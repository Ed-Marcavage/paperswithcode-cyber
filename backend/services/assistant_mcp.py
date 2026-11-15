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
from backend.services.assistant_facets import FACET_TOOLS, describe_facets, explain_empty, invalid_facet, vocabulary
from backend.services.assistant_tool_budget import bounded_arguments, bounded_tool, compact_result
from backend.services.assistant_post_metadata import enrich_posts, lookup_post_metadata
from backend.models.assistant_tools import FindPostsArguments
from backend.services.assistant_posts import DESCRIPTION as POSTS_DESCRIPTION, find_posts

MCP_TOOL_NAMES = frozenset({
    "search_papers", "browse_catalog", "catalog_filters", "get_paper_info",
    "list_developers", "get_developer", "list_organizations", "get_organization",
    "list_recent_papers", "list_trending_papers", "get_related_papers", "read_paper",
})
TOOL_NAMES = MCP_TOOL_NAMES | {"find_posts"}
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_RESULT_BYTES = 16 * 1024
READ_PAPER_BYTES = 8 * 1024
TRUNCATION = "\n[Result truncated; narrow the request.]"
FILTER_CACHE = {}
FILTER_LOCKS = {}

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


def result_payload(value: dict[str, Any]):
    # One copy of the MCP data, never both the text and structured envelope.
    if value.get("structuredContent") is not None:
        return value["structuredContent"], True
    content = "\n".join(block["text"] for block in value.get("content", [])
                        if isinstance(block, dict) and block.get("type") == "text"
                        and isinstance(block.get("text"), str))
    try:
        return json.loads(content), True
    except ValueError:
        return content, False


def cap_payload(payload, *, limit, is_json, is_error):
    content = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) if is_json else payload
    raw = content.encode()
    truncated = len(raw) > limit
    if truncated:
        content = raw[:limit - len(TRUNCATION.encode())].decode("utf-8", errors="ignore") + TRUNCATION
    return ToolResult(content, len(raw), truncated, is_error)


class CatalogMcp:
    def __init__(self, client: httpx.AsyncClient, endpoint: str, *, lookup=lookup_post_metadata, sessions=None):
        self.client = client
        self.endpoint = endpoint
        self.lookup = lookup
        self.sessions = sessions

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

    async def filters(self):
        # Catalog vocabulary is public and stable for this process's catalog snapshot.
        # Key by endpoint so separate catalogs never share slugs. Failures are not cached.
        lock = FILTER_LOCKS.setdefault(self.endpoint, asyncio.Lock())
        async with lock:
            if self.endpoint not in FILTER_CACHE:
                result = await self._request("tools/call", {"name": "catalog_filters", "arguments": {}})
                payload, is_json = result_payload(result)
                if result.get("isError") or not is_json or not vocabulary(payload):
                    raise AssistantMcpError("The catalog filter choices are unavailable. Please try again.")
                FILTER_CACHE[self.endpoint] = payload
            return FILTER_CACHE[self.endpoint]

    async def tools(self) -> list[dict]:
        result = await self._request("tools/list", {})
        tools = result.get("tools")
        if not isinstance(tools, list) or any(not isinstance(t, dict) for t in tools):
            raise AssistantMcpError("The catalog tool list is invalid.")
        selected = [t for t in tools if t.get("name") in MCP_TOOL_NAMES]
        if len(selected) != len(MCP_TOOL_NAMES) or {t["name"] for t in selected} != MCP_TOOL_NAMES:
            raise AssistantMcpError("The catalog tool list is incomplete.")
        if any(not isinstance(t.get("inputSchema"), dict) for t in selected):
            raise AssistantMcpError("The catalog tool schemas are invalid.")
        selected.append({"name": "find_posts", "description": POSTS_DESCRIPTION,
                         "inputSchema": FindPostsArguments.model_json_schema()})
        choices = vocabulary(await self.filters())
        return [describe_facets(bounded_tool(tool), choices) for tool in selected]

    async def call(self, name: str, arguments: dict) -> ToolResult:
        # Reject even before schema discovery or opening a connection.
        if name not in TOOL_NAMES:
            raise AssistantMcpError("This tool is not allowed.")
        arguments = bounded_arguments(name, arguments)
        if name == "catalog_filters":
            return cap_payload(await self.filters(), limit=MAX_RESULT_BYTES, is_json=True, is_error=False)
        if name in FACET_TOOLS and any(axis in arguments and arguments[axis] != "" for axis in ("topic", "target", "contribution", "kind", "year")):
            invalid = invalid_facet(arguments, vocabulary(await self.filters()))
            if invalid:
                return cap_payload(invalid, limit=MAX_RESULT_BYTES, is_json=True, is_error=True)
        if name == "find_posts":
            payload, is_error = await find_posts(arguments, self.sessions)
            return cap_payload(payload, limit=MAX_RESULT_BYTES, is_json=True, is_error=is_error)
        upstream_arguments = {k: v for k, v in arguments.items() if k != "counts_only"}
        result = await self._request("tools/call", {"name": name, "arguments": upstream_arguments})
        payload, is_json = result_payload(result)
        is_error = bool(result.get("isError"))
        if is_json and not is_error:
            payload = compact_result(name, add_catalog_urls(name, payload), arguments)
            payload = await enrich_posts(payload, self.lookup)
            payload = explain_empty(name, payload, arguments)
        return cap_payload(payload, limit=READ_PAPER_BYTES if name == "read_paper" else MAX_RESULT_BYTES,
                           is_json=is_json, is_error=is_error)
