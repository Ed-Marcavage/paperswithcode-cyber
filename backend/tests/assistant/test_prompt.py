import asyncio
import hashlib

from backend.services.assistant_loop import FINALIZER_PROMPT, PROMPT_VERSION, SYSTEM_PROMPT, TurnLimits
from backend.tests.assistant.test_loop import FakeServices, text_chunk, tool_chunk


def test_answer_contract_reaches_normal_generation_and_budget_finalizer():
    services = FakeServices([[tool_chunk()], [text_chunk('Found one useful post.')]])
    turn, _ = asyncio.run(services.run(TurnLimits(tool_calls=1)))
    assert PROMPT_VERSION == 'cyber-assistant-v12' and turn.status == 'limit_reached'
    assert services.model_requests[0]['messages'][0]['content'] == SYSTEM_PROMPT
    final_messages = services.model_requests[-1]['messages']
    assert final_messages[0]['content'] == SYSTEM_PROMPT
    assert final_messages[-1]['content'] == FINALIZER_PROMPT
    for prompt in (SYSTEM_PROMPT, FINALIZER_PROMPT):
        assert 'No emoji' in prompt
        assert 'internal field names' in prompt and 'selection thresholds' in prompt
        assert 'catalog_url' not in prompt and 'addresses present in' in prompt
        assert 'at most six items' in prompt and 'one short caveat' in prompt
        assert 'catalog-wide' in prompt
    exact_paths = 'Use catalog page paths exactly as the tools return them and never add a domain to them.'
    assert exact_paths in SYSTEM_PROMPT
    assert exact_paths in final_messages[0]['content']
    assert 'Link items however reads best' in SYSTEM_PROMPT
    assert 'one-sentence direct answer' in SYSTEM_PROMPT
    assert 'For industry posts, start with find_posts' in SYSTEM_PROMPT
    assert 'completed search actually supports that claim' in SYSTEM_PROMPT
    assert 'budget stop does not show' in FINALIZER_PROMPT
    assert 'not evidence of\nmissing coverage' in SYSTEM_PROMPT

    assert hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest() == "d76264c4696450b90037b2d5c252bb5f0baf34ac11296113949c12617c128d00"

    assert hashlib.sha256(FINALIZER_PROMPT.encode()).hexdigest() == "ffb1545d08455b7fe3d8bcabbd531c5f86ac91312a1abfd9cd7d9973856aec37"
