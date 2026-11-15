import asyncio
import json

import httpx

from backend.services.assistant_loop import (
    FINAL_OUTPUT_TOKENS, FINAL_RETRY_OUTPUT_TOKENS, TurnLimits, generation_options,
)
from backend.tests.assistant.test_loop import FakeServices, chunk, text_chunk, tool_chunk


def thinking_only(tokens=2048):
    return [chunk({"reasoning": "Internal reasoning only"}), chunk(finish="length"),
            chunk(usage={"prompt_tokens": 100, "completion_tokens": tokens, "total_tokens": 100 + tokens,
                         "completion_tokens_details": {"reasoning_tokens": tokens}})]


def test_empty_reasoning_finalizer_retries_once_with_larger_allowance():
    services = FakeServices([[tool_chunk()], thinking_only(FINAL_OUTPUT_TOKENS), [text_chunk("Evidence answer")]])
    turn, events = asyncio.run(services.run(TurnLimits(tool_calls=1)))
    assert turn.text == "Evidence answer"
    assert len(services.model_requests) == 3
    first, retry = services.model_requests[-2:]
    assert "tools" not in first and "tools" not in retry
    assert first["reasoning_effort"] == retry["reasoning_effort"] == "none"
    assert first["max_tokens"] == FINAL_OUTPUT_TOKENS
    assert retry["max_tokens"] == FINAL_RETRY_OUTPUT_TOKENS > FINAL_OUTPUT_TOKENS > 2048
    assert first["messages"] == retry["messages"]  # Never replay hidden reasoning.
    step = turn.steps[-2]
    assert step["reasoning_tokens"] == FINAL_OUTPUT_TOKENS
    assert step["reasoning_chars"] == len("Internal reasoning only")
    assert step["text"] == "" and step["finish_reason"] == "length"
    assert turn.steps[-1]["phase"] == "finalizer_retry"
    assert turn.steps[-1]["reasoning_tokens"] is None
    assert "Internal reasoning" not in json.dumps(events)


def test_two_empty_finalizers_fall_back_within_eight_call_budget():
    services = FakeServices([[tool_chunk()]] * 6 + [thinking_only()] * 2)
    turn, _ = asyncio.run(services.run())
    assert len(services.model_requests) == 8
    assert "could not establish" in turn.text
    assert [s["phase"] for s in turn.steps if s["kind"] == "model"] == ["research"] * 6 + ["finalizer", "finalizer_retry"]


def test_answering_finalizer_is_not_retried_and_research_uses_low_effort():
    services = FakeServices([[tool_chunk()], [text_chunk("Answer")]])
    turn, _ = asyncio.run(services.run(TurnLimits(tool_calls=1)))
    assert turn.text == "Answer" and len(services.model_requests) == 2
    assert services.model_requests[0]["reasoning_effort"] == "low"
    assert generation_options(final=True)["reasoning_effort"] == "none"


def test_no_usage_keeps_reasoning_tokens_unknown_even_when_reasoning_streams():
    services = FakeServices([[chunk({"reasoning": "Not an answer"}), text_chunk("Answer")]])
    turn, _ = asyncio.run(services.run())
    assert turn.text == "Answer"
    assert turn.steps[0]["reasoning_tokens"] is None
    assert turn.steps[0]["reasoning_chars"] == len("Not an answer")


def test_busy_finalizer_retries_within_reserved_attempt_but_quota_does_not():
    services = FakeServices([[tool_chunk()], httpx.Response(429, json={"error": "too many concurrent requests"}), [text_chunk("Recovered")]])
    turn, _ = asyncio.run(services.run(TurnLimits(tool_calls=1)))
    assert turn.text == "Recovered" and len(services.model_requests) == 3
    assert turn.steps[-1]["phase"] == "finalizer_retry"
    quota = FakeServices([[tool_chunk()], httpx.Response(429, json={"error": "session usage limit exceeded"})])
    turn, _ = asyncio.run(quota.run(TurnLimits(tool_calls=1)))
    assert turn.status == "provider_limit" and len(quota.model_requests) == 2
