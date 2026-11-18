"""Exercise the Cyber profile through a real SDK client, with no HTTP/database."""
import asyncio
import json
from copy import deepcopy

import pytest
from mcp.client import Client
from pwc_cli.transport import SITE_URL, TransportError
from pwc_mcp.catalog import CatalogClient
from pwc_mcp.mcp_profile import INSTRUCTIONS, POST_TYPES, TOOL_ORDER
from pwc_mcp.server import build_server

VOCAB = {"topic": ["fuzzing", "repair"], "target": ["binaries", "source-code"],
         "contribution": ["system", "study"], "kind": ["paper", "post", "repository"],
         "year": ["2005", *map(str, range(2007, 2027))]}
POST = {"paper_id": "42", "reference": "42", "title": "Harness", "date_published": "2026-11-01",
        "facets": {"kind": ["post"]}, "source_url": "https://example.test/post", "publisher": "Example",
        "post": {"tldr": "x" * 2000, "agent_relevance": 4, "tier": "featured", "post_type": "engineering-practice",
                 "entities": [{"name": "omit me"}], "authors": ["omit"], "original_title": "omit"}}
NATIVE = {"id": "42", "title": "Harness", "authors": [], "published": "2026-11-01",
          "has_official_implementation": False, "code_repository_count": 0}


@pytest.fixture(autouse=True)
def test_environment(monkeypatch):
    monkeypatch.setenv("PWC_MCP_CURSOR_KEY_CURRENT", "test-only-cursor-secret")
    monkeypatch.delenv("PWC_POSTHOG_PROJECT_TOKEN", raising=False)


class Catalog:
    def __init__(self):
        self.calls = []
        self.empty = False
        self.rows = [deepcopy(POST)]

    def profile_vocabulary(self):
        return VOCAB

    def discovery(self, path, params=None):
        self.calls.append((path, params))
        if path == "filters":
            return {k: {v: v for v in values} for k, values in VOCAB.items()}
        if path == "metadata":
            rows = []
            for ref in params['references'].split(','):
                rows.append({'paper_id': ref, 'reference': ref, 'title': POST['title'],
                             'publisher': 'Example', 'date_published': '2026-11-01',
                             'summary': 'x'*600 + '…', 'agent_relevance': 4, 'tier': 'featured',
                             'post_type': 'engineering-practice', 'facets': {'kind': ['post']},
                             'source_url': POST['source_url']})
            return {"results": rows}
        if path.startswith("papers/"):
            return deepcopy(POST)
        if path == "posts":
            return {"total": 0 if self.empty else 1, "results": [] if self.empty else [{
                        'id': row['paper_id'], 'title': row['title'], 'publisher': row['publisher'],
                        'published': row['date_published'], 'source_url': row['source_url'],
                        'tldr': row['post']['tldr'][:600] + '…', 'summary': row['post']['tldr'][:600] + '…',
                        'agent_relevance': row['post']['agent_relevance'], 'post_type': row['post']['post_type'],
                        'tier': row['post']['tier']} for row in self.rows],
                    "match_mode": "any_word", "sort": "text_rank_then_score", "relaxations": ["Text relaxed"]}
        return {"total": 0 if self.empty else 99, "results": [] if self.empty else deepcopy(self.rows)}

    def developers(self, params):
        self.calls.append(('developers', params))
        return {'count': 53, 'results': [{'github_id': 9, 'login': 'user', 'agent_work_count': 8,
                                        'repository_count': 10, 'owned_stars': 12}]}

    def developer(self, github_id):
        return {'github_id': github_id, 'login': 'user', 'repositories': [
            {'url': f'https://github.com/org/repo{i}', 'description': 'x'*2000} for i in range(40)]}

    def resolve_paper(self, paper):
        return '42'

    def query(self, command, options):
        self.calls.append((command, options))
        if command == ('paper', 'info'):
            return {**NATIVE, 'abstract': 'native abstract', 'repositories': [{'url': 'https://github.com/org/repo', 'is_official': True}]}
        if command == ('paper', 'lineage', 'list'):
            return {'paper': NATIVE, 'predecessors': [dict(NATIVE, id=str(i)) for i in range(1,41)], 'successors': []}
        if command == ('organization', 'list'):
            return {'count': 45, 'results': [{'id': str(i), 'slug': f'org-{i}', 'name': 'Example',
                      'description': 'x'*4000, 'post_count': 10, 'top_trending_paper': NATIVE} for i in range(45)]}
        if command == ('organization',):
            return {'id': '3', 'slug': 'example', 'name': 'Example', 'top_trending_paper': NATIVE}
        if command in {('conference', 'list'), ('framework', 'list')}:
            return {'count': 40, 'results': [{'id': str(i), 'name': str(i), 'description': 'x'*4000} for i in range(40)]}
        if command == ('task', 'list') and options.get('group_by_area'):
            return {'results': [{'id': '1', 'name': 'Security', 'tasks': [{'id': str(i), 'name': 'task'} for i in range(40)]}]}
        if command in {('task', 'list'), ('method', 'list')}:
            return {'count': 100, 'results': [{'id': '1', 'name': 'Task', 'description': 'x'*4000}]}
        return {'count': 120, 'results': [deepcopy(NATIVE)]}


def call(name, args=None, catalog=None):
    catalog = catalog or Catalog()
    async def run():
        async with Client(build_server(catalog)) as client:
            return await client.call_tool(name, args or {})
    return asyncio.run(run()), catalog


def payload(result):
    assert result.structured_content is None
    assert len(result.content) == 1
    text = result.content[0].text
    value = json.loads(text)
    assert text == json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value


def test_browse_forwards_filters_and_compacts_post():
    result, cat = call('browse_catalog', {'topic': '["fuzzing"]', 'kind': 'post', 'tier': 'featured',
                                         'post_type': 'engineering-practice', 'min_agent_relevance': 3, 'limit': 2})
    assert not result.is_error
    args = cat.calls[0][1]
    assert args['topic'] == 'fuzzing' and args['min_agent_relevance'] == 3 and args['tier'] == 'featured'
    assert args['post_type'] == 'engineering-practice' and args['limit'] == 2
    row = payload(result)['results'][0]
    assert row['catalog_url'] == SITE_URL + '/paper/42'
    assert row['publisher'] == 'Example' and row['published'] == '2026-11-01'
    assert len(row['summary']) == 601 and row['agent_relevance'] == 4
    assert row['tier'] == 'featured' and row['post_type'] == 'engineering-practice'
    assert 'post' not in row and 'entities' not in json.dumps(payload(result))


@pytest.mark.parametrize('name,args,field,valid', [
    ('browse_catalog', {'topic': 'nope'}, 'topic', 'fuzzing'),
    ('browse_catalog', {'topic': '["fuzzing", "repair"]'}, 'topic', 'repair'),
    ('browse_catalog', {'target': '["binaries","source-code"]'}, 'target', 'binaries'),
    ('browse_catalog', {'kind': 'blog'}, 'kind', 'post'),
    ('browse_catalog', {'year': '1900'}, 'year', '2026'),
    ('browse_catalog', {'post_type': 'blog'}, 'post_type', 'engineering-practice'),
    ('find_posts', {'tier': 'gold'}, 'tier', 'featured'),
    ('list_developers', {'sort': 'random'}, 'sort', 'agent'),
])
def test_bad_filters_are_actionable_errors_before_api(name, args, field, valid):
    result, cat = call(name, args)
    assert result.is_error and not cat.calls
    assert field in result.content[0].text and valid in result.content[0].text


@pytest.mark.parametrize('name,args', [('browse_catalog', {'limit': 26}), ('browse_catalog', {'offset': 2501}),
    ('find_posts', {'limit': 11}), ('find_posts', {'query': 'x'*201}), ('find_posts', {'min_agent_relevance': 5}),
    ('list_organizations', {'limit': 0}), ('list_developers', {'limit': 26})])
def test_bounds(name, args):
    result, cat = call(name, args)
    assert result.is_error and not cat.calls


def test_find_posts_preserves_implicit_vs_explicit_relevance_and_disclosure():
    result, cat = call('find_posts', {'query': 'harness', 'subtopic': 'memory', 'post_type': 'engineering-practice',
        'tier': 'featured', 'publisher': 'Example', 'harness_engineering': True, 'published_after': '2026-01-01', 'sort': 'score_recent'})
    params = cat.calls[0][1]
    assert 'min_agent_relevance' not in params
    assert params['limit'] == 10 and params['sort'] == 'score_recent' and params['subtopic'] == 'memory'
    assert params['publisher'] == 'Example' and params['harness_engineering'] is True
    assert params['published_after'] == '2026-01-01' and params['tier'] == 'featured'
    assert payload(result)['relaxations'] == ['Text relaxed']
    _, cat = call('find_posts', {'query': 'harness', 'min_agent_relevance': 3})
    assert cat.calls[0][1]['min_agent_relevance'] == 3


@pytest.mark.parametrize('name,args,filter', [('browse_catalog', {'topic': 'fuzzing'}, 'topic'),
    ('find_posts', {'query': 'narrow'}, 'query'), ('browse_catalog', {'offset': 10}, 'offset')])
def test_empty_hint(name, args, filter):
    cat = Catalog(); cat.empty = True
    result, _ = call(name, args, cat)
    assert filter in payload(result)['hint']
    assert 'does not mean' in payload(result)['message']


def test_developer_default_sort_counts_paging_and_repo_links():
    result, cat = call('list_developers')
    assert cat.calls[0][1]['sort'] == 'agent'
    row = payload(result)['results'][0]
    assert row['agent_work_count'] == 8 and row['catalog_url'] == SITE_URL + '/developers/9'
    assert payload(result)['total'] == 53
    result, _ = call('get_developer', {'github_id': 9, 'limit': 2, 'offset': 3})
    assert payload(result)['total'] == 40
    assert payload(result)['repositories'][0]['catalog_url'] == SITE_URL + '/repos/org/repo3'
    assert len(payload(result)['repositories']) == 2


@pytest.mark.parametrize('tool', ['list_organizations', 'list_conferences', 'list_frameworks'])
def test_whole_tables_are_paged_and_text_capped(tool):
    result, _ = call(tool, {'offset': 12, 'limit': 3})
    data = payload(result)['data']
    assert data['total'] >= 40 and len(data['results']) == 3
    assert data['results'][0]['id'] == '12'
    if tool == 'list_organizations':
        assert data['results'][0]['catalog_url'] == SITE_URL + '/orgs/org-12'
        assert data['results'][0]['top_trending_paper'] == {'title': 'Harness', 'catalog_url': SITE_URL + '/paper/42'}
        assert 'description' not in data['results'][0]
    else:
        assert len(data['results'][0]['description']) == 601


@pytest.mark.parametrize('name,args', [('search_papers', {'query': 'harness'}), ('list_recent_papers', {}),
    ('list_trending_papers', {}), ('list_papers', {}), ('get_related_papers', {'paper': '42'})])
def test_native_paper_lists_are_enriched_once_and_have_total(name, args):
    result, cat = call(name, args)
    data = payload(result)
    assert data['total'] == 120
    assert data['items'][0]['publisher'] == 'Example'
    assert data['items'][0]['summary'] and data['items'][0]['catalog_url'] == SITE_URL + '/paper/42'
    assert 'data' not in data
    assert sum(path == 'metadata' for path, _ in cat.calls) == 1


def test_grouped_tasks_page_tasks_not_whole_areas():
    result, cat = call('list_tasks', {'group_by_area': True, 'page': 2, 'limit': 3})
    data = payload(result)['data']
    assert data['total'] == 40 and len(data['results']) == 3 and data['results'][0]['id'] == '3'
    assert cat.calls[0][1]['page'] == 1 and cat.calls[0][1]['page_size'] is None


def test_descriptions_vocabulary_defaults_and_instructions():
    async def run():
        server = build_server(Catalog())
        return await server.list_tools(), server.instructions
    tools, instructions = asyncio.run(run())
    by_name = {t.name: t for t in tools}
    assert len(tools) == 26
    assert instructions == INSTRUCTIONS
    for name in ('find_posts', 'browse_catalog', 'search_papers', 'list_developers', 'get_developer',
                 'list_organizations', 'get_organization', 'catalog_filters'):
        assert name in instructions
    for name, axes in {'browse_catalog': VOCAB, 'list_developers': ('topic', 'target', 'contribution'), 'find_posts': ('topic',)}.items():
        for axis in axes:
            if axis == 'year':
                continue
            for value in VOCAB[axis]:
                assert value in by_name[name].description
    for name in ('browse_catalog', 'find_posts'):
        assert all(value in by_name[name].description for value in POST_TYPES)
        assert '0–4' in by_name[name].description and 'publisher' in by_name[name].description
    for tool in tools:
        if tool.name.startswith('list_') or 'limit' in tool.input_schema['properties']:
            assert 'maximum' in tool.description
    assert by_name['find_posts'].input_schema['properties']['min_agent_relevance']['default'] == 3
    assert by_name['list_developers'].input_schema['properties']['sort']['default'] == 'agent'


def test_vocabulary_failure_has_short_retry_and_fallback(monkeypatch):
    attempts = []
    def fail(self, path, params=None):
        attempts.append((self.timeout, path)); raise TransportError('offline')
    monkeypatch.setattr('pwc_mcp.catalog.Client.get', fail)
    monkeypatch.setattr('pwc_mcp.catalog.time.sleep', lambda _: None)
    cat = CatalogClient()
    server = build_server(cat)
    assert attempts == [(1, 'catalog/filters'), (1, 'catalog/filters')]
    tools = asyncio.run(server.list_tools())
    assert 'call catalog_filters' in next(t.description for t in tools if t.name == 'browse_catalog')


def test_browse_default_does_not_filter_general_reporting():
    _, cat = call('browse_catalog')
    assert cat.calls[0][1]['min_agent_relevance'] is None


def test_paper_detail_and_organization_nested_posts_have_links_and_metadata():
    result, _ = call('get_paper_info', {'paper': '42', 'include_resources': True})
    assert not result.is_error
    for field in ('paper', 'discovery'):
        row = payload(result)[field]
        assert row['catalog_url'] == SITE_URL + '/paper/42' and row['publisher'] == 'Example'
        assert row['summary'] and 'post' not in row
    repo = payload(result)['paper']['repositories'][0]
    assert repo['catalog_url'] == SITE_URL + '/repos/org/repo'
    result, _ = call('get_organization', {'organization': 'example'})
    assert payload(result)['data']['catalog_url'] == SITE_URL + '/orgs/example'
    top = payload(result)['data']['top_trending_paper']
    assert top['agent_relevance'] == 4
    assert not ({'paper_id', 'reference', 'tldr', 'date_published'} & top.keys())


def test_lineage_paginates_and_enriches_every_returned_work():
    result, _ = call('get_paper_lineage', {'paper': '42', 'limit': 2, 'offset': 3})
    data = payload(result)
    assert data['total'] == 40 and data['predecessors_total'] == 40
    assert len(data['predecessors']) == 2 and data['predecessors'][0]['id'] == '4'
    assert all(item['summary'] and item['catalog_url'] for item in data['predecessors'])
    assert 'data' not in data


def test_post_types_stay_aligned_with_backend_importer():
    import runpy
    from pathlib import Path
    model = runpy.run_path(str(Path(__file__).parents[1] / 'backend/models/catalog_posts.py'))
    assert set(POST_TYPES) == model['POST_TYPES']


def test_schema_endpoint_matches_client_descriptions():
    from pwc_mcp.app import create_app
    from starlette.testclient import TestClient
    with TestClient(create_app(Catalog(), allowed_hosts=['testserver'])) as client:
        data = client.get('/docs').json()
    tool = next(t for t in data['tools'] if t['name'] == 'find_posts')
    assert 'fuzzing' in tool['description'] and 'maximum 10' in tool['description']


@pytest.mark.parametrize('args', [{'group_by_area': True, 'limit': 26}, {'group_by_area': True, 'page': 0}])
def test_grouped_task_bounds_are_checked_before_normalizing_cli_paging(args):
    result, cat = call('list_tasks', args)
    assert result.is_error and not cat.calls


def test_optional_sort_accepts_single_array_string():
    result, cat = call('list_organizations', {'sort': '["papers"]'})
    assert not result.is_error and cat.calls[0][1]['sort'] == 'papers'


def test_bare_feed_retains_received_collection_count_semantics():
    class BareCatalog(Catalog):
        def query(self, command, options):
            return [NATIVE]
    result, _ = call('list_recent_papers', catalog=BareCatalog())
    data = payload(result)
    assert data['total'] == 1 and data['total_scope'] == 'received_items'
    assert data['data'][0]['publisher'] == 'Example' and 'items' not in data


@pytest.mark.parametrize('name,args', [('find_posts', {}), ('browse_catalog', {}), ('search_papers', {'query': 'harness'}),
    ('list_recent_papers', {}), ('get_related_papers', {'paper': '42'})])
def test_work_rows_have_one_id_summary_date_and_no_internal_fields(name, args):
    cat = Catalog()
    cat.rows[0].update(curated_pin=2, has_text=True, artifact_url=None, display_order=None)
    result, _ = call(name, args, cat)
    data = payload(result)
    row = data.get('results', data.get('items'))[0]
    assert row['id'] == '42' and row['published'] == '2026-11-01'
    assert row['summary'] and row['source_url'] == POST['source_url']
    assert not ({'paper_id', 'reference', 'arxiv_id', 'tldr', 'date_published', 'post',
                 'curated_pin', 'artifact_url', 'display_order'} & row.keys())
    assert all(value is not None for value in row.values())


def test_find_posts_skips_metadata_and_keeps_search_publisher():
    cat = Catalog()
    cat.rows[0]['publisher'] = 'Search publisher'
    result, _ = call('find_posts', catalog=cat)
    assert payload(result)['results'][0]['publisher'] == 'Search publisher'
    assert [path for path, _ in cat.calls] == ['posts']
    assert not ({'facets', 'artifact_url', 'has_text', 'arxiv_id'} & payload(result)['results'][0].keys())
    assert payload(result)['results'][0]['kind'] == 'post'


def test_nested_list_works_are_compact():
    result, _ = call('get_paper_lineage', {'paper': '42', 'limit': 2})
    for row in payload(result)['predecessors']:
        assert row['id'] and row['published'] and row['summary']
        assert not ({'paper_id', 'reference', 'tldr', 'date_published'} & row.keys())
        assert all(value is not None for value in row.values())


@pytest.mark.parametrize('name,args,path', [
    ('browse_catalog', {}, ('results', 0)),
    ('search_papers', {'query': 'harness'}, ('items', 0)),
    ('list_recent_papers', {}, ('items', 0)),
    ('list_trending_papers', {}, ('items', 0)),
    ('list_papers', {}, ('items', 0)),
    ('get_related_papers', {'paper': '42'}, ('items', 0)),
    ('get_paper_lineage', {'paper': '42', 'limit': 2}, ('predecessors', 0)),
    ('get_organization', {'organization': 'example'}, ('data', 'top_trending_paper')),
])
@pytest.mark.parametrize('has_text', [False, True])
def test_catalog_work_fields_survive_inline_and_metadata_projection(name, args, path, has_text):
    work = {'paper_id': '42', 'reference': '2610.12345', 'title': 'Harness',
            'date_published': '2026-11-01', 'source_url': 'https://arxiv.org/abs/2610.12345',
            'facets': {'topic': ['fuzzing'], 'target': ['binaries'], 'contribution': ['system'],
                       'kind': ['paper'], 'year': ['2026']},
            'kind': 'paper', 'artifact_url': 'https://github.com/org/repo', 'has_text': has_text,
            'post': None, 'curated_pin': 3, 'display_order': 7}
    class WorkCatalog(Catalog):
        def __init__(self):
            super().__init__()
            self.rows = [deepcopy(work)]

        def discovery(self, endpoint, params=None):
            if endpoint == 'metadata':
                self.calls.append((endpoint, params))
                return {'results': [{**deepcopy(work), 'paper_id': ref}
                                    for ref in params['references'].split(',')]}
            return super().discovery(endpoint, params)
    result, cat = call(name, args, WorkCatalog())
    row = payload(result)
    for key in path:
        row = row[key]
    assert row['id'].isdigit() and row['arxiv_id'] == '2610.12345'
    assert row['facets'] == work['facets'] and row['artifact_url'] == work['artifact_url']
    assert row['has_text'] is has_text and row['published'] == '2026-11-01'
    assert not ({'kind', 'reference', 'paper_id', 'date_published', 'tldr', 'post', 'curated_pin', 'display_order'} & row.keys())
    assert all(value is not None for value in row.values())
    assert any(endpoint == 'metadata' for endpoint, _ in cat.calls) is (name != 'browse_catalog')


@pytest.mark.parametrize('fields,expected', [
    ({'arxiv_id': '2610.12345v2', 'reference': '42'}, '2610.12345v2'),
    ({'reference': 'cs/0501001'}, 'cs/0501001'),
    ({'reference': 'math.OC/0501001'}, 'math.OC/0501001'),
    ({'arxiv_id': None, 'reference': '42'}, None),
])
def test_arxiv_identifier_preserved_or_recovered_only_when_available(fields, expected):
    cat = Catalog()
    cat.rows[0].update(fields)
    result, _ = call('browse_catalog', catalog=cat)
    row = payload(result)['results'][0]
    assert row['id'] == '42' and row.get('arxiv_id') == expected
    if expected is None:
        assert 'arxiv_id' not in row


def test_list_tools_order_description_polish_and_no_accumulation():
    async def run():
        server = build_server(Catalog())
        first, second = await server.list_tools(), await server.list_tools()
        assert first == second
        assert [t.name for t in first[:10]] == list(TOOL_ORDER)
        assert all(t.output_schema is None for t in first)
        assert all('  ' not in t.description for t in first)
        descriptions = {t.name: t.description for t in first}
        assert 'year: one four-digit year, 2005–2026' in descriptions['browse_catalog']
        assert '2007, 2008' not in descriptions['browse_catalog']
        assert 'Prefer find_posts' not in descriptions['find_posts']
        assert 'Trail of Bits' in descriptions['find_posts'] and 'list_organizations' in descriptions['find_posts']
        assert 'inherited from the base server and sparse' in server.instructions
        for name in ('find_posts', 'browse_catalog', 'search_papers', 'list_recent_papers', 'get_related_papers'):
            assert 'id (pass to get_paper_info/read_paper)' in descriptions[name] and 'published' in descriptions[name]
    asyncio.run(run())


@pytest.mark.parametrize('warm', [False, True])
def test_tool_calls_do_not_rebuild_descriptions(monkeypatch, warm):
    async def run():
        server = build_server(Catalog())
        if warm:
            await server.list_tools()
        async def forbidden():
            pytest.fail('call_tool rebuilt the described tool list')
        monkeypatch.setattr(server, 'list_tools', forbidden)
        for _ in range(2):
            result = await server.call_tool('list_developers', {'sort': '["agent"]'})
            assert payload(result)['results'][0]['agent_work_count'] == 8
    asyncio.run(run())


@pytest.mark.parametrize('name,args,message', [
    ('browse_catalog', {'limit': 100}, 'limit accepts 1–25'),
    ('browse_catalog', {'min_agent_relevance': 7}, 'min_agent_relevance accepts 0–4'),
    ('find_posts', {'limit': 100}, 'limit accepts 1–10'),
    ('list_developers', {'offset': -1}, 'offset accepts 0–2500'),
    ('get_developer', {'github_id': 0}, 'github_id accepts 1–9223372036854775807'),
    ('list_organizations', {'limit': 0}, 'limit accepts 1–25'),
    ('find_posts', {'query': 'x'*201}, 'query accepts at most 200 characters'),
])
def test_profile_range_errors_are_short_and_actionable(name, args, message):
    result, cat = call(name, args)
    assert result.is_error and not cat.calls
    text = result.content[0].text
    assert message in text and 'pydantic' not in text and 'validation error' not in text


class UnavailableMetadata(Catalog):
    def discovery(self, path, params=None):
        if path == 'metadata':
            self.calls.append((path, params))
            raise TransportError('private connection details')
        return super().discovery(path, params)


@pytest.mark.parametrize('name,args', [('search_papers', {'query': 'harness'}), ('get_paper_info', {'paper': '42'}),
                                      ('get_organization', {'organization': 'example'})])
def test_metadata_outage_returns_evidence_and_explicit_flag(name, args):
    result, _ = call(name, args, UnavailableMetadata())
    assert not result.is_error
    data = payload(result)
    assert data['metadata_status'] == 'unavailable'
    assert 'Post fields may be missing' in data['metadata_note']
    assert 'Harness' in result.content[0].text and 'private connection' not in result.content[0].text
    if name == 'get_paper_info':
        assert data['discovery']['publisher'] == 'Example' and data['discovery']['summary']


def test_inline_browse_reviews_survive_metadata_outage_and_use_curated_publisher():
    cat = UnavailableMetadata()
    cat.rows[0]['publisher'] = 'Amazon'
    cat.rows[0]['post']['curated_company'] = '  AWS Security  '
    result, _ = call('browse_catalog', catalog=cat)
    data = payload(result)
    assert not result.is_error and 'metadata_status' not in data
    assert data['results'][0]['publisher'] == 'AWS Security'
    assert data['results'][0]['summary'] and data['results'][0]['agent_relevance'] == 4
    assert [path for path, _ in cat.calls] == ['papers']


def test_curated_publisher_and_numeric_id_are_consistent_across_post_tools():
    class CuratedCatalog(Catalog):
        def __init__(self):
            super().__init__()
            self.rows[0].update(publisher='Amazon', reference='2610.12345')
            self.rows[0]['post']['curated_company'] = 'AWS Security'

        def discovery(self, path, params=None):
            data = super().discovery(path, params)
            if path in {'posts', 'metadata'}:
                for row in data['results']:
                    row['publisher'] = 'AWS Security'
            return data
    for name, args in [('find_posts', {}), ('browse_catalog', {}), ('search_papers', {'query': 'harness'})]:
        result, _ = call(name, args, CuratedCatalog())
        data = payload(result)
        row = data.get('results', data.get('items'))[0]
        assert row['publisher'] == 'AWS Security' and row['id'] == '42'
        assert row['catalog_url'] == SITE_URL + '/paper/42' and 'reference' not in row


class SizedCatalog(Catalog):
    """Filled pages with maximum-length summaries and all requested organization fields."""
    def discovery(self, path, params=None):
        if path in {'posts', 'papers'}:
            count = params.get('limit', 10)
            self.rows = [{**deepcopy(POST), 'paper_id': str(42+i), 'reference': str(42+i)} for i in range(count)]
        return super().discovery(path, params)

    def query(self, command, options):
        data = super().query(command, options)
        if command == ('organization', 'list'):
            for i, row in enumerate(data['results']):
                row.update(website_url=f'https://org{i}.test', github_url=f'https://github.com/org{i}',
                           paper_count=2, post_count=10, agent_post_count=3, repository_count=4,
                           owned_repository_count=5, catalog_stars=600, curated_pin=3, display_order=7,
                           hf_slug='private-ui-slug', trending_rank=None)
        return data


def sample_payload_sizes():
    from pwc_mcp.app import create_app
    from starlette.testclient import TestClient
    measured = {}
    headers = {'Accept': 'application/json, text/event-stream', 'MCP-Protocol-Version': '2025-11-25'}
    with TestClient(create_app(SizedCatalog(), allowed_hosts=['testserver'])) as client:
        for name, args in [('find_posts', {}), ('browse_catalog', {'limit': 25}), ('list_organizations', {'limit': 25})]:
            response = client.post('/mcp', headers=headers, json={
                'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': name, 'arguments': args}})
            assert response.status_code == 200
            result = response.json()['result']
            assert 'structuredContent' not in result and result.get('isError', False) is False
            assert len(result['content']) == 1
            text = result['content'][0]['text']
            measured[name] = {'text_bytes': len(text.encode()), 'wire_bytes': len(response.content)}
    return measured


def test_http_results_send_data_once_and_organizations_stay_small():
    measured = sample_payload_sizes()
    # All requested fields populated: absolute production URLs put 25 rows near 10 KB.
    assert measured['list_organizations']['text_bytes'] < 11000
    for sizes in measured.values():
        assert sizes['wire_bytes'] < sizes['text_bytes'] * 1.5


def test_organization_list_projection_and_no_metadata_lookup():
    result, cat = call('list_organizations', {'limit': 25}, SizedCatalog())
    rows = payload(result)['data']['results']
    assert len(rows) == 25
    expected = {'id', 'name', 'slug', 'website_url', 'github_url', 'paper_count', 'post_count', 'agent_post_count',
                'repository_count', 'owned_repository_count', 'catalog_stars', 'catalog_url', 'top_trending_paper'}
    assert set(rows[0]) == expected
    assert set(rows[0]['top_trending_paper']) == {'title', 'catalog_url'}
    assert all(value is not None for row in rows for value in row.values())
    assert not any(path == 'metadata' for path, _ in cat.calls)


def test_catalog_filters_are_text_only_without_changing_vocabulary_shape():
    result, _ = call('catalog_filters')
    assert payload(result) == {key: {value: value for value in values} for key, values in VOCAB.items()}
