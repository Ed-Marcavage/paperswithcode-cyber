import asyncio
import io
import json

import httpx
import pytest
from openai import AsyncOpenAI

from backend.assistant_eval import QUESTIONS, TOPIC_QUESTIONS, evaluate, result_row
from backend.services.assistant_loop import Turn
from backend.services.assistant_mcp import CatalogMcp
from backend.tests.assistant.test_loop import FakeServices, chunk, text_chunk, tool_chunk


@pytest.fixture(autouse=True)
def topic_choices(monkeypatch):
    from backend import assistant_eval
    monkeypatch.setattr(assistant_eval, "resolve_topic", lambda slug, sessions: {
        "slug": slug, "label": slug.replace("-", " ").title(), "count": 40,
    })


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
        assert row["topic"] == TOPIC_QUESTIONS.get(row["question"])
        assert row["follow_ups"] == []
        assert row["follow_ups_check"] == {"expected": row["question"] in TOPIC_QUESTIONS,
                                           "passed": False if row["question"] in TOPIC_QUESTIONS else None}
    assert all(r["model"] == "named-test-model" for r in services.model_requests)
    scoped = [r for r in services.model_requests if len(r["messages"]) > 1 and r["messages"][1]["role"] == "system"]
    assert len(scoped) == 8  # Both model passes of each of the four topic questions.


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


def test_cli_uses_backend_environment_and_internal_mcp_url(tmp_path, monkeypatch, capsys):
    from backend import assistant_eval
    replies = [[tool_chunk()], [text_chunk("Answer")]] * len(QUESTIONS)
    services = FakeServices(replies)
    mcp_urls = []

    def dispatch(request):
        if request.url.host == "model.test":
            assert request.headers["authorization"] == "Bearer evaluation-test-key"
            return services.model(request)
        assert str(request.url) == "http://mcp:7860/mcp"
        assert "authorization" not in request.headers
        mcp_urls.append(str(request.url))
        return services.mcp(request)

    class TestHttpClient(httpx.AsyncClient):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(dispatch), **kwargs)

    monkeypatch.chdir(tmp_path)  # No environment file is present or needed.
    monkeypatch.setenv("PWC_ASSISTANT_API_KEY", "evaluation-test-key")
    monkeypatch.setenv("PWC_ASSISTANT_BASE_URL", "http://model.test/v1")
    monkeypatch.setattr(assistant_eval.httpx, "AsyncClient", TestHttpClient)
    monkeypatch.setattr(assistant_eval, "model_client", lambda settings: AsyncOpenAI(
        api_key=settings.api_key.get_secret_value(), base_url=settings.base_url,
        max_retries=0, http_client=TestHttpClient()))
    output = tmp_path / "evaluation.jsonl"
    assert assistant_eval.main(["--model", "named-container-model", "--mcp-url", "http://mcp:7860/mcp", "--output", str(output)]) == 0
    assert len(mcp_urls) == 22  # One discovery + vocabulary fetch, then 20 actual tool calls.
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(rows) == 20
    assert all(row["model"] == "named-container-model" and row["status"] == "done" for row in rows)
    captured = capsys.readouterr()
    assert "evaluation-test-key" not in output.read_text() + captured.out + captured.err


def test_owner_questions_lead_the_twenty_item_evaluation_without_duplicate_generic_prompts():
    assert QUESTIONS[:4] == (
        "Which posts show cutting-edge harness design for automated pentesting?",
        "How are teams benchmarking AI agents on security tasks, and what did they find?",
        "What do defenders report about ARTEX and other agentic attack frameworks?",
        "How are companies using agents to triage and fix vulnerabilities?",
    )
    assert len(QUESTIONS) == len(set(QUESTIONS)) == 20
    dropped = {
        "Show me recent security papers in the catalog.",
        "Which organizations have research in the catalog?",
        "Which developers contribute to catalog repositories?",
        "Show engineering posts about security from the catalog.",
        "Which catalog topics and target categories can I browse?",
        "Show catalog work on vulnerability repair.",
        "Find security work involving AI systems.",
        "List trending security papers and link their catalog pages.",
    }
    assert not dropped.intersection(QUESTIONS)
    assert any("cached text" in question for question in QUESTIONS)
    assert any("ZZZ-Unpublished-Quantum-Toaster-999" in question for question in QUESTIONS)
    assert any("organization page" in question for question in QUESTIONS)
    assert any("profile link" in question for question in QUESTIONS)
    assert len(TOPIC_QUESTIONS) == 4 and set(TOPIC_QUESTIONS).issubset(QUESTIONS)


def test_topic_evaluation_records_verified_followups(monkeypatch):
    from backend.services import assistant_followups
    from backend.tests.assistant.test_followups import QUESTION, CHECK
    monkeypatch.setattr(assistant_followups, "read_counts", lambda *args: {"match_count": 5, "new_match_count": 3})
    replies = [[tool_chunk()], [tool_chunk(name="suggest_follow_ups", arguments=json.dumps({"candidates": [{"question": QUESTION, "check": CHECK}]}))],
               [text_chunk("Grounded answer")]]
    services = FakeServices(replies * 4)
    output = io.StringIO()
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(services.model)) as model_http:
            async with httpx.AsyncClient(transport=httpx.MockTransport(services.mcp)) as mcp_http:
                async with AsyncOpenAI(api_key="fake", base_url="http://model.test/v1", max_retries=0, http_client=model_http) as model:
                    return await evaluate(model, CatalogMcp(mcp_http, "http://catalog.test/mcp"), "named", output, questions=tuple(TOPIC_QUESTIONS))
    assert asyncio.run(run())
    for row in map(json.loads, output.getvalue().splitlines()):
        assert row["follow_ups_check"] == {"expected": True, "passed": True}
        assert row["follow_ups"] == [QUESTION]
        decision = json.loads(row["tools"][-1]["result"])["candidates"][0]
        assert decision["match_count"] == 5 and decision["new_match_count"] == 3 and decision["kept"]
