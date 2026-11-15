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
from backend.services.assistant_catalog_links import add_catalog_urls
from backend.services.assistant_tool_budget import bounded_arguments, bounded_tool, compact_result

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


def cap_result(value: dict[str, Any], limit: int, tool: str, arguments: dict | None = None) -> ToolResult:
    # MCP often repeats the same payload in text and structuredContent. Give
    # the model one copy; full_bytes measures that uncapped model input, not
    # the transport envelope (whose independent wire limit remains above).
    if value.get("structuredContent") is not None:
        payload = value["structuredContent"]
        if not value.get("isError"):
            payload = compact_result(tool, add_catalog_urls(tool, payload), arguments or {})
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    else:
        text = "\n".join(block["text"] for block in value.get("content", [])
                         if isinstance(block, dict) and block.get("type") == "text"
                         and isinstance(block.get("text"), str))
        if not value.get("isError"):
            try:
                payload = json.loads(text)
            except ValueError:
                pass  # Plain MCP text is already suitable model input.
            else:
                text = json.dumps(compact_result(tool, add_catalog_urls(tool, payload), arguments or {}), ensure_ascii=False, separators=(",", ":"))
    raw = text.encode()
    truncated = len(raw) > limit
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
        return [bounded_tool(tool) for tool in selected]

    async def call(self, name: str, arguments: dict) -> ToolResult:
        # Reject even before schema discovery or opening a connection.
        if name not in TOOL_NAMES:
            raise AssistantMcpError("This tool is not allowed.")
        arguments = bounded_arguments(name, arguments)
        upstream_arguments = {k: v for k, v in arguments.items() if k != "counts_only"}
        result = await self._request("tools/call", {"name": name, "arguments": upstream_arguments})
        return cap_result(result, READ_PAPER_BYTES if name == "read_paper" else MAX_RESULT_BYTES, name, arguments)
