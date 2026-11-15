import asyncio
import json
from datetime import date

import httpx
import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError

from backend.models.assistant_tools import FindPostsArguments
from backend.services import assistant_posts, trending_posts
from backend.services.assistant_loop import TurnLimits
from backend.services.assistant_mcp import CatalogMcp, MAX_RESULT_BYTES
from backend.services.assistant_tool_budget import bounded_arguments
from backend.tests.assistant.test_loop import FakeServices, text_chunk, tool_chunk
from backend.tests.assistant.test_mcp import FILTERS, response


ROW = {'id': 42, 'title': 'Building a pentest harness', 'publisher': 'Example Labs',
       'date_published': date(2026, 11, 1), 'source_url': 'https://example.test/harness', 'total': 29,
       'post_details': {'post_type': 'engineering-practice', 'tier': 'featured', 'agent_relevance': 4,
                        'agent_harness_engineering': True, 'technical_depth': 4, 'originality': 3,
                        'tldr': 'A scoped, verifiable harness.', 'caveat': 'Vendor measurements.',
                        'subtopics': ['automated-pentesting']}}


class FakeSessions:
    def __init__(self, rows=None, error=None):
        self.rows = [ROW] if rows is None else rows
        self.error = error
        self.calls = []
        self.closed = 0

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed += 1

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params))
        if self.error:
            raise self.error
        return self

    def mappings(self):
        return self.rows


def call_posts(arguments, sessions):
    requests = []
    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        assert body['params']['name'] == 'catalog_filters', 'find_posts must never be sent to MCP'
        return response(request, {'structuredContent': FILTERS})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await CatalogMcp(http, 'http://posts.test/mcp', sessions=sessions).call('find_posts', arguments)
    return asyncio.run(run()), requests


def test_local_tool_returns_requested_fields_and_total_with_existing_sessions():
    db = FakeSessions()
    result, requests = call_posts({'topic': '["penetration-testing"]', 'limit': 100, 'harness_engineering': True}, db)
    data = json.loads(result.text)
    assert data['total'] == 29 and len(data['results']) == 1
    assert data['results'][0] == {'id': 42, 'title': ROW['title'], 'publisher': 'Example Labs',
        'published': '2026-11-01', 'post_type': 'engineering-practice', 'tier': 'featured',
        'agent_relevance': 4, 'harness_engineering': True, 'technical_depth': 4, 'originality': 3,
        'tldr': 'A scoped, verifiable harness.', 'caveat': 'Vendor measurements.',
        'subtopics': ['automated-pentesting'], 'source_url': ROW['source_url'], 'catalog_url': '/paper/42'}
    assert not result.is_error and not result.truncated and result.full_bytes == len(result.text.encode())
    assert len(requests) == 1 and db.closed == 1
    assert db.calls[0] == ('SET TRANSACTION READ ONLY', None)
    assert db.calls[1][1] == {'timeout': '1500'}
    sql, params = db.calls[2]
    assert params['limit'] == 10 and params['min_agent_relevance'] == 3
    assert params['harness_engineering'] is True
    assert json.loads(params['topic']) == {'topic': ['penetration-testing']}
    assert 'count(*) OVER ()' in sql and 'LIMIT :limit' in sql


def test_all_filters_are_bound_and_postgres_statement_compiles(monkeypatch):
    monkeypatch.setattr(trending_posts, 'ANCHOR_DATE', date(2026, 11, 14))
    args = {'query': "title%_' OR TRUE--", 'topic': 'penetration-testing', 'subtopic': 'agent memory',
            'publisher': "O'Reilly", 'post_type': 'engineering-practice', 'tier': 'featured',
            'harness_engineering': False, 'min_agent_relevance': 0,
            'published_after': '2026-01-01', 'sort': 'score_recent', 'limit': 2}
    statement, params = assistant_posts.search_statement(args)
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert all(value not in sql for value in (args['query'], args['publisher'], args['subtopic'], args['topic']))
    assert params['query'] == args['query'] and params['publisher'] == args['publisher']
    assert params['published_after'] == date(2026, 1, 1)
    assert params['anchor'] == date(2026, 11, 14) and params['half_life'] == 7
    assert params['harness_engineering'] is False and params['min_agent_relevance'] == 0
    assert "to_tsvector('english', coalesce(title" in sql and "post_details ->> 'tldr'" in sql
    assert "@@ plainto_tsquery('english'," in sql and 'strpos' not in sql
    assert 'jsonb_array_elements_text' in sql and 'jsonb_each_text' in sql
    assert 'date_published::date >' in sql and 'ORDER BY score_recent DESC' in sql
    assert "post_details ->> 'technical_depth'" in sql and "post_details ->> 'originality'" in sql
    assert 'THEN 1 ELSE 0 END AS score' in sql and 'power(0.5' in sql
    # Numerical reference is the existing Trending implementation. The SQL's
    # JSON operators/ordering still require the reviewer's PostgreSQL check.
    assert trending_posts.post_score(ROW['post_details']) == 8
    assert trending_posts.decayed_score(ROW['post_details'], date(2026, 11, 7), date(2026, 11, 14)) == 4


@pytest.mark.parametrize('sort,order', [('score', 'score DESC'), ('recent', 'date_published DESC NULLS LAST'), ('score_recent', 'score_recent DESC')])
def test_sort_is_an_allowlisted_fragment_with_deterministic_ties(sort, order):
    statement, params = assistant_posts.search_statement({'sort': sort})
    assert f'ORDER BY {order}, date_published DESC NULLS LAST, id DESC LIMIT :limit' in str(statement)
    assert params['min_agent_relevance'] == 3 and 'harness_engineering' not in params


@pytest.mark.parametrize('arguments', [{'min_agent_relevance': -1}, {'min_agent_relevance': 5},
    {'min_agent_relevance': True}, {'harness_engineering': 'true'}, {'sort': 'score; DELETE'},
    {'published_after': 'yesterday'}, {'query': 'x' * 201}, {'unknown': 'field'}])
def test_invalid_arguments_fail_before_database_or_network(arguments):
    db = FakeSessions()
    with pytest.raises(ValueError):
        call_posts(arguments, db)
    assert not db.calls


def test_defaults_are_canonical_for_duplicate_calls_and_schema_explains_preferences():
    from backend.services.assistant_posts import DESCRIPTION
    assert bounded_arguments('find_posts', {}) == bounded_arguments('find_posts', {
        'min_agent_relevance': 3, 'limit': 100, 'sort': 'score'})
    schema = FindPostsArguments.model_json_schema()['properties']
    assert schema['min_agent_relevance']['default'] == 3
    assert schema['limit']['maximum'] == 10
    assert 'ANY question about industry posts' in DESCRIPTION
    assert 'browse_catalog and search_papers' in DESCRIPTION


def test_zero_results_explain_filter_to_loosen_and_invalid_topic_never_hits_database():
    db = FakeSessions([])
    result, requests = call_posts({'query': 'overly narrow'}, db)
    assert not requests and not result.is_error
    data = json.loads(result.text)
    assert data['total'] == 0 and data['results'] == [] and 'query' in data['hint']
    assert 'does not establish' in data['message']
    other = FakeSessions()
    invalid, _ = call_posts({'topic': 'invented'}, other)
    assert invalid.is_error and not other.calls and 'penetration-testing' in invalid.text
    multiple, _ = call_posts({'topic': ['penetration-testing', 'other']}, other)
    assert multiple.is_error and 'one valid slug' in multiple.text and not other.calls


def test_missing_metadata_stays_null_and_large_text_is_bounded():
    row = {**ROW, 'date_published': None, 'post_details': {'tldr': 'x' * 4000}}
    result, _ = call_posts({}, FakeSessions([row]))
    item = json.loads(result.text)['results'][0]
    assert item['agent_relevance'] is None and item['published'] is None and item['caveat'] is None
    assert len(item['tldr']) == 601 and len(result.text.encode()) < MAX_RESULT_BYTES


def test_database_failure_and_timeout_are_safe_nonzero_match_errors(monkeypatch):
    failed, _ = call_posts({}, FakeSessions(error=SQLAlchemyError('private connection detail')))
    assert failed.is_error and 'private' not in failed.text and 'temporarily unavailable' in failed.text
    assert 'total' not in json.loads(failed.text)
    monkeypatch.setattr(assistant_posts, 'QUERY_SECONDS', 0)
    timed_out, _ = call_posts({}, FakeSessions())
    assert timed_out.is_error and 'temporarily unavailable' in timed_out.text


def test_find_posts_obeys_turn_trace_cache_and_tool_budget():
    db = FakeSessions()
    services = FakeServices([
        [tool_chunk(name='find_posts', arguments='{"harness_engineering":true}')],
        [tool_chunk(name='find_posts', arguments='{"harness_engineering":true,"limit":100}')],
        [text_chunk('[Harness](/paper/42) ([source](https://example.test/harness))')],
    ], sessions=db)
    turn, events = asyncio.run(services.run(TurnLimits(tool_calls=2)))
    steps = [step for step in turn.steps if step['kind'] == 'tool']
    assert len(db.calls) == 3 and not services.tool_requests
    assert len(steps) == 2 and steps[1]['cached_from'] == steps[0]['call_id']
    assert steps[0]['name'] == 'find_posts' and '/paper/42' in steps[0]['result']
    assert steps[0]['effective_arguments']['min_agent_relevance'] == 3
    assert steps[0]['full_bytes'] == len(steps[0]['result'].encode())
    assert turn.status == 'limit_reached' and 'tools' not in services.model_requests[-1]
    assert any(event['type'] == 'tool_finished' and event['name'] == 'find_posts' for event in events)
    assert all(s['cumulative_input_tokens'] > 0 for s in turn.steps if s['kind'] == 'model')


class SequencedSessions(FakeSessions):
    def __init__(self, totals):
        super().__init__()
        self.totals = iter(totals)

    def mappings(self):
        total = next(self.totals)
        return [{**ROW, 'total': total}] if total else []

    @property
    def searches(self):
        return [(sql, params) for sql, params in self.calls if 'FROM matched' in sql]


def test_sparse_default_query_relaxes_relevance_then_uses_ranked_any_words():
    db = SequencedSessions([1, 2, 560])
    result, _ = call_posts({'query': 'ARTEX agentic attack frameworks'}, db)
    data = json.loads(result.text)
    assert len(db.searches) == 3
    first, broader, any_word = [sql for sql, _ in db.searches]
    assert '>= :min_agent_relevance' in first
    assert '>= :min_agent_relevance' not in broader and '>= :min_agent_relevance' not in any_word
    assert '@@ plainto_tsquery' in broader
    assert 'ORDER BY ts_rank_cd(' in any_word
    assert 'DESC, score DESC, date_published DESC NULLS LAST, id DESC' in any_word
    assert data['total'] == 560 and data['match_mode'] == 'any_word'
    assert data['sort'] == 'text_rank_then_score'
    assert len(data['relaxations']) == 2
    assert 'default agent relevance' in data['relaxations'][0]
    assert 'all words to any word' in data['relaxations'][1]


def test_relevance_relaxation_keeps_all_words_when_enough_match():
    db = SequencedSessions([0, 10])
    result = assistant_posts.read_posts({'query': 'ARTEX'}, db)
    assert len(db.searches) == 2 and result['total'] == 10
    assert result['match_mode'] == 'all_words' and len(result['relaxations']) == 1


@pytest.mark.parametrize('minimum', [0, 3, 4])
def test_explicit_relevance_is_never_removed(minimum):
    db = SequencedSessions([1, 20])
    result, _ = call_posts({'query': 'ARTEX agentic attack frameworks', 'min_agent_relevance': minimum}, db)
    assert len(db.searches) == 2
    assert all('>= :min_agent_relevance' in sql and params['min_agent_relevance'] == minimum
               for sql, params in db.searches)
    assert len(json.loads(result.text)['relaxations']) == 1


@pytest.mark.parametrize('arguments,total', [({}, 0), ({'query': 'ARTEX'}, 3), ({'query': 'ARTEX', 'limit': 1}, 10)])
def test_no_unnecessary_fallback_for_filters_or_small_requested_limit(arguments, total):
    db = SequencedSessions([total])
    assert assistant_posts.read_posts(arguments, db)['relaxations'] == []
    assert len(db.searches) == 1


def test_relevance_omission_survives_repeated_normalization_and_cache_keys():
    implicit = bounded_arguments('find_posts', {'query': 'ARTEX'})
    explicit = bounded_arguments('find_posts', {'query': 'ARTEX', 'min_agent_relevance': 3})
    assert 'min_agent_relevance' not in implicit and explicit['min_agent_relevance'] == 3
    assert bounded_arguments('find_posts', implicit) == implicit
    assert bounded_arguments('find_posts', explicit) == explicit
    assert implicit != explicit


def test_any_word_sql_quotes_normalized_lexemes_and_binds_every_user_value():
    query = "ARTEX' | !attack:* ; DROP TABLE papers; --"
    statement, params = assistant_posts.search_statement({'query': query}, any_word=True, relax_relevance=True)
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert query not in sql and params['query'] == query
    assert "string_agg(quote_literal(term), ' | ')" in sql
    assert "tsvector_to_array(to_tsvector('english'," in sql
    assert 'ORDER BY ts_rank_cd(' in sql


def test_extra_queries_share_the_original_deadline(monkeypatch):
    db = SequencedSessions([0, 0])
    times = iter([98, 99.75, 100.01])
    monkeypatch.setattr(assistant_posts.time, 'monotonic', lambda: next(times))
    with pytest.raises(TimeoutError):
        assistant_posts.read_posts({'query': 'ARTEX'}, db, deadline=100)
    assert len(db.searches) == 2
    timeouts = [params['timeout'] for sql, params in db.calls if 'set_config' in sql]
    assert timeouts == ['1500', '250']
    assert db.closed == 1
