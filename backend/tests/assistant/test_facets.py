import asyncio
import json

import httpx
import pytest

from backend.services.assistant_mcp import CatalogMcp, TOOL_NAMES
from backend.services.assistant_tool_budget import bounded_arguments
from backend.tests.assistant.test_mcp import FILTERS, response
from backend.tests.assistant.test_loop import FakeServices, tool_chunk, text_chunk


def exercise(operation, *, filters=FILTERS, items=None):
    requests = []
    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if body['method'] == 'tools/list':
            result = {'tools': [{'name': n, 'inputSchema': {'type': 'object'}} for n in TOOL_NAMES]}
        elif body['params']['name'] == 'catalog_filters':
            result = {'structuredContent': {'data': filters}}
        else:
            result = {'structuredContent': {'total': len(items or []), 'results': items or []}}
        return response(request, result)
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await operation(client)
    return asyncio.run(go()), requests


@pytest.mark.parametrize('value', ['["penetration-testing"]', ['penetration-testing'], ' penetration-testing '])
def test_single_facet_is_normalized_before_call(value):
    async def operation(client):
        return await CatalogMcp(client, 'http://facets.test/mcp', lookup=lambda ids: {}).call(
            'browse_catalog', {'topic': value, 'kind': '["post"]'})
    result, requests = exercise(operation)
    assert not result.is_error
    assert requests[-1]['params']['arguments'] == {'topic': 'penetration-testing', 'kind': 'post', 'limit': 10}
    assert 'Zero items' in result.text and 'topic filter' in result.text


@pytest.mark.parametrize('value', ['pentesting', ['penetration-testing', 'other'], '["penetration-testing","other"]', 3, 0])
def test_invalid_or_multiple_values_return_choices_without_browsing(value):
    async def operation(client):
        return await CatalogMcp(client, 'http://facets.test/mcp').call('browse_catalog', {'topic': value})
    result, requests = exercise(operation)
    data = json.loads(result.text)
    assert result.is_error and data['valid_values'] == ['penetration-testing']
    assert 'one valid slug' in data['error']
    assert [r['params']['name'] for r in requests] == ['catalog_filters']


def test_vocabulary_is_cached_across_instances_and_in_descriptions():
    async def operation(client):
        first = CatalogMcp(client, 'http://facets.test/mcp')
        tools = await first.tools()
        cached = await CatalogMcp(client, first.endpoint).call('catalog_filters', {})
        await CatalogMcp(client, 'http://other.test/mcp').call('catalog_filters', {})
        return tools, cached
    (tools, cached), requests = exercise(operation)
    browse = next(t['function'] for t in tools if t['function']['name'] == 'browse_catalog')
    for axis in ('topic', 'target', 'contribution', 'kind'):
        assert axis + ':' in browse['description']
        assert all(slug in browse['description'] for slug in FILTERS[axis])
    assert len(requests) == 3  # One list + one filter fetch per endpoint.
    assert json.loads(cached.text)['data'] == FILTERS


def test_zero_search_and_page_hints_do_not_claim_missing_coverage():
    async def operation(client):
        mcp = CatalogMcp(client, 'http://facets.test/mcp')
        return [await mcp.call('search_papers', {'query': 'long title'}),
                await mcp.call('browse_catalog', {'offset': 100})]
    results, _ = exercise(operation)
    assert 'searches titles' in results[0].text and 'Reset offset' in results[1].text
    assert all('does not establish' in result.text for result in results)


def test_array_and_scalar_variants_share_turn_cache_and_trace_effective_argument():
    services = FakeServices([[tool_chunk(name='browse_catalog', arguments='{"kind":["post"]}')],
                             [tool_chunk(name='browse_catalog', arguments='{"kind":"post"}')], [text_chunk()]])
    turn, _ = asyncio.run(services.run())
    steps = [s for s in turn.steps if s['kind'] == 'tool']
    assert len(services.tool_requests) == 1
    assert steps[0]['effective_arguments'] == {'kind': 'post', 'limit': 10}
    assert steps[1]['cached_from'] == steps[0]['call_id']
    assert bounded_arguments('browse_catalog', {'topic': []})['topic'] == ''
