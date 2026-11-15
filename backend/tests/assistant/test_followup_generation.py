import asyncio
import json
from contextlib import aclosing
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from backend.assistant_config import AssistantSettings, get_assistant_settings
from backend.assistant_cli import main
from backend.models.assistant import AssistantTurnRequest
from backend.models.database.assistant import AssistantConversation, AssistantMessage
from backend.routers import assistant
from backend.services import assistant_followup_generation as generation, assistant_followups, assistant_loop
from backend.services.assistant_admission import VisitorLimitReached
from backend.services.assistant_input_budget import estimate_input_tokens
from backend.services.assistant_loop import Turn, TurnLimits
from backend.services.assistant_mcp import CatalogMcp, AssistantMcpError
from backend.tests.assistant.test_find_posts import FakeSessions
from backend.tests.assistant.test_followups import QUESTION, CHECK
from backend.tests.assistant.test_loop import FakeServices, chunk, text_chunk, tool_chunk
from backend.tests.assistant.test_traces import fake_services

CANDIDATES = json.dumps({'candidates': [{'question': QUESTION, 'check': CHECK}]})


@pytest.fixture
def verified(monkeypatch):
    monkeypatch.setattr(assistant_followups, 'read_counts', lambda *args: {'match_count': 5, 'new_match_count': 3})


@pytest.mark.parametrize('tools', [2, 3, 4])
def test_research_requests_and_done_status_unchanged_with_optional_step(tools, verified):
    research = [[tool_chunk(i, arguments=json.dumps({'query': f'query {i}'})) for i in range(tools)], [text_chunk('Answer')]]
    off = FakeServices(research)
    before, _ = asyncio.run(off.run(follow_ups_enabled=False))
    on = FakeServices([*research, [text_chunk(CANDIDATES)]])
    after, events = asyncio.run(on.run(follow_ups_enabled=True))
    assert before.status == after.status == 'done' and before.text == after.text == 'Answer'
    assert on.model_requests[:-1] == off.model_requests
    assert on.tool_requests == off.tool_requests and len(on.tool_requests) == tools
    assert [step for step in after.steps if step['kind'] == 'follow_ups'][0]['status'] == 'done'
    assert events[-1]['follow_ups'] == [QUESTION]
    assert all('suggest_follow_ups' not in json.dumps(request) for request in off.model_requests)


@pytest.mark.parametrize('finalizer', [False, True])
def test_step_runs_after_stream_and_save_on_both_answer_paths(finalizer, verified):
    checkpoints = []
    services = FakeServices([[tool_chunk(name='find_posts', arguments='{}')], [text_chunk('Complete answer')],
                             [text_chunk(CANDIDATES)]], sessions=FakeSessions())
    async def saved():
        assert len(services.model_requests) == 2
        checkpoints.append('saved')
    original = services.model
    def model(request):
        if len(services.model_requests) == 2:
            assert checkpoints == ['saved']
        return original(request)
    services.model = model
    turn, events = asyncio.run(services.run(TurnLimits(tool_calls=1) if finalizer else TurnLimits(),
                                           follow_ups_enabled=True, on_answer=saved))
    assert turn.status == ('limit_reached' if finalizer else 'done') and turn.answer_complete
    assert turn.follow_ups == [QUESTION] and turn.text == 'Complete answer'
    assert [e['text'] for e in events if e['type'] == 'text_delta'] == ['Complete answer']
    call = services.model_requests[-1]
    assert 'tools' not in call and 'tool_choice' not in call
    assert call['reasoning_effort'] == 'none' and call['max_tokens'] == generation.OUTPUT_TOKENS
    assert call['messages'][0]['content'] == generation.PROMPT
    step = turn.steps[-1]
    assert step['kind'] == 'follow_ups' and step['candidates'][0]['new_match_count'] == 3
    assert step['latency_ms'] >= step['model_latency_ms'] >= 0
    assert len([s for s in turn.steps if s['kind'] == 'tool']) == 1


def test_optional_call_is_outside_research_model_limit():
    services = FakeServices([[text_chunk('Final answer')], [text_chunk('{"candidates":[]}')]])
    turn, _ = asyncio.run(services.run(TurnLimits(model_turns=1), follow_ups_enabled=True))
    assert turn.status == 'limit_reached' and len(services.model_requests) == 2
    assert [s['kind'] for s in turn.steps] == ['model', 'follow_ups']


@pytest.mark.parametrize('invalid', ['not JSON', '```json\n{"candidates":[]}\n```',
    '{"candidates":[],"candidates":[]}', '{"candidates":[],"extra":1}',
    json.dumps({'candidates': [{'question': 'x' * 121, 'check': CHECK}]}),
    json.dumps({'candidates': [{'question': QUESTION, 'check': {'tier': 'featured'}}]}),
    json.dumps({'candidates': [{'question': QUESTION, 'check': CHECK}] * 5})])
def test_invalid_output_does_not_affect_answer(invalid):
    services = FakeServices([[text_chunk('Saved answer')], [text_chunk(invalid)]])
    turn, events = asyncio.run(services.run(follow_ups_enabled=True))
    assert turn.text == 'Saved answer' and turn.status == 'done' and turn.follow_ups == []
    assert turn.steps[-1]['status'] == 'invalid_json'
    assert events[-1] == {'type': 'done', 'status': 'done', 'follow_ups': []}


def test_timeout_is_optional_and_has_no_retry(monkeypatch):
    real = assistant_loop.model_pass
    calls = []
    async def delayed(*args, **kwargs):
        if kwargs.get('options'):
            calls.append(1)
            await asyncio.sleep(10)
        async for event in real(*args, **kwargs):
            yield event
    monkeypatch.setattr(assistant_loop, 'model_pass', delayed)
    monkeypatch.setattr(generation, 'MODEL_SECONDS', .01)
    services = FakeServices([[text_chunk('Answer')]])
    turn, events = asyncio.run(services.run(follow_ups_enabled=True))
    assert calls == [1] and turn.steps[-1]['status'] == 'timeout'
    assert turn.status == 'done' and turn.text == 'Answer' and events[-1]['follow_ups'] == []


def test_provider_and_unexpected_errors_do_not_fail_answer(monkeypatch):
    services = FakeServices([[text_chunk('Answer')], 500])
    turn, _ = asyncio.run(services.run(follow_ups_enabled=True))
    assert turn.status == 'done' and turn.steps[-1]['status'] == 'provider_error'
    assert 'private detail' not in json.dumps(turn.steps)
    def broken(*args):
        raise RuntimeError('private failure')
    monkeypatch.setattr(generation, 'followup_messages', broken)
    services = FakeServices([[text_chunk('Answer')]])
    turn, _ = asyncio.run(services.run(follow_ups_enabled=True))
    assert turn.status == 'done' and turn.steps[-1]['status'] == 'unavailable'
    assert len(services.model_requests) == 1 and 'private failure' not in json.dumps(turn.steps)


def test_setting_default_and_disabled_step(monkeypatch):
    monkeypatch.delenv('PWC_ASSISTANT_FOLLOW_UPS_ENABLED', raising=False)
    assert AssistantSettings().follow_ups_enabled is True
    monkeypatch.setenv('PWC_ASSISTANT_FOLLOW_UPS_ENABLED', 'false')
    settings = AssistantSettings()
    assert settings.follow_ups_enabled is False
    services = FakeServices([[text_chunk('Answer')]])
    turn, _ = asyncio.run(services.run(follow_ups_enabled=settings.follow_ups_enabled))
    assert len(services.model_requests) == len(turn.steps) == 1 and turn.follow_ups == []
    async def forbidden():
        with pytest.raises(AssistantMcpError):
            await CatalogMcp(None, 'http://catalog.test/mcp').call('suggest_follow_ups', {})
    asyncio.run(forbidden())


def test_digest_is_bounded_prioritizes_uncited_and_distinguishes_code_evidence():
    rows = [dict(id=i, title=f'Work {i}', publisher='Publisher', post_type='engineering-practice',
                 subtopics=['agents', 'fuzzing'], catalog_url=f'/paper/{i}',
                 repositories=[{'role': 'original' if i == 1 else 'target'}]) for i in range(1, 40)]
    steps = [{'kind': 'tool', 'name': 'search_papers', 'result': json.dumps({'results': rows})}]
    answer = '[Work 1](/paper/1) explains the main result.'
    digest = generation.digest(steps, answer)
    assert len(digest) == generation.MAX_DIGEST_WORKS
    assert digest[0]['title'] == 'Work 2' and digest[0]['released_code'] is None
    one = generation.digest([dict(steps[0], result=json.dumps({'results': rows[:2]}))], answer)
    assert one[-1]['released_code'] is True and one[-1]['cited_in_answer'] is True
    topic = {'slug': 'repair', 'label': 'Repair'}
    messages = generation.followup_messages('Question' * 2000, answer * 2000, steps, topic)
    assert estimate_input_tokens(messages) <= generation.INPUT_TOKENS
    body = json.loads(messages[1]['content'])
    assert body['topic'] == topic and body['shortened']
    assert body['works'][0]['title'] == 'Work 2'
    messages = generation.followup_messages('\x00' * 10000, '\x00' * 20000, [], topic)
    assert estimate_input_tokens(messages) <= generation.INPUT_TOKENS


def test_sse_checkpoint_persistence_trace_cli_and_token_totals(client, store, monkeypatch, verified, capsys):
    monkeypatch.setattr(get_assistant_settings(), 'follow_ups_enabled', True)
    def usage(value):
        return chunk(usage={'prompt_tokens': value, 'completion_tokens': 3, 'total_tokens': value + 3,
                            'completion_tokens_details': {'reasoning_tokens': 1}})
    services = fake_services(monkeypatch, [[tool_chunk(), usage(20)], [text_chunk('Answer'), usage(30)],
                                          [text_chunk(CANDIDATES), usage(40)]])
    response = client.post('/api/v1/assistant/turn', json={'question': 'Show agent harnesses'})
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    assert events[-1]['follow_ups'] == [QUESTION] and events[-1]['status'] == 'done'
    assert [e['text'] for e in events if e['type'] == 'text_delta'] == ['Answer']
    run = store.show_run(events[-1]['run_id'])
    assert run['tokens'] == {'input_tokens': 90, 'output_tokens': 9}
    step = run['steps'][-1]
    assert step['kind'] == 'follow_ups' and step['reasoning_tokens'] == 1 and step['input_tokens'] == 40
    assert step['proposed_candidates'][0]['question'] == QUESTION and step['candidates'][0]['kept']
    details = client.get('/api/v1/assistant/conversations/' + run['conversation_id']).json()
    assert details['messages'][-1]['follow_ups'] == [QUESTION]
    main(['show', run['id']], store=store)
    assert 'Step 4: follow_ups' in capsys.readouterr().out
    assert len(services.model_requests) == 3


def test_followup_usage_limit_switches_off_assistant_but_keeps_done(client, store, monkeypatch):
    monkeypatch.setattr(get_assistant_settings(), 'follow_ups_enabled', True)
    fake_services(monkeypatch, [[text_chunk('Answered')], httpx.Response(429,
        json={'error': 'session usage limit exceeded'}, headers={'retry-after': '60'})])
    response = client.post('/api/v1/assistant/turn', json={'question': 'Question'})
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    assert events[-1]['type'] == 'done' and events[-1]['status'] == 'done' and events[-1]['follow_ups'] == []
    run = store.show_run(events[-1]['run_id'])
    assert run['answer'] == 'Answered' and run['error'] is None
    assert run['steps'][-1]['status'] == 'usage_limit'
    assert client.get('/api/v1/assistant/status').json()['available'] is False
    assert client.post('/api/v1/assistant/turn', json={'question': 'Again'}).status_code == 503


@pytest.mark.parametrize('phase', ['model', 'verification'])
@pytest.mark.parametrize('disconnect', [False, True])
def test_stop_or_disconnect_during_optional_step_keeps_saved_answer(store, monkeypatch, phase, disconnect):
    async def exercise():
        started = asyncio.Event()
        real = assistant_loop.model_pass
        async def pause_model(*args, **kwargs):
            if kwargs.get('options') and phase == 'model':
                started.set()
                await asyncio.Event().wait()
            async for item in real(*args, **kwargs):
                yield item
        async def pause_verification(*args):
            started.set()
            await asyncio.Event().wait()
        monkeypatch.setattr(assistant_loop, 'model_pass', pause_model)
        monkeypatch.setattr(assistant_followups.FollowUpState, 'suggest', pause_verification)
        fake_services(monkeypatch, [[text_chunk('Complete saved answer')], [text_chunk(CANDIDATES)]])
        saved = store.begin('owner', None, 'Question')
        events = assistant.turn_events(AssistantTurnRequest(question='Question'), AssistantSettings(), saved, store)
        sent = []
        async def receive():
            await started.wait()
            return {'type': 'http.disconnect'}
        async def send(event):
            sent.append(event)
        async def consume():
            async with aclosing(events):
                async for event in events:
                    sent.append(event)
        if disconnect:
            task = asyncio.create_task(assistant.AssistantStreamResponse(events)(
                {'type': 'http', 'asgi': {'spec_version': '2.4'}}, receive, send))
        else:
            task = asyncio.create_task(consume())
        await asyncio.wait_for(started.wait(), 2)
        # This must already be durable, before the blocked optional call finishes.
        details = store.get_conversation('owner', saved.conversation_id)
        assert details['messages'][-1]['content'] == 'Complete saved answer'
        assert details['messages'][-1]['status'] == 'done' and details['messages'][-1]['follow_ups'] == []
        if not disconnect:
            with pytest.raises(VisitorLimitReached):
                store.begin('owner', saved.conversation_id, 'Too early')
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            await asyncio.wait_for(task, 2)
        run = store.show_run(saved.run_id)
        assert run['status'] == 'done' and run['answer'] == 'Complete saved answer' and run['follow_ups'] == []
        assert run['steps'][-1]['kind'] == 'follow_ups' and run['steps'][-1]['status'] == 'cancelled'
        store.begin('owner', saved.conversation_id, 'Allowed after disconnect')
    asyncio.run(exercise())


def test_answer_checkpoint_cannot_revive_expired_or_deleted_conversation(store):
    saved = store.begin('owner', None, 'Question')
    with store.sessions.begin() as db:
        db.get(AssistantConversation, saved.conversation_id).updated_at = datetime.now(UTC) - timedelta(days=100)
    store.save_answer(saved, Turn(text='Late', status='done'))
    with store.sessions.begin() as db:
        assert db.get(AssistantMessage, saved.message_id).content == ''
        db.delete(db.get(AssistantConversation, saved.conversation_id))
    store.save_answer(saved, Turn(text='Deleted', status='done'))
    with store.sessions() as db:
        assert db.get(AssistantMessage, saved.message_id) is None
