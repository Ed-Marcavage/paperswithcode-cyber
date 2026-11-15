import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError

from backend.assistant_cli import main
from backend.routers import assistant
from backend.services import assistant_topics as topics
from backend.services.assistant_loop import Turn, TurnLimits
from backend.services.assistant_mcp import ToolResult, MAX_RESULT_BYTES
from backend.tests.assistant.test_find_posts import FakeSessions
from backend.tests.assistant.test_loop import FakeServices, text_chunk, tool_chunk
from backend.tests.assistant.test_traces import fake_services

TOPIC = {'slug': 'penetration-testing', 'label': 'Penetration testing', 'count': 107}


def test_choices_threshold_order_labels_and_count_query():
    rows = [TOPIC, {'slug': 'thin', 'label': 'Thin', 'count': 19},
            {'slug': 'boundary', 'label': 'Boundary label', 'count': 20},
            {'slug': 'first', 'label': 'First label', 'count': 169}]
    assert topics.topic_choices(rows) == [rows[3], TOPIC, rows[2]]
    sql = str(topics.TOPICS_SQL.compile(dialect=postgresql.dialect()))
    assert 'count(DISTINCT w.paper_id)' in sql
    assert "t.axis = 'topic'" in sql and "w.facets -> 'kind' ? 'paper'" in sql
    assert "w.facets -> 'kind' ? 'post'" in sql and '>= %(min_relevance)s' in sql
    assert topics.MIN_TOPIC_WORKS == 20


def test_process_cache_expiry_copy_and_minimum_relevance(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(topics.time, 'monotonic', lambda: now[0])
    db = FakeSessions([TOPIC])
    first = topics.get_topics(db)
    first[0]['label'] = 'Caller mutation'
    assert topics.get_topics(db) == [TOPIC] and len(db.calls) == 3
    assert db.calls[-1][1] == {'min_relevance': topics.MIN_AGENT_RELEVANCE}
    now[0] += topics.TOPICS_CACHE_SECONDS + 1
    assert topics.get_topics(db) == [TOPIC] and len(db.calls) == 6
    assert topics.get_topics(FakeSessions([])) == []  # No cross-database cache.


def test_endpoint_is_public_cached_and_available_during_usage_cooldown(client, store, monkeypatch):
    db = FakeSessions([TOPIC, {'slug': 'small', 'label': 'Small', 'count': 19}])
    monkeypatch.setattr(assistant, 'get_topics', lambda sessions: topics.get_topics(db))
    monkeypatch.setattr(assistant, 'model_client', lambda *args: pytest.fail('No model call'))
    store.record_provider_limit('Usage limit', datetime.now(UTC) + timedelta(hours=1))
    for _ in range(2):
        response = client.get('/api/v1/assistant/topics')
        assert response.json() == {'topics': [TOPIC]}
        assert response.headers['cache-control'] == 'public, max-age=60'
        assert 'set-cookie' not in response.headers
    assert len(db.calls) == 3


def test_endpoint_failure_is_safe_and_not_cached(client, monkeypatch):
    db = FakeSessions(error=SQLAlchemyError('private detail'))
    monkeypatch.setattr(assistant, 'get_topics', lambda sessions: topics.get_topics(db))
    response = client.get('/api/v1/assistant/topics')
    assert response.status_code == 503 and 'private' not in response.text
    db.error = None
    db.rows = [TOPIC]
    assert client.get('/api/v1/assistant/topics').json() == {'topics': [TOPIC]}


def test_unknown_or_thin_topic_is_plain_422_before_admission(client, store, monkeypatch):
    db = FakeSessions([TOPIC, {'slug': 'thin', 'label': 'Thin', 'count': 19}])
    monkeypatch.setattr(assistant, 'resolve_topic', lambda slug, sessions: topics.resolve_topic(slug, db))
    monkeypatch.setattr(store, 'begin', lambda *args, **kwargs: pytest.fail('Admitted invalid topic'))
    for slug in ('invented', 'thin', ''):
        response = client.post('/api/v1/assistant/turn', json={'question': 'What is useful?', 'topic': slug})
        assert response.status_code == 422
        assert response.json() == {'detail': 'Unknown topic. Choose one of the available topics.'}


@pytest.mark.parametrize('name', ['browse_catalog', 'find_posts'])
def test_topic_default_tool_scope_trace_and_finalizer(name):
    db = FakeSessions([])
    services = FakeServices([[tool_chunk(name=name, arguments='{}')], [text_chunk('Answer')]], sessions=db)
    turn, _ = asyncio.run(services.run(TurnLimits(tool_calls=1), topic=TOPIC))
    for request in services.model_requests:
        assert request['messages'][1]['role'] == 'system'
        assert 'Penetration testing' in request['messages'][1]['content']
    step = next(step for step in turn.steps if step['kind'] == 'tool')
    assert step['effective_arguments']['topic'] == TOPIC['slug']
    assert step['default_topic'] == TOPIC['slug']
    assert json.loads(step['result'])['scope'] == {'topic': TOPIC['slug'], 'label': TOPIC['label'], 'defaulted': True}
    assert step['full_bytes'] == len(step['result'].encode())


def test_explicit_empty_topic_overrides_default_and_later_turn_does_not_inherit():
    services = FakeServices([[tool_chunk(name='browse_catalog', arguments='{"topic":""}')], [text_chunk('Answer')]])
    turn, _ = asyncio.run(services.run(topic=TOPIC))
    assert services.tool_requests[0]['arguments']['topic'] == ''
    assert next(s for s in turn.steps if s['kind'] == 'tool')['default_topic'] is None
    unscoped = FakeServices([[tool_chunk(name='browse_catalog', arguments='{}')], [text_chunk('Answer')]])
    asyncio.run(unscoped.run())
    assert 'topic' not in unscoped.tool_requests[0]['arguments']
    assert unscoped.model_requests[0]['messages'][1]['role'] == 'user'


def test_topic_is_stored_on_run_and_visible_in_cli_not_future_history(client, store, monkeypatch, capsys):
    monkeypatch.setattr(assistant, 'resolve_topic', lambda slug, sessions: TOPIC if slug else None)
    services = fake_services(monkeypatch, [[text_chunk('Answer')]])
    response = client.post('/api/v1/assistant/turn', json={'question': 'Harnesses?', 'topic': TOPIC['slug']})
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    run = store.show_run(events[0]['run_id'])
    assert run['topic'] == TOPIC['slug'] and 'Penetration testing' in services.model_requests[0]['messages'][1]['content']
    main(['show', run['id']], store=store)
    assert 'Topic: penetration-testing' in capsys.readouterr().out
    saved = store.begin('other visitor', None, 'Question')
    assert saved.topic is None and store.show_run(saved.run_id)['topic'] is None
    store.finish(saved, Turn(status='done'))


def test_scope_annotation_preserves_bounded_truncated_result_size():
    result = ToolResult('x' * MAX_RESULT_BYTES, 30000, True)
    scoped = topics.scoped_result(result, TOPIC)
    assert scoped.truncated and len(scoped.text.encode()) <= MAX_RESULT_BYTES
    assert scoped.full_bytes > 30000 and 'Topic scope defaulted' in scoped.text
