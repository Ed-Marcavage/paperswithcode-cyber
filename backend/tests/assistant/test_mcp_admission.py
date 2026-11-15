"""Tool discovery caching, bounded catalog retries and private client identities."""

import asyncio
import hashlib
import json
import time

import httpx
import pytest

from backend.services import assistant_mcp
from backend.services.assistant_loop import TurnLimits
from backend.services.assistant_mcp import AssistantMcpBusy, AssistantMcpError, CatalogMcp, MCP_TOOL_NAMES
from backend.tests.assistant.test_loop import FakeServices, text_chunk, tool_chunk
from backend.tests.assistant.test_mcp import FILTERS, response


def tool_list():
    return {"tools": [{"name": name, "inputSchema": {"type": "object"}} for name in MCP_TOOL_NAMES]}


def successful(request):
    payload = json.loads(request.content)
    if payload["method"] == "tools/list":
        return response(request, tool_list())
    if payload["params"]["name"] == "catalog_filters":
        return response(request, {"structuredContent": FILTERS})
    return response(request, {"structuredContent": {"title": "Evidence"}})


def test_tools_cache_is_shared_coalesced_bounded_by_ttl_and_copied():
    calls = []
    async def handler(request):
        calls.append(json.loads(request.content))
        await asyncio.sleep(0)
        return successful(request)
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            endpoint = "http://catalog.test/mcp"
            clients = [CatalogMcp(client, endpoint) for _ in range(4)]
            tools = await asyncio.gather(*(mcp.tools() for mcp in clients))
            assert len(calls) == 2  # One tools/list and one vocabulary request.
            tools[0][0]["function"]["name"] = "mutated"
            assert (await clients[1].tools())[0]["function"]["name"] != "mutated"
            expiry, value = assistant_mcp.TOOL_CACHE[endpoint]
            assert 590 < expiry - time.monotonic() <= 600
            assistant_mcp.TOOL_CACHE[endpoint] = (time.monotonic() - 1, value)
            await clients[2].tools()
            assert len(calls) == 3
            await CatalogMcp(client, "http://other.test/mcp").tools()
            assert len(calls) == 5  # Other endpoint has separate tools and vocabulary.
    asyncio.run(go())


@pytest.mark.parametrize("failure", ["transport", "rpc", "tool"])
def test_catalog_failure_invalidates_discovery_for_the_next_turn(failure):
    calls = []
    fail = False
    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        if fail and payload["params"].get("name") == "search_papers":
            if failure == "transport":
                raise httpx.ConnectError("private detail")
            if failure == "rpc":
                return httpx.Response(200, json={"error": "private detail"})
            return response(request, {"isError": True, "content": []})
        return successful(request)
    async def go():
        nonlocal fail
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            mcp = CatalogMcp(client, "http://catalog.test/mcp", lookup=lambda ids: {})
            await mcp.tools()
            fail = True
            if failure == "tool":
                assert (await mcp.call("search_papers", {})).is_error
            else:
                with pytest.raises(AssistantMcpError):
                    await mcp.call("search_papers", {})
            assert not assistant_mcp.TOOL_CACHE
            fail = False
            await mcp.tools()
            assert sum(c["method"] == "tools/list" for c in calls) == 2
    asyncio.run(go())


def test_invalid_discovery_is_not_cached():
    count = 0
    def handler(request):
        nonlocal count
        count += 1
        return response(request, {"tools": []}) if count == 1 else successful(request)
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            mcp = CatalogMcp(client, "http://catalog.test/mcp")
            with pytest.raises(AssistantMcpError, match="incomplete"):
                await mcp.tools()
            assert not assistant_mcp.TOOL_CACHE
            assert await mcp.tools()
    asyncio.run(go())


@pytest.mark.parametrize("recover", [False, True])
def test_429_waits_once_retries_once_and_preserves_valid_cache(monkeypatch, recover):
    waits = []
    count = 0
    async def sleep(delay):
        waits.append(delay)
    monkeypatch.setattr(assistant_mcp.asyncio, "sleep", sleep)
    def handler(request):
        nonlocal count
        count += 1
        return successful(request) if recover and count == 2 else httpx.Response(429, text="private detail")
    async def go():
        endpoint = "http://catalog.test/mcp"
        assistant_mcp.TOOL_CACHE[endpoint] = (time.monotonic() + 600, [])
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            mcp = CatalogMcp(client, endpoint, lookup=lambda ids: {})
            if recover:
                assert not (await mcp.call("search_papers", {})).is_error
                assert not mcp.rate_limited
            else:
                with pytest.raises(AssistantMcpBusy, match="catalog is busy"):
                    await mcp.call("search_papers", {})
            assert endpoint in assistant_mcp.TOOL_CACHE
    asyncio.run(go())
    assert count == 2 and waits == [0.5]


@pytest.mark.parametrize("stage", ["tools/list", "catalog_filters", "search_papers"])
def test_turn_reports_catalog_busy_without_provider_error_or_finalizer(monkeypatch, stage):
    monkeypatch.setattr(assistant_mcp, "BUSY_RETRY_SECONDS", 0)
    services = FakeServices([[tool_chunk()]])
    original = services.mcp
    failures = []
    def handler(request):
        payload = json.loads(request.content)
        if payload["method"] == stage or payload["params"].get("name") == stage:
            failures.append(payload)
            return httpx.Response(429, text="private detail")
        return original(request)
    services.mcp = handler
    turn, events = asyncio.run(services.run())
    assert len(failures) == 2
    assert turn.status == "catalog_busy"
    assert len(services.model_requests) == (1 if stage == "search_papers" else 0)
    assert events[-1] == {"type": "error", "code": "catalog_busy", "retryable": True,
                          "message": assistant_mcp.CATALOG_BUSY_MESSAGE}
    assert "private detail" not in json.dumps(events)
    if stage == "search_papers":
        assert turn.steps[-1]["error"] == assistant_mcp.CATALOG_BUSY_MESSAGE
        assert events[-2]["type"] == "tool_finished" and events[-2]["error"]


def test_turn_deadline_interrupting_busy_wait_still_reports_catalog_busy(monkeypatch):
    monkeypatch.setattr(assistant_mcp, "BUSY_RETRY_SECONDS", 10)
    services = FakeServices([])
    requests = []
    def busy(request):
        requests.append(request)
        return httpx.Response(429)
    services.mcp = busy
    turn, events = asyncio.run(services.run(TurnLimits(seconds=.04, final_seconds=.02)))
    assert turn.status == "catalog_busy" and len(requests) == 1
    assert events[-1]["code"] == "catalog_busy" and not services.model_requests


def test_disconnect_during_busy_wait_propagates_cancellation(monkeypatch):
    entered = asyncio.Event()
    async def sleep(delay):
        entered.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(assistant_mcp.asyncio, "sleep", sleep)
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(429))) as client:
            task = asyncio.create_task(CatalogMcp(client, "http://catalog.test/mcp").tools())
            await entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    asyncio.run(go())


@pytest.mark.parametrize("endpoint,tagged", [
    ("http://127.0.0.1:7860/mcp", True), ("http://[::1]:7860/mcp", True),
    ("http://localhost:7860/mcp", True), ("http://mcp:7860/mcp", False),
    ("https://catalog.test/mcp", False),
])
def test_only_loopback_requests_send_server_derived_visitor_hash(endpoint, tagged):
    requests = []
    def handler(request):
        requests.append(request)
        return successful(request)
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            for visitor in ("synthetic-cookie-one", "synthetic-cookie-two"):
                digest = hashlib.sha256(visitor.encode()).hexdigest()
                mcp = CatalogMcp(client, endpoint, visitor_hash=digest, lookup=lambda ids: {})
                await mcp.call("search_papers", {})
                headers = requests[-1].headers
                assert headers.get("x-pwc-mcp-client") == (f"assistant-{digest}" if tagged else None)
                assert "cookie" not in headers and "x-forwarded-for" not in headers
                assert visitor not in str(headers) + requests[-1].content.decode()
            with pytest.raises(ValueError, match="hashed"):
                CatalogMcp(client, endpoint, visitor_hash="raw-cookie")
    asyncio.run(go())


def test_recovered_catalog_request_finishes_normally(monkeypatch):
    monkeypatch.setattr(assistant_mcp, "BUSY_RETRY_SECONDS", 0)
    services = FakeServices([[tool_chunk()], [text_chunk("Recovered answer")]])
    original = services.mcp
    count = 0
    def handler(request):
        nonlocal count
        count += 1
        return httpx.Response(429) if count == 1 else original(request)
    services.mcp = handler
    turn, _ = asyncio.run(services.run())
    assert turn.status == "done" and turn.text == "Recovered answer"


def test_http_route_uses_cookie_hash_and_ignores_browser_client_id(client, store, monkeypatch):
    from backend.assistant_config import get_assistant_settings
    from backend.routers import assistant
    from backend.tests.assistant.test_traces import fake_services

    monkeypatch.setattr(get_assistant_settings(), "mcp_url", "http://127.0.0.1:7860/mcp")
    services = fake_services(monkeypatch, [[text_chunk("Answer")]])
    factory = assistant.CatalogMcp
    identities = []
    def capture(http, endpoint, **kwargs):
        identities.append(kwargs["visitor_hash"])
        return factory(http, endpoint, **kwargs)
    monkeypatch.setattr(assistant, "CatalogMcp", capture)
    reply = client.post("/api/v1/assistant/turn", json={"question": "Hi"},
                        headers={"X-PwC-MCP-Client": "spoofed", "X-Forwarded-For": "192.0.2.1"})
    assert reply.status_code == 200
    cookie = client.cookies.get(assistant.COOKIE_NAME)
    assert identities == [hashlib.sha256(cookie.encode()).hexdigest()]
    assert "spoofed" not in reply.text and cookie not in reply.text
    assert identities[0] not in json.dumps(services.model_requests)


def test_catalog_busy_http_trace_does_not_disable_provider(client, store, monkeypatch):
    from backend.routers import assistant
    from backend.tests.assistant.test_traces import fake_services

    monkeypatch.setattr(assistant_mcp, "BUSY_RETRY_SECONDS", 0)
    fake_services(monkeypatch, [])
    busy_http = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(429)))
    monkeypatch.setattr(assistant, "CatalogMcp", lambda http, endpoint, **kw: CatalogMcp(busy_http, endpoint, **kw))
    reply = client.post("/api/v1/assistant/turn", json={"question": "Hello"})
    assert "catalog_busy" in reply.text and "provider_error" not in reply.text
    assert store.provider_status()["available"]
    run = next(store.runs(1))
    assert run["status"] == "catalog_busy" and run["error"] == assistant_mcp.CATALOG_BUSY_MESSAGE


def test_schema_failure_refreshes_tools_before_the_next_model_pass():
    services = FakeServices([[tool_chunk()], [text_chunk("New schema loaded")]])
    original = services.mcp
    lists = 0
    def handler(request):
        nonlocal lists
        payload = json.loads(request.content)
        if payload['method'] == 'tools/list':
            lists += 1
            tools = tool_list()
            for tool in tools['tools']:
                tool['description'] = f'Schema generation {lists}'
            return response(request, tools)
        if payload['params'].get('name') == 'search_papers':
            return response(request, {'isError': True, 'content': []})
        return original(request)
    services.mcp = handler
    turn, _ = asyncio.run(services.run())
    assert turn.status == 'done' and lists == 2
    assert 'Schema generation 2' in json.dumps(services.model_requests[-1]['tools'])
