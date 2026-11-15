from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from backend.assistant_config import get_assistant_settings
from backend.models.database.assistant import AssistantConversation, AssistantMessage, AssistantRun
from backend.routers.assistant import COOKIE_NAME
from backend.services.assistant_loop import Turn
from backend.services.assistant_store import ConversationNotFound


@pytest.mark.parametrize("action", ["get", "continue", "rename", "feedback", "delete", "trace"])
def test_expired_conversations_are_rejected_without_purge(store, action):
    saved = store.begin("owner", None, "Old")
    store.finish(saved, Turn(status="done", text="Old answer"))
    expired = datetime.now(UTC) - timedelta(days=91)
    with store.sessions.begin() as db:
        db.execute(update(AssistantConversation).values(updated_at=expired))
    actions = {
        "get": lambda: store.get_conversation("owner", saved.conversation_id),
        "continue": lambda: store.begin("owner", saved.conversation_id, "Revive"),
        "rename": lambda: store.rename("owner", saved.conversation_id, "Revive"),
        "feedback": lambda: store.feedback("owner", saved.run_id, "good", "Revive"),
        "delete": lambda: store.delete_conversation("owner", saved.conversation_id),
        "trace": lambda: store.show_run(saved.run_id),
    }
    with pytest.raises(ConversationNotFound):
        actions[action]()
    assert store.list_conversations("owner") == []
    assert list(store.runs(365)) == []
    with store.sessions() as db:
        row = db.get(AssistantConversation, saved.conversation_id)
        assert row.updated_at.replace(tzinfo=UTC) == expired
        assert row.question_count == 1


def test_late_completion_and_trace_step_cannot_revive_expired_chat(store):
    saved = store.begin("owner", None, "Old")
    with store.sessions.begin() as db:
        db.execute(update(AssistantConversation).values(updated_at=datetime.now(UTC) - timedelta(days=91)))
    store.record_step(saved, 0, {"kind": "tool", "name": "late"})
    store.finish(saved, Turn(status="done", text="Late answer", steps=[{"kind": "model", "text": "late"}]))
    with store.sessions() as db:
        assert db.get(AssistantMessage, saved.message_id).content == ""
        assert db.get(AssistantRun, saved.run_id).ended_at is None
    assert store.purge(90) == 1
    # Completion released the admission lease even though it could not save.
    store.begin("owner", None, "New chat")


def test_retention_uses_last_activity_and_configured_period(store, monkeypatch):
    monkeypatch.setattr(get_assistant_settings(), "retention_days", 7)
    first = store.begin("owner", None, "Old creation, recent activity")
    store.finish(first, Turn(status="done"))
    second = store.begin("owner", None, "Overdue")
    store.finish(second, Turn(status="done"))
    with store.sessions.begin() as db:
        db.execute(update(AssistantConversation).where(AssistantConversation.id == first.conversation_id)
                   .values(created_at=datetime.now(UTC) - timedelta(days=365)))
        db.execute(update(AssistantConversation).where(AssistantConversation.id == second.conversation_id)
                   .values(updated_at=datetime.now(UTC) - timedelta(days=8)))
    assert [c["id"] for c in store.list_conversations("owner")] == [first.conversation_id]
    store.rename("owner", first.conversation_id, "Still active")
    with pytest.raises(ConversationNotFound):
        store.begin("owner", second.conversation_id, "Revive")


def test_exact_retention_boundary_matches_purge(store, monkeypatch):
    saved = store.begin("owner", None, "At cutoff")
    store.finish(saved, Turn(status="done"))
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=90)
    monkeypatch.setattr(store, "retention_cutoff", lambda: cutoff)
    with store.sessions.begin() as db:
        db.execute(update(AssistantConversation).values(updated_at=cutoff))
    assert store.get_conversation("owner", saved.conversation_id)
    assert store.purge(90, now=now) == 0
    monkeypatch.setattr(store, "retention_cutoff", lambda: cutoff + timedelta(microseconds=1))
    with pytest.raises(ConversationNotFound):
        store.get_conversation("owner", saved.conversation_id)
    assert store.purge(90, now=now + timedelta(microseconds=1)) == 1


@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE", "turn", "feedback"])
def test_expired_http_routes_return_404(client, store, method):
    client.get("/api/v1/assistant/conversations")
    saved = store.begin(client.cookies.get(COOKIE_NAME), None, "Old")
    store.finish(saved, Turn(status="done"))
    with store.sessions.begin() as db:
        db.execute(update(AssistantConversation).values(updated_at=datetime.now(UTC) - timedelta(days=91)))
    url = f"/api/v1/assistant/conversations/{saved.conversation_id}"
    if method == "turn":
        response = client.post("/api/v1/assistant/turn", json={"question": "Revive", "conversation_id": saved.conversation_id})
    elif method == "feedback":
        response = client.post(f"/api/v1/assistant/runs/{saved.run_id}/feedback", json={"rating": "good"})
    else:
        response = client.request(method, url, **({"json": {"title": "Revive"}} if method == "PATCH" else {}))
    assert response.status_code == 404
    assert client.get("/api/v1/assistant/conversations").json() == []
