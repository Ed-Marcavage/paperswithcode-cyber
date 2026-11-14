import asyncio
import io
import json

import httpx
from openai import AsyncOpenAI

from backend.assistant_eval import QUESTIONS, evaluate, result_row
from backend.services.assistant_loop import Turn
from backend.services.assistant_mcp import CatalogMcp
from backend.tests.assistant.test_loop import FakeServices, chunk, text_chunk, tool_chunk


def test_twenty_questions_use_named_model_and_write_grounded_results():
    replies = []
    for _ in QUESTIONS:
        replies.extend([[tool_chunk()], [text_chunk("[Evidence](/paper/evidence)"), chunk(finish="stop"),
                        chunk(usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})]])
    services = FakeServices(replies)
    output = io.StringIO()

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(services.model)) as model_http:
            async with httpx.AsyncClient(transport=httpx.MockTransport(services.mcp)) as mcp_http:
                async with AsyncOpenAI(api_key="fake", base_url="http://model.test/v1", max_retries=0, http_client=model_http) as model:
                    return await evaluate(model, CatalogMcp(mcp_http, "http://catalog.test/mcp"), "named-test-model", output)
    assert asyncio.run(run())
    rows = [json.loads(line) for line in output.getvalue().splitlines()]
    assert len(rows) == len(set(QUESTIONS)) == 20
    for index, row in enumerate(rows, 1):
        assert row["question_id"] == index and row["question"] == QUESTIONS[index - 1]
        assert row["model"] == "named-test-model" and row["status"] == "done"
        assert row["links"] == ["/paper/evidence"] and row["answer"]
        assert row["tools"][0]["name"] == "search_papers"
        assert row["duration_ms"] >= 0 and row["model_calls"] == 2
        assert row["tokens"] == {"input_tokens": None, "output_tokens": None}
    assert all(r["model"] == "named-test-model" for r in services.model_requests)


def test_evaluation_stops_after_quota_and_writes_partial_row():
    services = FakeServices([httpx.Response(429, json={"error": "session usage limit exceeded"})])
    output = io.StringIO()

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(services.model)) as model_http:
            async with httpx.AsyncClient(transport=httpx.MockTransport(services.mcp)) as mcp_http:
                async with AsyncOpenAI(api_key="fake", base_url="http://model.test/v1", max_retries=0, http_client=model_http) as model:
                    return await evaluate(model, CatalogMcp(mcp_http, "http://catalog.test/mcp"), "named", output)
    assert not asyncio.run(run())
    assert len(services.model_requests) == 1
    assert json.loads(output.getvalue())["status"] == "provider_limit"


def test_token_totals_only_when_every_call_reports_usage():
    turn = Turn(text="Answer", status="done", steps=[{"kind": "model", "input_tokens": 4, "output_tokens": 2}] * 2)
    assert result_row(1, "Question", "model", turn, 1.25)["tokens"] == {"input_tokens": 8, "output_tokens": 4}
