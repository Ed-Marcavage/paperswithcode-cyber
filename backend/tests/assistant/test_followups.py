import asyncio
import json
import time
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError, OperationalError

from backend.assistant_cli import main
from backend.models.assistant_tools import FollowUpPostCheck, SuggestFollowUpsArguments
from backend.services import assistant_followups as followups
from backend.services.assistant_loop import Turn, TurnLimits
from backend.services.assistant_mcp import ToolResult
from backend.services.assistant_posts import search_statement
from backend.services.paper_retrieval_service import PaperRetrievalService
from backend.tests.assistant.test_find_posts import FakeSessions
from backend.tests.assistant.test_loop import FakeServices, text_chunk, tool_chunk
from backend.tests.assistant.test_traces import fake_services

QUESTION = 'How does Example Labs verify agent-generated patches?'
CHECK = {'publisher': 'Example Labs'}


def state(question='Which agent harness designs are useful?'):
    result = followups.FollowUpState(question)
    result.observe('find_posts', ToolResult(json.dumps({'results': [{'id': 42, 'title': 'Harness', 'catalog_url': '/paper/42'}]}), 1, False))
    return result


def suggest(service, candidates):
    return asyncio.run(service.suggest({'candidates': candidates}))


@pytest.mark.parametrize('total,new,reason', [(3, 2, 'kept'), (2, 2, 'too_few_matches'), (8, 1, 'not_enough_new'), (8, 0, 'not_enough_new')])
def test_match_and_novelty_thresholds(monkeypatch, total, new, reason):
    def counts(check, seen, sessions, deadline):
        assert check.publisher == 'Example Labs' and check.min_agent_relevance == 3
        assert seen.ids == {'42'} and deadline > time.monotonic()
        return {'match_count': total, 'new_match_count': new}
    monkeypatch.setattr(followups, 'read_counts', counts)
    result = suggest(state(), [{'question': QUESTION, 'check': CHECK}])
    assert result['candidates'][0]['reason'] == reason
    assert result['candidates'][0]['match_count'] == total
    assert result['follow_ups'] == ([QUESTION] if reason == 'kept' else [])


def test_duplicates_generic_and_three_question_cap(monkeypatch):
    monkeypatch.setattr(followups, 'read_counts', lambda *args: {'match_count': 8, 'new_match_count': 4})
    service = state(QUESTION)
    result = suggest(service, [
        {'question': QUESTION.upper() + '!', 'check': CHECK},
        {'question': 'What should I read next?', 'check': CHECK},
        {'question': 'Which fuzzing benchmarks released code?', 'check': 'fuzzing'},
        {'question': 'Which fuzzing benchmarks have released code?', 'check': 'fuzzing benchmarks'},
    ])
    assert [candidate['reason'] for candidate in result['candidates']] == ['duplicate_question', 'generic', 'kept', 'duplicate_candidate']
    assert len(result['follow_ups']) == 1
    candidates = [{'question': q, 'check': CHECK} for q in (
        QUESTION, 'Which fuzzing benchmarks released code?',
        'What newer work evaluates sandbox isolation?', 'How do offensive planners manage long-term memory?')]
    result = suggest(state(), candidates)
    assert [c['reason'] for c in result['candidates']] == ['kept', 'kept', 'kept', 'limit']
    assert len(result['follow_ups']) == 3 and result['candidates'][3]['match_count'] == 8


def test_missing_research_no_second_verification_and_no_mcp_calls(monkeypatch):
    monkeypatch.setattr(followups, 'read_counts', lambda *args: pytest.fail('No database check before research'))
    service = followups.FollowUpState('Question')
    result = suggest(service, [{'question': QUESTION, 'check': CHECK}])
    assert result['candidates'][0]['reason'] == 'no_research_evidence'
    second = suggest(service, [{'question': 'Which benchmarks released code?', 'check': 'fuzzing'}])
    assert second['follow_ups'] == [] and second['candidates'] == [] and 'Already checked' in second['note']


def test_deadline_bounds_all_four_checks_and_keeps_completed_ones(monkeypatch):
    calls = []
    def counts(*args):
        calls.append(args)
        if len(calls) == 1:
            return {'match_count': 5, 'new_match_count': 3}
        time.sleep(0.15)
        return {'match_count': 5, 'new_match_count': 3}
    monkeypatch.setattr(followups, 'read_counts', counts)
    monkeypatch.setattr(followups, 'FOLLOW_UP_SECONDS', 0.03)
    began = time.monotonic()
    result = suggest(state(), [{'question': q, 'check': CHECK} for q in (
        QUESTION, 'Which fuzzing benchmarks released code?', 'How do planners retain memory?', 'Which agents triage vulnerabilities?')])
    assert time.monotonic() - began < 0.3
    assert result['follow_ups'] == [QUESTION]
    assert [c['reason'] for c in result['candidates']] == ['kept', 'deadline', 'deadline', 'deadline']
    assert result['candidates'][1]['match_count'] is None
    assert len(calls) == 2


def test_verification_failure_is_sanitized_not_an_empty_search(monkeypatch):
    def failure(*args):
        raise SQLAlchemyError('private database parameters')
    monkeypatch.setattr(followups, 'read_counts', failure)
    result = suggest(state(), [{'question': QUESTION, 'check': CHECK}])
    assert result['candidates'][0]['reason'] == 'verification_unavailable'
    assert result['candidates'][0]['match_count'] is None and 'private' not in json.dumps(result)


@pytest.mark.parametrize('candidates', [
    [{'question': 'x' * 121, 'check': CHECK}], [{'question': QUESTION, 'check': 'x' * 201}],
    [{'question': QUESTION, 'check': {'tier': 'featured'}}], [{'question': QUESTION, 'check': {'min_agent_relevance': 5}}],
    [{'question': QUESTION, 'check': CHECK}] * 5,
])
def test_candidate_contract_is_bounded(candidates):
    with pytest.raises(ValidationError):
        SuggestFollowUpsArguments.model_validate({'candidates': candidates})


def test_seen_id_aliases_nested_shapes_and_truncated_catalog_paths():
    seen = followups.SeenWorks()
    seen.observe(json.dumps({'data': {'results': [{'title': 'Paper', 'id': 42, 'arxiv_id': '2601.12345v2', 'catalog_url': '/paper/2601.12345'}]},
                             'paper': {'title': 'Post', 'id': '43'}, 'discovery': {'paper_id': '43', 'catalog_url': '/paper/43'}}))
    seen.observe('{"catalog_url":"/paper/44","title":"cut')
    assert seen.ids == {'42', '43', '44'} and seen.arxiv == {'2601.12345'}
    statement, params = search_statement({'query': 'agent security'}, seen=seen)
    assert params['seen_ids'] == ['42', '43', '44'] and params['seen_arxiv'] == ['2601.12345']
    assert params['min_agent_relevance'] == 3
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert 'count(DISTINCT id)' in sql and 'new_match_count' in sql
    assert 'plainto_tsquery' in sql and 'tsvector_to_array' not in sql


class CountSessions(FakeSessions):
    def mappings(self):
        return SimpleNamespace(one=lambda: {'match_count': 7, 'new_match_count': 4})


def test_count_checks_reuse_post_query_and_existing_paper_search_at_limit_one(monkeypatch):
    seen = followups.SeenWorks(ids={'42'}, arxiv={'2601.12345'})
    db = CountSessions()
    result = followups.read_counts(FollowUpPostCheck(query='agent patches'), seen, db, time.monotonic() + 1)
    assert result == {'match_count': 7, 'new_match_count': 4}
    assert db.calls[0] == ('SET TRANSACTION READ ONLY', None) and len(db.calls) == 3
    assert 0 < int(db.calls[1][1]['timeout']) <= 1000
    assert 'min_agent_relevance' in db.calls[-1][1]
    seen_calls = []
    monkeypatch.setattr(PaperRetrievalService, '_search_papers_fts', lambda self, query, limit: seen_calls.append((query, limit)) or [object()])
    result = followups.read_counts('fuzzing', seen, db, time.monotonic() + 1)
    assert seen_calls == [('fuzzing', 1)] and result['match_count'] == 7
    assert 'discovery_works' in db.calls[-1][0] and 'coalesce(papers.arxiv_id' in db.calls[-1][0]
    assert 'LIMIT' in db.calls[-1][0] and 'new_match_count' in db.calls[-1][0]
    monkeypatch.setattr(PaperRetrievalService, '_search_papers_fts', lambda *args, **kwargs: [])
    assert followups.read_counts('absent', seen, db, time.monotonic() + 1) == {'match_count': 0, 'new_match_count': 0}


def test_shared_paper_candidates_preserve_existing_keyword_ranking():
    from backend.config import get_settings
    retrieval = PaperRetrievalService(None, settings=get_settings(), summary_factory=lambda rows: rows, paper_resolver=lambda ref: None)
    candidate = retrieval.keyword_candidates('fuzzing')
    compiled = str(candidate.select().compile(dialect=postgresql.dialect()))
    assert 'search_vector @@' in compiled and 'paper_authors' in compiled
    assert 'identity_tier' in compiled and 'papers.is_latest_version' in compiled
    count = followups.paper_count_statement(retrieval, 'fuzzing', followups.SeenWorks())
    sql = str(count.compile(dialect=postgresql.dialect()))
    assert 'count(distinct(papers.id))' in sql and 'discovery_works' in sql


def test_model_tool_done_event_trace_budget_and_once_only(monkeypatch):
    seen_calls = []
    def counts(check, seen, *args):
        seen_calls.append(set(seen.ids))
        return {'match_count': 5, 'new_match_count': 2}
    monkeypatch.setattr(followups, 'read_counts', counts)
    args = json.dumps({'candidates': [{'question': QUESTION, 'check': CHECK}]})
    services = FakeServices([
        [tool_chunk(name='find_posts', arguments='{}')],
        [text_chunk('Checking useful next questions.'), tool_chunk(name='suggest_follow_ups', arguments=args)],
        [text_chunk('The supported answer.')],
    ], sessions=FakeSessions())
    turn, events = asyncio.run(services.run())
    assert turn.follow_ups == [QUESTION] and seen_calls == [{'42'}]
    assert events[-1] == {'type': 'done', 'status': 'done', 'follow_ups': [QUESTION]}
    assert 'tools' not in services.model_requests[-1] and not services.tool_requests
    steps = [s for s in turn.steps if s['kind'] == 'tool']
    assert [s['name'] for s in steps] == ['find_posts', 'suggest_follow_ups']
    assert json.loads(steps[-1]['result'])['candidates'][0]['new_match_count'] == 2
    assert turn.text == 'The supported answer.' and 'Checking' not in turn.text


def test_batched_verification_runs_after_other_research(monkeypatch):
    seen_calls = []
    monkeypatch.setattr(followups, 'read_counts', lambda check, seen, *args: seen_calls.append(set(seen.ids)) or {'match_count': 5, 'new_match_count': 2})
    args = json.dumps({'candidates': [{'question': QUESTION, 'check': CHECK}]})
    services = FakeServices([[tool_chunk(name='suggest_follow_ups', arguments=args), tool_chunk(index=1, name='find_posts', arguments='{}')],
                             [text_chunk('Answer')]], sessions=FakeSessions())
    turn, _ = asyncio.run(services.run(TurnLimits(tool_calls=2)))
    assert seen_calls == [{'42'}] and turn.follow_ups == [QUESTION]
    assert turn.status == 'limit_reached'
    assert len([s for s in turn.steps if s['kind'] == 'tool']) == 2


def test_no_tool_or_finalizer_first_means_no_followups():
    plain = FakeServices([[text_chunk('Answer')]])
    turn, events = asyncio.run(plain.run())
    assert turn.follow_ups == [] and events[-1]['follow_ups'] == []
    limited = FakeServices([[tool_chunk()], [text_chunk('Limited answer')]])
    turn, events = asyncio.run(limited.run(TurnLimits(tool_calls=1)))
    assert turn.follow_ups == [] and events[-1]['follow_ups'] == []


def test_sse_persist_reload_trace_and_next_turn_does_not_imply_topic(client, store, monkeypatch, capsys):
    monkeypatch.setattr(followups, 'read_counts', lambda *args: {'match_count': 5, 'new_match_count': 3})
    args = json.dumps({'candidates': [{'question': QUESTION, 'check': CHECK}]})
    fake_services(monkeypatch, [[tool_chunk()], [tool_chunk(name='suggest_follow_ups', arguments=args)], [text_chunk('Answer')]])
    response = client.post('/api/v1/assistant/turn', json={'question': 'Show useful security agent harnesses'})
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    assert events[-1]['follow_ups'] == [QUESTION]
    details = client.get('/api/v1/assistant/conversations/' + events[-1]['conversation_id']).json()
    assert details['messages'][-1]['follow_ups'] == [QUESTION]
    run = store.show_run(events[-1]['run_id'])
    assert run['follow_ups'] == [QUESTION]
    verification = next(s for s in run['steps'] if s.get('name') == 'suggest_follow_ups')
    assert json.loads(verification['arguments'])['candidates'][0]['question'] == QUESTION
    assert json.loads(verification['result'])['candidates'][0]['kept']
    main(['show', run['id']], store=store)
    assert QUESTION in capsys.readouterr().out
    fake_services(monkeypatch, [[text_chunk('Follow-up answer')]])
    next_response = client.post('/api/v1/assistant/turn', json={'question': QUESTION, 'conversation_id': run['conversation_id']})
    next_events = [json.loads(line[6:]) for line in next_response.text.splitlines() if line.startswith('data: ')]
    assert store.show_run(next_events[-1]['run_id'])['topic'] is None
    details = client.get('/api/v1/assistant/conversations/' + run['conversation_id']).json()
    assert details['messages'][-1]['follow_ups'] == []
    assert details['messages'][1]['follow_ups'] == [QUESTION]


def test_failed_answers_do_not_persist_suggestions_and_state_resets(store):
    saved = store.begin('visitor', None, 'Question')
    store.finish(saved, Turn(status='failed', follow_ups=[QUESTION]))
    assert store.get_conversation('visitor', saved.conversation_id)['messages'][-1]['follow_ups'] == []
    from backend.services.assistant_mcp import CatalogMcp
    mcp = CatalogMcp(None, 'http://catalog.test/mcp')
    mcp.follow_up_state.used = True
    mcp.follow_up_state.questions = [QUESTION]
    mcp.follow_up_state.seen.ids.add('42')
    mcp.begin_turn('Next question')
    assert not mcp.follow_up_state.used and not mcp.follow_up_state.questions and not mcp.follow_up_state.seen.ids


def test_verification_finishes_research_and_empty_candidates_are_valid():
    from backend.services.assistant_mcp import CatalogMcp
    mcp = CatalogMcp(None, 'http://catalog.test/mcp')
    async def run():
        result = await mcp.call('suggest_follow_ups', {'candidates': []})
        assert json.loads(result.text) == {'follow_ups': [], 'candidates': []}
        assert not result.is_error and await mcp.tools() == []
        refused = await mcp.call('find_posts', {})
        assert refused.is_error and 'Research has ended' in refused.text
    asyncio.run(run())


def test_database_statement_deadline_is_recorded_without_error_details(monkeypatch):
    class Cancelled(Exception):
        pgcode = '57014'
    def counts(*args):
        raise OperationalError('private SQL', {}, Cancelled('private error'))
    monkeypatch.setattr(followups, 'read_counts', counts)
    result = suggest(state(), [{'question': QUESTION, 'check': CHECK}])
    assert result['follow_ups'] == [] and result['candidates'][0]['reason'] == 'deadline'
    assert 'private' not in json.dumps(result)
