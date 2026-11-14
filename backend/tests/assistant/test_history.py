import asyncio
import json
from contextlib import aclosing
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from backend.assistant_cli import main
from backend.assistant_config import AssistantSettings
from backend.models.assistant import AssistantTurnRequest
from backend.models.database.assistant import AssistantConversation, AssistantMessage, AssistantToolCall
from backend.routers import assistant
from backend.services.assistant_loop import Turn
from backend.services.assistant_store import ConversationNotFound, QuestionLimitReached


def test_persist_history_and_atomic_question_limit(store):
    first = store.begin("visitor", None, "First question")
    store.finish(first, Turn(text="First answer", status="done"))
    for number in range(2, 11):
        saved = store.begin("visitor", first.conversation_id, f"Question {number}")
        assert saved.question_count == number
    assert saved.history[:2] == [{"role": "user", "content": "First question"}, {"role": "assistant", "content": "First answer"}]
    with pytest.raises(QuestionLimitReached):
        store.begin("visitor", first.conversation_id, "Too many")
    with store.sessions() as db:
        assert len(list(db.scalars(select(AssistantMessage)))) == 20
        assert db.get(AssistantConversation, first.conversation_id).question_count == 10


def test_ownership_and_no_network_identity_in_schema(store):
    saved = store.begin("owner", None, "Hello")
    with pytest.raises(ConversationNotFound):
        store.begin("stranger", saved.conversation_id, "Steal history")
    with store.sessions() as db:
        assert db.get(AssistantConversation, saved.conversation_id).visitor_hash != "owner"
    for table in (AssistantConversation.__table__, AssistantMessage.__table__, AssistantToolCall.__table__):
        assert not {"ip", "ip_address", "user_agent"} & set(table.columns.keys())


@pytest.mark.parametrize("status", ["failed", "cancelled", "done"])
def test_partial_answer_and_tool_steps_are_saved(store, status):
    saved = store.begin("owner", None, "Question")
    step = {"kind": "tool", "name": "search_papers", "result": "evidence"}
    store.finish(saved, Turn(text="Partial answer", status=status, steps=[step]))
    with store.sessions() as db:
        message = db.get(AssistantMessage, saved.message_id)
        assert message.content == "Partial answer" and message.status == status
        assert db.scalar(select(AssistantToolCall)).detail == step


def test_cookie_is_private_and_other_browser_cannot_continue(client, monkeypatch, store):
    async def fake(payload, settings, saved, store):
        yield assistant.sse({"type": "done", **saved.metadata()})
    monkeypatch.setattr(assistant, "turn_events", fake)
    first = client.post("/api/v1/assistant/turn", json={"question": "Hello"})
    cookie = first.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "Secure" not in cookie
    metadata = json.loads(first.text.split("data: ")[1])
    assert metadata["question_count"] == 1 and metadata["question_limit"] == 10
    conversation_id = metadata["conversation_id"]
    client.cookies.clear()
    assert client.post("/api/v1/assistant/turn", json={"conversation_id": conversation_id, "question": "Read it"}).status_code == 404


def test_secure_cookie_outside_local(monkeypatch):
    from backend.config import get_settings
    from starlette.responses import Response
    monkeypatch.setattr(get_settings(), "environment", "production")
    response = Response()
    assistant.set_visitor_cookie(response, "test", AssistantSettings())
    assert "Secure" in response.headers["set-cookie"]


def test_cookie_mutations_require_same_origin(client, monkeypatch):
    async def fake(*args):
        yield assistant.sse({"type": "done"})
    monkeypatch.setattr(assistant, "turn_events", fake)
    assert client.post("/api/v1/assistant/turn", json={"question": "Hi"}).status_code == 200
    assert client.post("/api/v1/assistant/turn", json={"question": "Hi"}, headers={"Origin": "https://evil.test"}).status_code == 403


def test_cancelled_route_saves_partial_answer(store, monkeypatch):
    class Context:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
    monkeypatch.setattr(assistant, "model_client", lambda _: Context())
    async def fake_loop(client, mcp, model, history, turn, **kwargs):
        turn.text = "Partial"
        yield {"type": "text_delta", "text": "Partial"}
        await asyncio.Event().wait()
    monkeypatch.setattr(assistant, "run_turn", fake_loop)
    saved = store.begin("owner", None, "Question")
    async def go():
        async with aclosing(assistant.turn_events(AssistantTurnRequest(question="Question"), AssistantSettings(), saved, store)) as events:
            await anext(events)  # metadata
            await anext(events)  # partial answer
    asyncio.run(go())
    with store.sessions() as db:
        message = db.get(AssistantMessage, saved.message_id)
        assert message.content == "Partial" and message.status == "cancelled"


def test_retention_command_deletes_cascading_history(store, capsys):
    old = store.begin("owner", None, "Expired")
    current = store.begin("owner", None, "Current")
    store.finish(old, Turn(text="Answer", status="done", steps=[{"kind": "tool", "name": "search_papers"}]))
    with store.sessions.begin() as db:
        db.execute(update(AssistantConversation).where(AssistantConversation.id == old.conversation_id)
                   .values(updated_at=datetime.now(UTC) - timedelta(days=91)))
        # An old conversation with recent activity must survive retention.
        db.execute(update(AssistantConversation).where(AssistantConversation.id == current.conversation_id)
                   .values(created_at=datetime.now(UTC) - timedelta(days=180)))
    main(["purge"], store=store)
    assert "Deleted 1" in capsys.readouterr().out
    with store.sessions() as db:
        assert db.get(AssistantConversation, current.conversation_id)
        assert db.get(AssistantMessage, old.message_id) is None
        assert db.scalar(select(AssistantToolCall)) is None
