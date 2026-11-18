"""No real analytics: every HTTP sender is replaced before any request."""
import asyncio
import json

import pytest
from pwc_mcp import mcp_analytics as analytics
from pwc_mcp.app import create_app
from starlette.datastructures import Headers
from starlette.testclient import TestClient
from test_mcp_profile import Catalog


@pytest.fixture(autouse=True)
def isolated_analytics(monkeypatch):
    monkeypatch.setenv("PWC_MCP_CURSOR_KEY_CURRENT", "test-only-cursor-secret")
    monkeypatch.delenv('PWC_POSTHOG_PROJECT_TOKEN', raising=False)
    monkeypatch.delenv('PWC_POSTHOG_HOST', raising=False)
    monkeypatch.setattr(analytics, '_pending', set())
    sent = []
    monkeypatch.setattr(analytics, '_post', lambda url, body: sent.append(json.loads(body)))
    return sent


def observe(method, params=None, ua='claude-code/2.4 Extra/9', first_party=False):
    state = {}
    body = {'jsonrpc': '2.0', 'method': method, 'params': params or {}, 'id': 'private-id'}
    analytics.observe_request(state, json.dumps(body).encode(), Headers({'user-agent': ua}),
                              {'browse_catalog'}, first_party=first_party)
    return state


def emit(state, monkeypatch):
    monkeypatch.setenv('PWC_POSTHOG_PROJECT_TOKEN', 'test-token')
    async def run():
        analytics.capture_request(state, 200, '2026-07-28')
        await asyncio.gather(*analytics._pending)
    asyncio.run(run())


@pytest.mark.parametrize('method,event', [('initialize', 'catalog_mcp_client_initialized'),
    ('tools/list', 'catalog_mcp_tools_listed'), ('tools/call', 'catalog_mcp_tool_called')])
def test_events_caller_labels_and_privacy(method, event, monkeypatch, isolated_analytics):
    info = {'name': 'Claude Code', 'version': '2.4', 'title': 'do not send', 'websiteUrl': 'https://secret.test'}
    params = {'clientInfo': info, '_meta': {'io.modelcontextprotocol/clientInfo': info, 'cursor': 'secret-cursor'},
              'name': 'browse_catalog', 'arguments': {'query': 'private-query', 'paper_id': 1234}}
    state = observe(method, params)
    emit(state, monkeypatch)
    message = isolated_analytics[0]
    assert message['event'] == event
    props = message['properties']
    assert props['client_name'] == 'Claude Code' and props['client_version'] == '2.4'
    assert props['user_agent_product'] == 'claude-code' and props['user_agent_version'] == '2.4'
    assert props['client_source'] == 'request' and props['mcp_protocol'] == '2026-07-28'
    assert props['http_status'] == 200 and props['distinct_id'] == 'catalog-mcp-service'
    assert props['$process_person_profile'] is False and props['$geoip_disable'] is True
    assert ('tool' in props) == (method == 'tools/call')
    assert set(props) <= {'distinct_id', 'tool', 'client_name', 'client_version', 'user_agent_product',
        'user_agent_version', 'client_source', 'mcp_protocol', 'http_status', 'catalog_environment',
        '$process_person_profile', '$geoip_disable'}
    assert all(secret not in json.dumps(message) for secret in ['private', '1234', 'secret', 'Extra', 'title', 'websiteUrl'])


@pytest.mark.parametrize('value,expected', [('normal.Name_1 -', 'normal.Name_1 -'),
    ('a/b?query', 'other'), ('test@example.com', 'other'), ('bad\nname', 'other'), ('claude😀', 'other'),
    ('1.2.3.4', 'other'), ('2001:db8::1', 'other'), ('', None), (None, None), ({'name': 'x'}, None)])
def test_restricted_labels(value, expected):
    assert analytics.label(value, 64) == expected


def test_caps_reject_bad_suffix_and_ua_first_product_only():
    state = observe('initialize', {'clientInfo': {'name': 'a'*100, 'version': 'b'*100}}, ua='python-httpx/0.28.1 comment/private')
    props = state['catalog_analytics'][1]
    assert props['client_name'] == 'a'*64 and props['client_version'] == 'b'*32
    assert props['user_agent_product'] == 'python-httpx' and props['user_agent_version'] == '0.28.1'
    assert analytics.label('a'*100 + '@secret', 64) == 'other'
    assert len(analytics.request_properties({}, Headers({'user-agent': 'a'*100 + '/' + 'v'*100}))['user_agent_version']) == 32


def test_stateless_no_identity_inference_and_absent_values_stay_absent():
    observe('initialize', {'clientInfo': {'name': 'legacy', 'version': '1'}})
    state = observe('tools/call', {'name': 'browse_catalog'}, ua='')
    assert state['catalog_analytics'][1] == {'client_source': 'none', 'tool': 'browse_catalog'}
    state = observe('tools/list', ua='node')
    assert state['catalog_analytics'][1] == {'client_source': 'none', 'user_agent_product': 'node'}


@pytest.mark.parametrize('method,params', [('notifications/initialized', {}), ('bogus', {}),
    ('tools/call', {'name': 'private-tool'}), ('tools/call', {'name': ['browse_catalog']}),
    ('tools/call', {'name': 'read_paper', 'arguments': {'paper': 'secret'}})])
def test_only_allowlisted_events_and_tools(method, params):
    assert observe(method, params) == {}


def test_no_token_no_tasks(monkeypatch, isolated_analytics):
    analytics.capture_request(observe('tools/list'), 200, 'legacy')
    assert not analytics._pending and not isolated_analytics


def test_pending_bound_and_no_await_on_request(monkeypatch, isolated_analytics):
    monkeypatch.setenv('PWC_POSTHOG_PROJECT_TOKEN', 'test')
    async def run():
        for _ in range(20):
            analytics.capture_request(observe('tools/list'), 429, 'private-protocol')
        assert len(analytics._pending) == 8
        await asyncio.gather(*analytics._pending)
        await asyncio.sleep(0)
        assert not analytics._pending
    asyncio.run(run())
    assert len(isolated_analytics) == 8
    assert all(event['properties']['mcp_protocol'] == 'unknown' for event in isolated_analytics)


def test_sender_outage_is_ignored_without_network(monkeypatch):
    # Test the actual sender independently of the autouse stub.
    import importlib.util
    spec = importlib.util.spec_from_file_location('sender', analytics.__file__)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    def fail(*args, **kwargs):
        raise OSError('offline')
    monkeypatch.setattr(module.urllib.request, 'urlopen', fail)
    module._post('https://example.invalid', b'{}')


@pytest.mark.parametrize('peer,forwarded,expected', [('127.0.0.1', '', True),
    ('192.0.2.1', '', False), ('127.0.0.1', '192.0.2.1', False), ('127.0.0.1', 'client:assistant-' + 'b'*64, False)])
def test_first_party_header_only_inside_existing_trust_boundary(peer, forwarded, expected, monkeypatch):
    captured = []
    monkeypatch.setattr('pwc_mcp.app.capture_request', lambda state, status, protocol: captured.append((state, status, protocol)))
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream',
               'MCP-Protocol-Version': '2025-11-25', 'X-PwC-MCP-Client': 'assistant-' + 'a'*64}
    if forwarded:
        headers['X-Forwarded-For'] = forwarded
    with TestClient(create_app(Catalog(), allowed_hosts=['testserver']), client=(peer, 1234)) as client:
        response = client.post('/mcp', headers=headers, json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {}})
    assert response.status_code == 200
    props = captured[-1][0]['catalog_analytics'][1]
    assert props.get('first_party_assistant', False) is expected
    assert peer not in json.dumps(props) and 'a'*64 not in json.dumps(props)


def test_initialize_and_listing_are_seen_by_middleware(monkeypatch):
    captured = []
    monkeypatch.setattr('pwc_mcp.app.capture_request', lambda state, status, protocol: captured.append((state, status, protocol)))
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}
    with TestClient(create_app(Catalog(), allowed_hosts=['testserver'])) as client:
        result = client.post('/mcp', headers=headers, json={'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
            'params': {'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'outside', 'version': '1'}}})
    assert result.status_code == 200
    state, status, protocol = captured[0]
    assert protocol == 'legacy'
    assert state['catalog_analytics'][0] == 'catalog_mcp_client_initialized'
    assert state['catalog_analytics'][1]['client_name'] == 'outside' and status == 200


def test_embedded_address_labels_are_replaced():
    assert analytics.label('client 192.0.2.1', 64) == 'other'
