import asyncio
import json
from contextlib import aclosing
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from backend.assistant_cli import main
from backend.assistant_config import AssistantSettings, get_assistant_settings
from backend.models.assistant import AssistantTurnRequest
from backend.models.database.assistant import AssistantConversation, AssistantMessage
from backend.routers import assistant
from backend.services import assistant_followups as phase, assistant_loop
from backend.services.assistant_context import paired_messages
from backend.services.assistant_loop import Turn, TurnLimits
from backend.services.assistant_mcp import CatalogMcp, ToolResult
from backend.services.assistant_admission import VisitorLimitReached
from backend.tests.assistant.test_loop import FakeServices, chunk, text_chunk, tool_chunk
from backend.tests.assistant.test_traces import fake_services

QUESTION = 'How does Example Labs verify agent-generated patches?'
SUPPORT = 'The search found three engineering posts explaining patch verification.'


def submission(items=None):
    return tool_chunk(name='submit_follow_ups', arguments=json.dumps({'follow_ups':
        [{'question': QUESTION, 'support': SUPPORT}] if items is None else items}))


def tool_names(request):
    return {t['function']['name'] for t in request.get('tools', [])}


@pytest.mark.parametrize('finalizer', [False, True])
def test_same_context_phase_starts_after_answer_saved_on_both_paths(finalizer):
    services = FakeServices([[tool_chunk()], [text_chunk('Complete answer')], [tool_chunk()], [submission()]])
    saved = []
    async def checkpoint():
        assert len(services.model_requests) == 2
        saved.append(True)
    original = services.model
    def model(request):
        if len(services.model_requests) == 2:
            assert saved
        return original(request)
    services.model = model
    turn, events = asyncio.run(services.run(TurnLimits(tool_calls=1) if finalizer else TurnLimits(),
                                           follow_ups_enabled=True, on_answer=checkpoint))
    assert turn.text == 'Complete answer' and turn.status == ('limit_reached' if finalizer else 'done')
    assert turn.follow_ups == [QUESTION]
    assert [e['type'] for e in events][-3:] == ['text_delta', 'answer_complete', 'done']
    context = services.model_requests[2]['messages']
    assert [m['role'] for m in context] == ['system', 'user', 'assistant', 'tool', 'assistant', 'system']
    assert context[2]['tool_calls'][0]['function'] == {'name': 'search_papers', 'arguments': '{"query":"security"}'}
    assert context[-2]['content'] == turn.text and context[-1]['content'] == phase.INSTRUCTION
    assert tool_names(services.model_requests[2]) == phase.SEARCH_TOOLS | {'submit_follow_ups'}
    assert all(s['phase'] == 'follow_ups' for s in turn.steps[3:])
    assert turn.steps[-1]['decisions'][0] == {'question': QUESTION, 'support': SUPPORT, 'kept': True, 'reason': 'kept'}


def test_research_requests_are_unchanged_and_disabled_phase_makes_no_call():
    replies = [[tool_chunk()], [text_chunk('Answer')]]
    off, on = FakeServices(replies), FakeServices([*replies, [tool_chunk()], [submission()]])
    before, _ = asyncio.run(off.run(follow_ups_enabled=False))
    after, _ = asyncio.run(on.run(follow_ups_enabled=True))
    assert off.model_requests == on.model_requests[:2]
    assert before.text == after.text and before.status == after.status == 'done'
    assert before.follow_ups == [] and AssistantSettings().follow_ups_enabled is True


@pytest.mark.parametrize('bad', [[text_chunk('Here are some ideas')], [tool_chunk(name='submit_follow_ups', arguments='not JSON')],
    [tool_chunk(name='submit_follow_ups', arguments=json.dumps({'follow_ups': [{'question': '', 'support': 'Evidence'}]}))],
    [tool_chunk(name='submit_follow_ups', arguments=json.dumps({'follow_ups': [{'question': 'x'*121, 'support': 'Evidence'}]}))],
    [tool_chunk(name='submit_follow_ups', arguments=json.dumps({'follow_ups': [{'question': QUESTION, 'support': SUPPORT}]*4}))]])
def test_invalid_submission_or_plain_text_retries_with_submit_only(bad):
    services = FakeServices([[text_chunk('Answer')], [tool_chunk()], bad, [submission()]])
    turn, events = asyncio.run(services.run(follow_ups_enabled=True))
    assert turn.follow_ups == [QUESTION] and turn.status == 'done'
    assert tool_names(services.model_requests[-1]) == {'submit_follow_ups'}
    assert 'must call submit_follow_ups' in json.dumps(services.model_requests[-1]['messages'])
    assert [e['text'] for e in events if e['type'] == 'text_delta'] == ['Answer']
    assert paired_messages(services.model_requests[-1]['messages']) == services.model_requests[-1]['messages']


def test_four_pass_limit_includes_the_submit_only_last_pass():
    services = FakeServices([[text_chunk('Answer')]] + [[text_chunk('No tool call')]] * 4)
    turn, _ = asyncio.run(services.run(follow_ups_enabled=True))
    assert len(services.model_requests) == 5 and turn.follow_ups == [] and turn.status == 'done'
    assert all(tool_names(r) == {'submit_follow_ups'} for r in services.model_requests[2:])
    assert services.model_requests[-1]['messages'][-1]['content'] == phase.SUBMIT_INSTRUCTION


def test_six_search_limit_and_final_submission_gate():
    services = FakeServices([[text_chunk('Answer')], [tool_chunk(i, arguments=json.dumps({'query': str(i)})) for i in range(8)], [submission()]])
    turn, _ = asyncio.run(services.run(follow_ups_enabled=True))
    assert len(services.tool_requests) == 6 and turn.follow_ups == [QUESTION]
    assert tool_names(services.model_requests[-1]) == {'submit_follow_ups'}
    assert services.model_requests[-1]['messages'][-1]['content'] == phase.SUBMIT_INSTRUCTION
    assert paired_messages(services.model_requests[-1]['messages']) == services.model_requests[-1]['messages']


@pytest.mark.parametrize('searched', [False, True])
def test_only_search_presence_and_near_exact_duplicates_filter_submissions(searched):
    items = [{'question': 'Find security papers!', 'support': SUPPORT}, {'question': QUESTION, 'support': SUPPORT},
             {'question': QUESTION.lower()+'!', 'support': SUPPORT}]
    services = FakeServices([[text_chunk('Answer')], *([[tool_chunk()]] if searched else []), [submission(items)]])
    turn, _ = asyncio.run(services.run(follow_ups_enabled=True))
    assert turn.follow_ups == ([QUESTION] if searched else [])
    reasons = [d['reason'] for d in turn.steps[-1]['decisions']]
    assert reasons == (['duplicate_question', 'kept', 'duplicate_candidate'] if searched else ['no_successful_search']*3)


def test_zero_result_success_is_left_to_model_judgment_but_errors_do_not_count(monkeypatch):
    async def call(self, name, arguments):
        return ToolResult('{"results":[]}', 14, False, failed)
    monkeypatch.setattr(CatalogMcp, 'call', call)
    for failed in (False, True):
        services = FakeServices([[text_chunk('Answer')], [tool_chunk()], [submission()]])
        turn, _ = asyncio.run(services.run(follow_ups_enabled=True))
        assert turn.follow_ups == ([] if failed else [QUESTION])


def test_phase_timeout_reserves_last_submit_pass_and_keeps_answer(monkeypatch):
    original = assistant_loop.model_pass
    async def slow(*args, **kwargs):
        if kwargs.get('options', {}).get('reasoning_effort') == 'low':
            await asyncio.Event().wait()
        async for item in original(*args, **kwargs):
            yield item
    monkeypatch.setattr(assistant_loop, 'model_pass', slow)
    real = phase.research_followups
    async def short(*args, **kwargs):
        return await real(*args, **kwargs, limits=phase.FollowUpLimits(seconds=.10, submit_seconds=.05))
    monkeypatch.setattr(phase, 'research_followups', short)
    services = FakeServices([[text_chunk('Answer')], [submission([])]])
    turn, _ = asyncio.run(services.run(follow_ups_enabled=True))
    assert turn.status == 'done' and turn.text == 'Answer' and turn.follow_ups == []
    assert turn.steps[1]['status'] == 'timeout'
    assert tool_names(services.model_requests[-1]) == {'submit_follow_ups'}


def test_phase_input_budget_uses_reported_usage_and_forces_last_gate(monkeypatch):
    real = phase.research_followups
    async def small(*args, **kwargs):
        return await real(*args, **kwargs, limits=replace(phase.FollowUpLimits(), input_tokens=8000))
    monkeypatch.setattr(phase, 'research_followups', small)
    services = FakeServices([[text_chunk('Answer')], [tool_chunk(), chunk(usage={'prompt_tokens': 6000, 'completion_tokens': 5, 'total_tokens': 6005})], [submission()]])
    turn, _ = asyncio.run(services.run(follow_ups_enabled=True))
    assert turn.status == 'done'
    assert len(services.model_requests) == 3
    assert tool_names(services.model_requests[-1]) == {'submit_follow_ups'}
    assert turn.steps[1]['input_token_charge'] == 6000


def test_sse_persistence_trace_and_phase_cost(client, store, monkeypatch, capsys):
    monkeypatch.setattr(get_assistant_settings(), 'follow_ups_enabled', True)
    def usage(n):
        return chunk(usage={'prompt_tokens': n, 'completion_tokens': 3, 'total_tokens': n+3,
                            'completion_tokens_details': {'reasoning_tokens': 1}})
    fake_services(monkeypatch, [[tool_chunk(), usage(10)], [text_chunk('Answer'), usage(20)], [tool_chunk(), usage(30)], [submission(), usage(40)]])
    response = client.post('/api/v1/assistant/turn', json={'question': 'Question'})
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    assert events[-2] == {'type': 'answer_complete'} and events[-1]['follow_ups'] == [QUESTION]
    run = store.show_run(events[-1]['run_id'])
    assert run['tokens'] == {'input_tokens': 100, 'output_tokens': 12}
    details = client.get('/api/v1/assistant/conversations/'+run['conversation_id']).json()['messages'][-1]
    assert details['follow_ups'] == [QUESTION]
    assert all(t.get('phase') != 'follow_ups' for t in details['tool_steps'])
    assert run['steps'][-1]['submitted'][0]['support'] == SUPPORT
    main(['show', run['id']], store=store)
    assert 'submit_follow_ups' in capsys.readouterr().out


def test_optional_quota_still_disables_provider_without_failing_answer(client, store, monkeypatch):
    monkeypatch.setattr(get_assistant_settings(), 'follow_ups_enabled', True)
    fake_services(monkeypatch, [[text_chunk('Answered')], httpx.Response(429, json={'error': 'weekly usage limit exceeded'})])
    response = client.post('/api/v1/assistant/turn', json={'question': 'Question'})
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    assert events[-1]['status'] == 'done' and events[-1]['follow_ups'] == []
    assert not client.get('/api/v1/assistant/status').json()['available']
    assert store.show_run(events[-1]['run_id'])['steps'][-1]['status'] == 'usage_limit'


@pytest.mark.parametrize('where', ['model', 'search'])
@pytest.mark.parametrize('disconnect', [False, True])
def test_stop_and_disconnect_leave_checkpoint_intact(store, monkeypatch, where, disconnect):
    async def exercise():
        started = asyncio.Event()
        real = assistant_loop.model_pass
        async def pause_model(*args, **kwargs):
            if kwargs.get('options') and where == 'model':
                started.set()
                await asyncio.Event().wait()
            async for item in real(*args, **kwargs):
                yield item
        async def pause_search(*args, **kwargs):
            started.set()
            await asyncio.Event().wait()
        monkeypatch.setattr(assistant_loop, 'model_pass', pause_model)
        monkeypatch.setattr(CatalogMcp, 'call', pause_search)
        fake_services(monkeypatch, [[text_chunk('Saved answer')], [tool_chunk()]])
        saved = store.begin('owner', None, 'Question')
        events = assistant.turn_events(AssistantTurnRequest(question='Question'), AssistantSettings(), saved, store)
        async def receive():
            await started.wait()
            return {'type': 'http.disconnect'}
        async def send(event):
            pass
        async def consume():
            async with aclosing(events):
                async for _ in events:
                    pass
        task = asyncio.create_task(assistant.AssistantStreamResponse(events)(
            {'type': 'http', 'asgi': {'spec_version': '2.4'}}, receive, send) if disconnect else consume())
        await asyncio.wait_for(started.wait(), 2)
        message = store.get_conversation('owner', saved.conversation_id)['messages'][-1]
        assert message['content'] == 'Saved answer' and message['status'] == 'done' and message['follow_ups'] == []
        if not disconnect:
            with pytest.raises(VisitorLimitReached):
                store.begin('owner', saved.conversation_id, 'Too early')
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            await asyncio.wait_for(task, 2)
        run = store.show_run(saved.run_id)
        assert run['status'] == 'done' and run['answer'] == 'Saved answer' and run['follow_ups'] == []
        store.begin('owner', saved.conversation_id, 'Now allowed')
    asyncio.run(exercise())


def test_pair_repair_drops_only_unfinished_tool_calls():
    calls = [{'id': x, 'function': {'name': 'search_papers', 'arguments': '{}'}, 'type': 'function'} for x in ('a','b')]
    messages = [{'role': 'assistant', 'content': None, 'tool_calls': calls}, {'role':'tool','tool_call_id':'a','content':'Result'}]
    repaired = paired_messages(messages)
    assert repaired[0]['tool_calls'] == calls[:1] and repaired[1] == messages[1]
    assert len(messages[0]['tool_calls']) == 2


def test_answer_checkpoint_cannot_revive_expired_or_deleted_conversation(store):
    saved = store.begin('owner', None, 'Question')
    with store.sessions.begin() as db:
        db.get(AssistantConversation, saved.conversation_id).updated_at = datetime.now(UTC) - timedelta(days=100)
    store.save_answer(saved, Turn(text='Late', status='done'))
    with store.sessions.begin() as db:
        assert db.get(AssistantMessage, saved.message_id).content == ''
        db.delete(db.get(AssistantConversation, saved.conversation_id))
    store.save_answer(saved, Turn(text='Deleted', status='done'))
