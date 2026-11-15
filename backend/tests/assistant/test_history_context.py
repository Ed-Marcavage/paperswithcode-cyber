import asyncio
import copy
import json
import math
from types import SimpleNamespace

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import ValidationError

from backend.assistant_config import AssistantSettings, get_assistant_settings
from backend.services.assistant_context import paired_messages
from backend.services.assistant_history import build_history, trace_messages, digest_message, HistoryContextTooLarge
from backend.services.assistant_input_budget import (
    HISTORY_INPUT_TOKENS, MAX_CONTEXT_INPUT_TOKENS, INPUT_TOKEN_BUDGET, FINAL_INPUT_RESERVE,
    FINAL_INPUT_TOKENS, estimate_input_tokens, history_token_estimate, growth_charge, finalizer_messages,
)
from backend.services.assistant_loop import SYSTEM_PROMPT, FINALIZER_PROMPT, Turn, run_turn
from backend.services.assistant_mcp import CatalogMcp
from backend.tests.assistant.test_loop import FakeServices, text_chunk, tool_chunk, chunk


def evidence(index=1, size=0):
    call = {'id': f'call-{index}', 'type': 'function', 'function': {'name': 'search_papers', 'arguments': '{"query": "agent harness"}'}}
    payload = {'results': [{'id': index, 'title': f'Agent harness {index}', 'publisher': 'Example Labs',
        'published': '2026-11-14', 'post_type': 'engineering-practice', 'has_code': True,
        'catalog_url': f'/paper/{index}', 'source_url': f'https://example.test/{index}', 'abstract': 'x'*size}]}
    result = json.dumps(payload, indent=2)
    steps = [{'kind': 'model', 'phase': 'research', 'text': 'Working note not replayed.', 'tool_calls': [call]},
             {'kind': 'tool', 'call_id': call['id'], 'name': call['function']['name'], 'arguments': call['function']['arguments'], 'result': result}]
    return steps


def conversation(count=1, size=0):
    messages, steps = [], {}
    for i in range(1, count+1):
        messages.extend([SimpleNamespace(id=f'u{i}', role='user', content=f'Question {i}'),
                         SimpleNamespace(id=f'a{i}', role='assistant', content=f'Answer {i}')])
        steps[f'a{i}'] = evidence(i, size)
    return messages, steps


@pytest.mark.parametrize('mode', ['answers', 'digest', 'full'])
def test_modes_preserve_answers_and_requested_evidence(mode):
    messages, steps = conversation()
    steps['a1'].extend([{**s, 'phase': 'follow_ups'} for s in evidence(999)])
    history = build_history(messages, steps, mode)
    assert history[0] == {'role': 'user', 'content': 'Question 1'}
    assert {'role': 'assistant', 'content': 'Answer 1'} in history
    assert '999' not in json.dumps(history) and 'Working note' not in json.dumps(history)
    if mode == 'answers':
        assert len(history) == 2
    elif mode == 'digest':
        assert len(history) == 3 and history[-1]['role'] == 'system'
        digest = json.loads(history[-1]['content'].split('\n',1)[1])[0]
        assert digest == {'title': 'Agent harness 1', 'publisher': 'Example Labs', 'date': '2026-11-14',
            'post_type': 'engineering-practice', 'released_code': True, 'catalog_url': '/paper/1', 'source_url': 'https://example.test/1'}
    else:
        assert history[1]['tool_calls'] == steps['a1'][0]['tool_calls']
        assert history[2] == {'role': 'tool', 'tool_call_id': 'call-1', 'content': steps['a1'][1]['result']}
    assert paired_messages(history) == history


def test_pairing_omits_interrupted_and_unexecuted_calls_but_keeps_error_and_cached_results():
    steps = evidence()
    calls = steps[0]['tool_calls']
    calls.extend([dict(calls[0], id='unexecuted'), dict(calls[0], id='interrupted')])
    steps.extend([{'kind':'tool','call_id':'interrupted','result':'','error':'Tool interrupted.'},
                  *evidence(2)])
    steps[-1].update(error='Tool failed.', result='Try a different search.')
    cached = evidence(3)
    cached[-1].update(cached_from='call-1', result='Already fetched as tool call call-1; reuse that result above.')
    steps.extend(cached)
    result = trace_messages(steps)
    assert len(result) == 6 and result[0]['tool_calls'] == calls[:1]
    assert result[3]['content'] == 'Try a different search.' and 'call-1' in result[-1]['content']
    assert paired_messages(result) == result


def test_parallel_tool_order_and_legacy_tool_only_trace():
    first, second = evidence(), evidence(2)
    steps = [dict(first[0], tool_calls=first[0]['tool_calls']+second[0]['tool_calls']), second[1], first[1]]
    messages = trace_messages(steps)
    assert [m['tool_call_id'] for m in messages[1:]] == ['call-1', 'call-2']
    assert trace_messages([first[1]]) == trace_messages(first)


def test_digest_code_unknown_is_not_false_and_only_official_code_counts():
    steps = evidence()
    rows = [dict(id=i, title=f'Item {i}', repositories=[{'role': role}]) for i,role in enumerate(['target', 'original', 'supporting'])]
    rows.append({'id':4, 'title':'Explicit no code', 'has_code':False})
    steps[-1]['result'] = json.dumps({'data': {'papers': rows}})
    digest = json.loads(digest_message(steps)[0]['content'].split('\n',1)[1])
    assert [r['released_code'] for r in digest] == [None, True, None, False]
    assert all(r['source_url'] is None for r in digest)


def test_oldest_full_to_digest_to_answers_before_touching_next_turn():
    messages, steps = conversation(3, size=12000)
    original = copy.deepcopy(steps)
    one_full = estimate_input_tokens(build_history(messages[:2], steps, 'full'))
    history = build_history(messages, steps, 'full', allowance=2*one_full+500)
    assert 'turn 1 to digest' in history[0]['content'] and 'turn 1 to answers' not in history[0]['content']
    assert [m['tool_call_id'] for m in history if m['role']=='tool'] == ['call-2','call-3']
    smaller = build_history(messages, steps, 'full', allowance=one_full+700)
    note = smaller[0]['content']
    assert note.index('turn 1 to digest') < note.index('turn 1 to answers') < note.index('turn 2 to digest')
    assert 'turn 3 to' not in note
    assert [m['tool_call_id'] for m in smaller if m['role']=='tool'] == ['call-3']
    assert next(m for m in smaller if m['role']=='tool')['content'] == steps['a3'][1]['result']
    assert estimate_input_tokens(smaller) <= one_full+700
    assert steps == original and paired_messages(smaller) == smaller


def test_latest_turn_is_never_silently_weakened_even_if_allowance_is_too_small():
    messages, steps = conversation(2, size=10000)
    with pytest.raises(HistoryContextTooLarge):
        build_history(messages, steps, 'full', allowance=100)


def test_history_rejection_rolls_back_question_count_and_visitor_admission(store, monkeypatch):
    from backend.services import assistant_store
    first = store.begin('owner', None, 'Question')
    store.finish(first, Turn(text='Answer', status='done'))
    original = assistant_store.build_history
    def reject(*args):
        raise HistoryContextTooLarge('Too large')
    monkeypatch.setattr(assistant_store, 'build_history', reject)
    with pytest.raises(HistoryContextTooLarge):
        store.begin('owner', first.conversation_id, 'Cannot fit')
    assert store.get_conversation('owner', first.conversation_id)['question_count'] == 1
    monkeypatch.setattr(assistant_store, 'build_history', original)
    assert store.begin('owner', first.conversation_id, 'Fits now').question_count == 2


def test_store_reads_run_steps_not_visitor_tool_summaries_and_modes_are_configurable(store, monkeypatch):
    first = store.begin('owner', None, 'First question')
    steps = evidence()
    steps.extend([{**s, 'phase':'follow_ups'} for s in evidence(88)])
    store.finish(first, Turn(text='First answer', status='done', steps=steps))
    for mode in ('full','digest','answers'):
        monkeypatch.setattr(get_assistant_settings(), 'history_context', mode)
        next_turn = store.begin('owner', first.conversation_id, 'Which of these released code?')
        assert next_turn.history[-1]['content'] == 'Which of these released code?'
        assert '88' not in json.dumps(next_turn.history)
        if mode=='full':
            assert next_turn.history[2]['content'] == steps[1]['result']
        elif mode=='digest':
            assert 'released_code' in json.dumps(next_turn.history) and not any(m['role']=='tool' for m in next_turn.history)
        else:
            assert not any(m['role'] in {'tool','system'} for m in next_turn.history)
        assert paired_messages(next_turn.history) == next_turn.history
        store.finish(next_turn, Turn(text='Continued', status='done'))


def test_settings_default_and_strict_values(monkeypatch):
    monkeypatch.delenv('PWC_ASSISTANT_HISTORY_CONTEXT', raising=False)
    assert AssistantSettings().history_context == 'full'
    for mode in ('answers','digest','full'):
        monkeypatch.setenv('PWC_ASSISTANT_HISTORY_CONTEXT', mode)
        assert AssistantSettings().history_context == mode
    monkeypatch.setenv('PWC_ASSISTANT_HISTORY_CONTEXT','unknown')
    with pytest.raises(ValidationError):
        AssistantSettings()


def test_growth_budget_prorates_usage_instead_of_subtracting_incompatible_estimates():
    assert growth_charge(10000, 20000, 15000) == 2500
    assert growth_charge(None, 20000, 15000) == 5000
    assert growth_charge(10000, 20000, 0) == 10000
    assert growth_charge(100, 1000, 999) == 1
    assert HISTORY_INPUT_TOKENS == 128000 and MAX_CONTEXT_INPUT_TOKENS == INPUT_TOKEN_BUDGET == 256000
    assert FINAL_INPUT_RESERVE == 2*FINAL_INPUT_TOKENS == 64000


def test_four_question_full_chat_keeps_room_for_research_and_counts_actual_cost():
    messages, steps = conversation(3, size=40000)
    history = build_history(messages, steps, 'full') + [{'role':'user','content':'Which of these released code?'}]
    usage = chunk(usage={'prompt_tokens':50000,'completion_tokens':10,'total_tokens':50010})
    services = FakeServices([[tool_chunk(), usage], [text_chunk('These released code.'), usage]])
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(services.model)) as model_http, httpx.AsyncClient(transport=httpx.MockTransport(services.mcp)) as mcp_http:
            async with AsyncOpenAI(api_key='fake', base_url='http://model.test/v1', max_retries=0, http_client=model_http) as model:
                turn = Turn()
                async for _ in run_turn(model, CatalogMcp(mcp_http,'http://catalog.test/mcp'), 'fake', history, turn, follow_ups_enabled=False):
                    pass
                return turn
    turn = asyncio.run(run())
    assert turn.status == 'done' and len(services.model_requests) == 2 and len(services.tool_requests) == 1
    assert services.model_requests[0]['messages'][1:] == history
    model_steps = [s for s in turn.steps if s['kind']=='model']
    assert model_steps[-1]['cumulative_input_tokens'] == 100000
    assert model_steps[-1]['cumulative_new_turn_input_tokens'] < 10000
    for step in model_steps:
        expected = math.ceil(step['input_tokens'] * (step['input_token_estimate']-history_token_estimate(history)) / step['input_token_estimate'])
        assert step['new_turn_input_token_charge'] == expected
    assert all(estimate_input_tokens(r['messages'], r['tools']) <= MAX_CONTEXT_INPUT_TOKENS for r in services.model_requests)


def test_finalizer_retains_paired_history_and_only_shortens_current_evidence():
    messages, steps = conversation(2, size=2000)
    history = build_history(messages, steps, 'full') + [{'role':'user','content':'Which released code?'}]
    new_steps = evidence(9, size=20000)
    allowance = history_token_estimate(history) + 2500
    result = finalizer_messages(SYSTEM_PROMPT, FINALIZER_PROMPT, history, new_steps, allowance)
    assert result[1:1+len(history)] == history
    assert paired_messages(result) == result
    assert estimate_input_tokens(result) <= allowance and 'Shortened for input budget' in result[-2]['content']
    with pytest.raises(ValueError):
        finalizer_messages(SYSTEM_PROMPT, FINALIZER_PROMPT, history, [], 100)
