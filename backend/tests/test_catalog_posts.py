"""Anonymous HTTP search uses the same bounded SQL/relaxations as the assistant."""
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from backend.database.catalog_reads import catalog_sessions
from backend.routers.discovery_catalog import router
from backend.services import catalog_posts, discovery_catalog
from backend.tests.assistant.test_find_posts import ROW, FakeSessions, SequencedSessions


@pytest.fixture
def route(monkeypatch):
    monkeypatch.setattr(discovery_catalog, 'terms', lambda db: {'topic': {'fuzzing': 'Fuzzing'}})
    def client(sessions):
        app = FastAPI()
        app.include_router(router, prefix='/api/v1')
        app.dependency_overrides[catalog_sessions] = lambda: sessions
        return TestClient(app)
    return client


def test_all_filters_are_bound_through_public_route(route):
    db = FakeSessions()
    response = route(db).get('/api/v1/catalog/posts', params={
        'query': "harness' OR true --", 'topic': 'fuzzing', 'subtopic': 'memory',
        'post_type': 'engineering-practice', 'tier': 'featured', 'publisher': "O'Reilly",
        'min_agent_relevance': 0, 'harness_engineering': False, 'published_after': '2026-01-01',
        'sort': 'score_recent', 'limit': 2})
    assert response.status_code == 200
    data = response.json()
    assert data['total'] == 29 and data['results'][0]['summary'] == ROW['post_details']['tldr']
    assert data['results'][0]['catalog_url'] == '/paper/42' and 'post_details' not in data['results'][0]
    sql, params = db.calls[-1]
    assert params['publisher'] == "O'Reilly" and params['harness_engineering'] is False
    assert params['published_after'] == date(2026, 1, 1) and params['limit'] == 2
    assert params['query'] not in sql and params['publisher'] not in sql
    assert db.calls[0][0] == 'SET TRANSACTION READ ONLY'
    assert any('statement_timeout' in sql for sql, _ in db.calls)
    assert 'OFFSET' not in sql and 'LIMIT :limit' in sql


@pytest.mark.parametrize('sort,fragment', [('score', 'score DESC'), ('recent', 'date_published DESC NULLS LAST'),
                                          ('score_recent', 'score_recent DESC')])
def test_route_sort_allowlist(route, sort, fragment):
    db = FakeSessions()
    assert route(db).get('/api/v1/catalog/posts', params={'sort': sort}).status_code == 200
    assert 'ORDER BY ' + fragment in db.calls[-1][0]


@pytest.mark.parametrize('explicit,attempts', [(False, [1, 2, 9]), (True, [1, 9])])
def test_route_sparse_relaxations_and_explicit_relevance(route, explicit, attempts):
    db = SequencedSessions(attempts)
    params = {'query': 'agent harness'}
    if explicit:
        params['min_agent_relevance'] = 3
    data = route(db).get('/api/v1/catalog/posts', params=params).json()
    assert data['sort'] == 'text_rank_then_score' and data['match_mode'] == 'any_word'
    assert len(data['relaxations']) == len(attempts) - 1
    if explicit:
        assert all('>= :min_agent_relevance' in sql for sql, _ in db.searches)
    else:
        assert '>= :min_agent_relevance' not in db.searches[-1][0]


@pytest.mark.parametrize('params', [{'query': 'x'*201}, {'limit': 11}, {'limit': 0},
    {'min_agent_relevance': -1}, {'min_agent_relevance': 5}, {'sort': 'invented'},
    {'tier': 'gold'}, {'published_after': 'yesterday'}, {'publisher': 'x'*161}])
def test_request_bounds_before_search(route, params):
    db = FakeSessions()
    assert route(db).get('/api/v1/catalog/posts', params=params).status_code == 422
    assert not db.calls


@pytest.mark.parametrize('field,value,valid', [('topic', 'bogus', 'fuzzing'),
    ('post_type', 'blog', 'engineering-practice')])
def test_unknown_vocabulary_is_helpful_and_does_not_search(route, field, value, valid):
    db = FakeSessions()
    response = route(db).get('/api/v1/catalog/posts', params={field: value})
    assert response.status_code == 422
    detail = response.json()['detail']
    assert detail['parameter'] == field and valid in detail['valid_values']
    assert not any('FROM matched' in sql for sql, _ in db.calls)


def test_empty_result_is_not_missing_coverage(route):
    data = route(FakeSessions([])).get('/api/v1/catalog/posts', params={'publisher': 'Narrow'}).json()
    assert data['total'] == 0 and data['results'] == []
    assert 'publisher' in data['hint'] and 'does not establish' in data['message']


@pytest.mark.parametrize('error', [SQLAlchemyError('SELECT secret connection password'), TimeoutError('secret')])
def test_failure_is_safe_503_not_empty_search(route, error):
    response = route(FakeSessions(error=error)).get('/api/v1/catalog/posts')
    assert response.status_code == 503
    assert 'temporarily unavailable' in response.text
    assert 'secret' not in response.text and 'SELECT' not in response.text and 'total' not in response.json()


def test_query_attempts_share_deadline(route, monkeypatch):
    monkeypatch.setattr(catalog_posts, 'QUERY_SECONDS', 0)
    response = route(FakeSessions()).get('/api/v1/catalog/posts')
    assert response.status_code == 503 and 'not a zero-match' in response.text


def test_metadata_route_is_bounded_and_has_no_raw_review(route):
    rows = [{**ROW, 'paper_id': '42', 'reference': '42', 'facets': {'kind': ['post']},
             'post': ROW['post_details'], 'publisher_organization': 'Example'}]
    db = FakeSessions(rows)
    response = route(db).get('/api/v1/catalog/metadata', params={'references': '42,1706.03762'})
    assert response.status_code == 200
    row = response.json()['results'][0]
    assert row['summary'] == ROW['post_details']['tldr'] and row['agent_relevance'] == 4
    assert 'post' not in row
    sql, params = db.calls[-1]
    assert params == {'refs': ['42', '1706.03762']} and 'LIMIT 25' in sql
    assert '42' not in sql
    for value in (','.join(str(i) for i in range(1,27)), "1; SELECT secret", '-1', '1,'):
        assert route(db).get('/api/v1/catalog/metadata', params={'references': value}).status_code == 422


def test_post_vocabulary_has_unchanged_importer_types(route):
    from backend.models.catalog_posts import POST_TYPES
    response = route(FakeSessions()).get('/api/v1/catalog/post-types')
    assert response.json() == {'post_type': sorted(POST_TYPES)}


@pytest.mark.parametrize('curated,expected', [('  AWS Security  ', 'AWS Security'), (' ', 'Amazon'), (None, 'Amazon')])
def test_mcp_publisher_rule_does_not_change_site_browse_or_detail(curated, expected):
    row = {'paper_id': '42', 'reference': '42', 'title': 'A post', 'date_published': date(2026, 11, 1),
           'source_url': 'https://aws.amazon.com/security/post', 'facets': {'kind': ['post']},
           'publisher_organization': 'Amazon', 'post': {'curated_company': curated, 'tldr': 'Summary'}}
    # Both existing site routes use this unchanged projection.
    site = discovery_catalog._with_publisher(row)
    assert site['publisher'] == 'Amazon' and site['post']['curated_company'] == curated
    mcp = discovery_catalog.compact_metadata(['42'], FakeSessions([row]))['results'][0]
    assert mcp['publisher'] == expected and 'post' not in mcp
    # Search displays the resolved publisher selected/filtered by the shared SQL.
    from backend.services.catalog_posts import post_item, search_statement
    assert post_item({**ROW, 'publisher': expected})['publisher'] == expected
    sql, params = search_statement({'publisher': expected})
    assert params['publisher'] == expected and 'lower(publisher) = lower(:publisher)' in str(sql)
    assert str(sql).index("post_details ->> 'curated_company'") < str(sql).index('btrim(organization)')
