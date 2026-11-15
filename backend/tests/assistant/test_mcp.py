import asyncio
import json

import httpx
import pytest

from backend.services.assistant_mcp import (
    AssistantMcpError, CatalogMcp, MAX_RESPONSE_BYTES, MAX_RESULT_BYTES,
    READ_PAPER_BYTES, TOOL_NAMES, MCP_TOOL_NAMES,
)


FILTERS = {"topic": {"penetration-testing": "Penetration testing"}, "target": {"web": "Web"},
           "contribution": {"benchmark": "Benchmark"}, "kind": {"post": "Post", "paper": "Paper"}, "year": {"2026": "2026"}}


def run(call, handler):
    def dispatch(request):
        body = json.loads(request.content)
        if body["method"] == "tools/call" and body["params"]["name"] == "catalog_filters":
            return response(request, {"structuredContent": FILTERS})
        return handler(request)
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as client:
            return await call(CatalogMcp(client, "http://catalog.test/mcp", lookup=lambda ids: {}))
    return asyncio.run(go())


def response(request, result):
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": json.loads(request.content)["id"], "result": result})


def test_allowlist_is_exact_and_discovery_excludes_other_tools():
    assert TOOL_NAMES == {
        "search_papers", "browse_catalog", "catalog_filters", "get_paper_info",
        "list_developers", "get_developer", "list_organizations", "get_organization",
        "list_recent_papers", "list_trending_papers", "get_related_papers", "read_paper", "find_posts", "suggest_follow_ups",
    }
    tools = run(lambda m: m.tools(), lambda r: response(r, {"tools": [
        {"name": name, "inputSchema": {"type": "object"}}
        for name in [*MCP_TOOL_NAMES, "find_posts", "delete_paper"]
    ]}))
    assert {t["function"]["name"] for t in tools} == TOOL_NAMES


def test_disallowed_tool_never_contacts_network():
    def forbidden(request):
        pytest.fail("Network called for a forbidden tool")
    with pytest.raises(AssistantMcpError, match="not allowed"):
        run(lambda m: m.call("delete_paper", {}), forbidden)


@pytest.mark.parametrize("name,cap", [("search_papers", MAX_RESULT_BYTES), ("read_paper", READ_PAPER_BYTES)])
def test_result_cap_is_utf8_safe_and_records_original_size(name, cap):
    result = run(lambda m: m.call(name, {}), lambda r: response(r, {"content": [{"type": "text", "text": "🦊" * cap}]}))
    assert len(result.text.encode()) <= cap
    assert result.full_bytes > cap
    assert result.truncated
    assert result.text.endswith("[Result truncated; narrow the request.]")
    assert result.full_bytes == len(("🦊" * cap).encode())


def test_structured_content_is_one_compact_copy_before_capping():
    data = {"results": [{"title": "Catalog item", "abstract": "Evidence " * 20} for _ in range(45)]}
    envelope = {"content": [{"type": "text", "text": json.dumps(data, indent=2)}],
                "structuredContent": data, "isError": False}
    assert len(json.dumps(envelope).encode()) > MAX_RESULT_BYTES
    result = run(lambda m: m.call("browse_catalog", {}), lambda r: response(r, envelope))
    projected = json.loads(result.text)
    assert projected["total"] == 45 and projected["returned"] == 10
    assert projected["results"] == data["results"][:10]
    assert "structuredContent" not in result.text and '"content"' not in result.text
    assert result.full_bytes == len(result.text.encode())
    assert not result.truncated and not result.is_error


@pytest.mark.parametrize("structured", [None, {}])
def test_text_fallback_and_structured_error_preserve_is_error(structured):
    envelope = {"isError": True, "content": [{"type": "text", "text": "No cached text."},
                 {"type": "image", "data": "ignored"}, {"type": "text", "text": "Try the source."}]}
    if structured is not None:
        envelope["structuredContent"] = structured
    result = run(lambda m: m.call("read_paper", {}), lambda r: response(r, envelope))
    assert result.text == ("{}" if structured is not None else "No cached text.\nTry the source.")
    assert result.full_bytes == len(result.text.encode())
    assert result.is_error


@pytest.mark.parametrize("kind", ["http", "transport", "json", "rpc", "oversize"])
def test_failed_call_is_sanitized(kind):
    def fail(request):
        if kind == "transport":
            raise httpx.ConnectError("private upstream detail")
        if kind == "http":
            return httpx.Response(500, text="private upstream detail")
        if kind == "json":
            return httpx.Response(200, text="private upstream detail")
        if kind == "oversize":
            return httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1))
        return httpx.Response(200, json={"error": "private upstream detail"})
    with pytest.raises(AssistantMcpError) as error:
        run(lambda m: m.call("search_papers", {}), fail)
    assert "private" not in str(error.value)


def test_mcp_tool_error_is_preserved_but_bounded():
    result = run(lambda m: m.call("read_paper", {}), lambda r: response(r, {"isError": True, "content": []}))
    assert result.is_error
    assert not result.truncated
