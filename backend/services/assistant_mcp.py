"""Credential-free, bounded access to the catalog's stateless MCP server.

Adapted from chat_pwc_mcp's JSON-RPC transport. Only a server-derived visitor
hash may identify direct loopback requests; raw cookies, credentials and
arbitrary URLs supplied by the model are never forwarded to the catalog.
"""

import asyncio
import json
import re
import time
from copy import deepcopy
from ipaddress import ip_address
from urllib.parse import urlsplit
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from backend.services.assistant_catalog_links import add_catalog_urls
from backend.services.assistant_facets import FACET_TOOLS, describe_facets, explain_empty, invalid_facet, vocabulary
from backend.services.assistant_tool_budget import bounded_arguments, bounded_tool, compact_result
from backend.services.assistant_post_metadata import enrich_posts, lookup_post_metadata
from backend.models.assistant_tools import FindPostsArguments, SuggestFollowUpsArguments
from backend.services.assistant_followups import FollowUpState, DESCRIPTION as FOLLOW_UP_DESCRIPTION
from backend.services.assistant_posts import DESCRIPTION as POSTS_DESCRIPTION, find_posts

MCP_TOOL_NAMES = frozenset({
    "search_papers", "browse_catalog", "catalog_filters", "get_paper_info",
    "list_developers", "get_developer", "list_organizations", "get_organization",
    "list_recent_papers", "list_trending_papers", "get_related_papers", "read_paper",
})
TOOL_NAMES = MCP_TOOL_NAMES | {"find_posts", "suggest_follow_ups"}
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_RESULT_BYTES = 16 * 1024
READ_PAPER_BYTES = 8 * 1024
TRUNCATION = "\n[Result truncated; narrow the request.]"
FILTER_CACHE = {}
FILTER_LOCKS = {}
TOOL_CACHE = {}
TOOL_LOCKS = {}
TOOL_CACHE_TTL_SECONDS = 600
BUSY_RETRY_SECONDS = 0.5
CATALOG_BUSY_MESSAGE = "The catalog is busy. Please try again in a moment."

META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
}


class AssistantMcpError(Exception):
    """A public error containing no upstream response or request contents."""


class AssistantMcpBusy(AssistantMcpError):
    """Catalog admission refused a request; retrying later is safe."""

    def __init__(self):
        super().__init__(CATALOG_BUSY_MESSAGE)


def loopback_endpoint(endpoint):
    host = urlsplit(endpoint).hostname
    if host == "localhost":
        return True
    try:
        return ip_address(host or "").is_loopback
    except ValueError:
        return False


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
    def __init__(self, client: httpx.AsyncClient, endpoint: str, *, lookup=lookup_post_metadata, sessions=None, visitor_hash=None):
        self.client = client
        self.endpoint = endpoint
        self.lookup = lookup
        self.sessions = sessions
        self.follow_up_state = FollowUpState(sessions=sessions)
        self.rate_limited = False
        if visitor_hash is not None and not re.fullmatch(r"[0-9a-f]{64}", visitor_hash):
            raise ValueError("Expected a hashed visitor identity")
        # The pinned MCP server honors this only for direct loopback peers with
        # no forwarded headers. Remote/Compose connections retain the IP bucket.
        self.client_identity = f"assistant-{visitor_hash}" if visitor_hash and loopback_endpoint(endpoint) else None

    async def _request(self, method: str, params: dict) -> dict:
        self.rate_limited = False
        for attempt in range(2):
            try:
                result = await self._request_once(method, params)
            except AssistantMcpBusy:
                self.rate_limited = True
                if attempt:
                    raise
                # The loop's research deadline includes this one short retry.
                # Keep valid discovery cached while the catalog is busy.
                await asyncio.sleep(BUSY_RETRY_SECONDS)
            except AssistantMcpError:
                self.rate_limited = False
                TOOL_CACHE.pop(self.endpoint, None)
                raise
            else:
                self.rate_limited = False
                return result
        raise AssertionError("unreachable")

    async def _request_once(self, method: str, params: dict) -> dict:
        request_id = str(uuid.uuid4())
        headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
        if self.client_identity:
            headers["X-PwC-MCP-Client"] = self.client_identity
        try:
            async with asyncio.timeout(30):
                async with self.client.stream(
                    "POST", self.endpoint,
                    headers=headers,
                    json={"jsonrpc": "2.0", "id": request_id, "method": method,
                          "params": {**params, "_meta": META}},
                ) as response:
                    if response.status_code == 429:
                        raise AssistantMcpBusy()
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

    def begin_turn(self, question):
        self.follow_up_state = FollowUpState(question, self.sessions)

    async def tools(self) -> list[dict]:
        if self.follow_up_state.used:
            return []  # Verification ends research; next pass writes the answer.
        lock = TOOL_LOCKS.setdefault(self.endpoint, asyncio.Lock())
        async with lock:
            cached = TOOL_CACHE.get(self.endpoint)
            if cached and cached[0] > time.monotonic():
                return deepcopy(cached[1])
            TOOL_CACHE.pop(self.endpoint, None)
            tools = await self._discover_tools()
            TOOL_CACHE[self.endpoint] = (time.monotonic() + TOOL_CACHE_TTL_SECONDS, tools)
            return deepcopy(tools)

    async def _discover_tools(self) -> list[dict]:
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
        selected.append({"name": "suggest_follow_ups", "description": FOLLOW_UP_DESCRIPTION,
                         "inputSchema": SuggestFollowUpsArguments.model_json_schema()})
        choices = vocabulary(await self.filters())
        return [describe_facets(bounded_tool(tool), choices) for tool in selected]

    async def call(self, name: str, arguments: dict) -> ToolResult:
        # Reject even before schema discovery or opening a connection.
        if name not in TOOL_NAMES:
            raise AssistantMcpError("This tool is not allowed.")
        arguments = bounded_arguments(name, arguments)
        if name == "suggest_follow_ups":
            payload = await self.follow_up_state.suggest(arguments)
            return cap_payload(payload, limit=MAX_RESULT_BYTES, is_json=True, is_error=False)
        if self.follow_up_state.used:
            return cap_payload({"error": "Research has ended. Write the answer using collected evidence and kept follow-ups."},
                               limit=MAX_RESULT_BYTES, is_json=True, is_error=True)
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
        if is_error:
            TOOL_CACHE.pop(self.endpoint, None)
        if is_json and not is_error:
            payload = compact_result(name, add_catalog_urls(name, payload), arguments)
            payload = await enrich_posts(payload, self.lookup)
            payload = explain_empty(name, payload, arguments)
        return cap_payload(payload, limit=READ_PAPER_BYTES if name == "read_paper" else MAX_RESULT_BYTES,
                           is_json=is_json, is_error=is_error)
