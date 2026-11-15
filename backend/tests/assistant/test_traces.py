import asyncio
import json
import logging
from contextlib import aclosing
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from openai import AsyncOpenAI
from sqlalchemy import select, update

from backend.assistant_cli import main
from backend.assistant_config import AssistantSettings
from backend.models.assistant import AssistantTurnRequest
from backend.models.database.assistant import AssistantConversation, AssistantRun, AssistantRunStep
from backend.routers import assistant
from backend.services.assistant_loop import Turn
from backend.services.assistant_mcp import CatalogMcp
from backend.tests.assistant.test_loop import FakeServices, text_chunk, tool_chunk, chunk


def fake_services(monkeypatch, replies):
    services = FakeServices(replies)
    mcp_http = httpx.AsyncClient(transport=httpx.MockTransport(services.mcp))
    monkeypatch.setattr(assistant, "CatalogMcp", lambda http, endpoint, **kwargs: CatalogMcp(mcp_http, endpoint, **kwargs))
    monkeypatch.setattr(assistant, "model_client", lambda settings: AsyncOpenAI(
        api_key="fake", base_url="http://model.test/v1", max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(services.model))))
    return services


@pytest.mark.parametrize("fail", [False, True])
def test_full_trace_from_http_turn(client, store, monkeypatch, caplog, fail):
    fake_services(monkeypatch, [[tool_chunk()], 500 if fail else [text_chunk("Evidence answer"), chunk(usage={
        "prompt_tokens": 50, "completion_tokens": 8, "total_tokens": 58,
        "completion_tokens_details": {"reasoning_tokens": 3}})]])
    with caplog.at_level(logging.INFO, logger=assistant.__name__):
        response = client.post("/api/v1/assistant/turn", json={"question": "Private question", "surface": "landing",
            "site_path": "/catalog?query=private#fragment", "analytics_session_id": str(uuid4())})
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    run = store.show_run(events[0]["run_id"])
    assert run["status"] == ("failed" if fail else "done")
    assert run["question"] == "Private question" and run["site_path"] == "/catalog"
    assert run["surface"] == "landing"
    assert len(run["prompt_hash"]) == 64
    assert [s["kind"] for s in run["steps"]] == ["model", "tool", "model"]
    assert run["steps"][-1]["reasoning_tokens"] == (None if fail else 3)
    assert run["steps"][1]["full_bytes"] > 0
    assert run["steps"][1]["limit_bytes"] == 16384
    assert run["steps"][1]["result"] in json.dumps(run["steps"][1], ensure_ascii=False).replace('\\"', '"')
    assert run["tokens"]["input_tokens"] is None  # first call has no usage
    with store.sessions() as db:
        assert db.get(AssistantRun, run["id"]).analytics_session_id is None
    logs = [r.getMessage() for r in caplog.records if r.name == assistant.__name__]
    assert len(logs) == 1
    assert run["id"] in logs[0] and "model_steps=2 tool_steps=1" in logs[0]
    assert "Private question" not in logs[0] and "Evidence answer" not in logs[0]
    assert bool(run["error"]) == fail


def test_cancelled_trace_records_partial_model_step(store, monkeypatch):
    fake_services(monkeypatch, [[text_chunk("Partial answer"), text_chunk("Should not appear")]])
    async def no_tools(self):
        return []
    monkeypatch.setattr(CatalogMcp, "tools", no_tools)
    saved = store.begin("owner", None, "Question")
    async def go():
        events = assistant.turn_events(AssistantTurnRequest(question="Question"), AssistantSettings(follow_ups_enabled=False), saved, store)
        async with aclosing(events):
            await anext(events)
            await anext(events)
    asyncio.run(go())
    run = store.show_run(saved.run_id)
    assert run["status"] == "cancelled"
    assert run["answer"] == "Partial answer"
    assert run["steps"][0]["status"] == "cancelled"
    assert run["steps"][0]["text"] == "Partial answer"


def test_client_closing_at_done_cannot_change_completed_trace(store, monkeypatch):
    fake_services(monkeypatch, [[text_chunk("Completed answer")]])
    saved = store.begin("owner", None, "Question")
    async def go():
        events = assistant.turn_events(AssistantTurnRequest(question="Question"), AssistantSettings(follow_ups_enabled=False), saved, store)
        async with aclosing(events):
            async for event in events:
                if event.startswith("event: done"):
                    # The database must already be committed before this event.
                    assert store.show_run(saved.run_id)["status"] == "done"
                    break
    asyncio.run(go())
    run = store.show_run(saved.run_id)
    assert run["status"] == "done"
    assert run["answer"] == "Completed answer"
    assert len(run["steps"]) == 1


def test_feedback_requires_owner(client, store, monkeypatch):
    fake_services(monkeypatch, [[text_chunk()]])
    response = client.post("/api/v1/assistant/turn", json={"question": "Hi"})
    run_id = json.loads(response.text.split("data: ")[1].split("\n")[0])["run_id"]
    url = f"/api/v1/assistant/runs/{run_id}/feedback"
    assert client.post(url, json={"rating": "good", "note": "Useful"}).status_code == 200
    assert store.show_run(run_id)["feedback"] == {"rating": "good", "note": "Useful"}
    assert client.post(url, json={"rating": "bad", "note": "x" * 501}).status_code == 422
    client.cookies.clear()
    assert client.post(url, json={"rating": "bad"}).status_code == 404


def test_read_only_commands_without_model_key(store, capsys, monkeypatch):
    monkeypatch.delenv("PWC_ASSISTANT_API_KEY", raising=False)
    saved = store.begin("owner", None, "Question to inspect")
    steps = [{"kind": "model", "text": "Looking", "input_tokens": 10, "output_tokens": 2},
             {"kind": "tool", "name": "search_papers", "result": "Evidence"},
             {"kind": "model", "text": "Answer", "input_tokens": 20, "output_tokens": 5}]
    store.finish(saved, Turn(text="Answer", status="done", steps=steps))
    main(["list", "--days", "1"], store=store)
    listed = json.loads(capsys.readouterr().out)
    assert listed["question"] == "Question to inspect" and listed["steps"] == 3
    assert listed["tokens"] == {"input_tokens": 30, "output_tokens": 7}
    main(["show", saved.run_id], store=store)
    shown = capsys.readouterr().out
    assert shown.index("Step 1: model") < shown.index("Step 2: tool") < shown.index("Step 3: model") < shown.index("Answer: Answer")
    assert "Question to inspect" in shown and "Evidence" in shown
    main(["export", "--days", "1"], store=store)
    exported = json.loads(capsys.readouterr().out)
    assert exported["steps"] == steps and exported["id"] == saved.run_id
    assert store.show_run(saved.run_id) == exported  # reads have not changed it


def test_retention_cascades_to_runs_and_steps(store):
    saved = store.begin("owner", None, "Old")
    store.finish(saved, Turn(status="done", steps=[{"kind": "model", "text": "Old answer"}]))
    with store.sessions.begin() as db:
        db.execute(update(AssistantConversation).values(updated_at=datetime.now(UTC) - timedelta(days=91)))
    assert store.purge(90) == 1
    with store.sessions() as db:
        assert db.scalar(select(AssistantRun)) is None
        assert db.scalar(select(AssistantRunStep)) is None


def test_working_notes_stay_in_trace_not_persisted_answer_or_followup(client, store, monkeypatch):
    note = "Let me check the posts."
    services = fake_services(monkeypatch, [
        [text_chunk(note), tool_chunk()], [text_chunk("Final answer")], [text_chunk("Follow-up")],
    ])
    response = client.post("/api/v1/assistant/turn", json={"question": "Find papers"})
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    meta = events[0]
    run = store.show_run(meta["run_id"])
    assert run["answer"] == "Final answer"
    assert run["steps"][0]["text"] == note
    assert events[1] == {"type": "working_note", "text": note}
    conversation = client.get(f"/api/v1/assistant/conversations/{meta['conversation_id']}").json()
    assert conversation["messages"][-1]["content"] == "Final answer"
    client.post("/api/v1/assistant/turn", json={"question": "And next?", "conversation_id": meta["conversation_id"]})
    history = services.model_requests[-1]["messages"]
    assert note not in json.dumps(history)
    assert any(m["role"] == "assistant" and m["content"] == "Final answer" for m in history)
