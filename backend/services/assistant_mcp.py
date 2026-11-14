"""Credential-free, bounded access to the catalog's stateless MCP server.

Adapted from chat_pwc_mcp's JSON-RPC transport. No chat identity, credentials,
or arbitrary URL supplied by the model is forwarded to the catalog.
"""

import asyncio
import json
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

TOOL_NAMES = frozenset({
    "search_papers", "browse_catalog", "catalog_filters", "get_paper_info",
    "list_developers", "get_developer", "list_organizations", "get_organization",
    "list_recent_papers", "list_trending_papers", "get_related_papers", "read_paper",
})
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_RESULT_BYTES = 16 * 1024
READ_PAPER_BYTES = 8 * 1024
TRUNCATION = "\n[Result truncated; narrow the request.]"
META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
}


class AssistantMcpError(Exception):
    """A public error containing no upstream response or request contents."""


@dataclass(frozen=True)
class ToolResult:
    text: str
    full_bytes: int
    truncated: bool
    is_error: bool = False


def cap_result(value: dict[str, Any], limit: int) -> ToolResult:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    truncated = len(raw) > limit
    text = raw.decode()
    if truncated:
        text = raw[:limit - len(TRUNCATION.encode())].decode("utf-8", errors="ignore") + TRUNCATION
    return ToolResult(text, len(raw), truncated, bool(value.get("isError")))


class CatalogMcp:
    def __init__(self, client: httpx.AsyncClient, endpoint: str):
        self.client = client
        self.endpoint = endpoint

    async def _request(self, method: str, params: dict) -> dict:
        request_id = str(uuid.uuid4())
        try:
            async with asyncio.timeout(30):
                async with self.client.stream(
                    "POST", self.endpoint,
                    headers={"Accept": "application/json", "Accept-Encoding": "identity"},
                    json={"jsonrpc": "2.0", "id": request_id, "method": method,
                          "params": {**params, "_meta": META}},
                ) as response:
                    if response.status_code != 200:
                        raise AssistantMcpError("The catalog tools are unavailable. Please try again.")
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(raw) + len(chunk) > MAX_RESPONSE_BYTES:
                            raise AssistantMcpError("The catalog result is too large. Narrow the request.")
                        raw.extend(chunk)
                    value = json.loads(raw)
        except (httpx.HTTPError, TimeoutError, ValueError, UnicodeError) as error:
            raise AssistantMcpError("The catalog request failed. Please try again.") from error
        if (not isinstance(value, dict) or value.get("jsonrpc") != "2.0"
                or value.get("id") != request_id or "error" in value
                or not isinstance(value.get("result"), dict)):
            raise AssistantMcpError("The catalog returned an invalid response.")
        return value["result"]

    async def tools(self) -> list[dict]:
        result = await self._request("tools/list", {})
        tools = result.get("tools")
        if not isinstance(tools, list) or any(not isinstance(t, dict) for t in tools):
            raise AssistantMcpError("The catalog tool list is invalid.")
        selected = [t for t in tools if t.get("name") in TOOL_NAMES]
        if len(selected) != len(TOOL_NAMES) or {t["name"] for t in selected} != TOOL_NAMES:
            raise AssistantMcpError("The catalog tool list is incomplete.")
        if any(not isinstance(t.get("inputSchema"), dict) for t in selected):
            raise AssistantMcpError("The catalog tool schemas are invalid.")
        return [{"type": "function", "function": {
            "name": t["name"], "description": t.get("description", ""),
            "parameters": t["inputSchema"],
        }} for t in selected]

    async def call(self, name: str, arguments: dict) -> ToolResult:
        # Reject even before schema discovery or opening a connection.
        if name not in TOOL_NAMES:
            raise AssistantMcpError("This tool is not allowed.")
        result = await self._request("tools/call", {"name": name, "arguments": arguments})
        return cap_result(result, READ_PAPER_BYTES if name == "read_paper" else MAX_RESULT_BYTES)
