from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from backend.models.database.assistant import (
    AssistantConversation, AssistantMessage, AssistantToolCall, AssistantRun, AssistantRunStep,
)
from backend.routers.assistant import COOKIE_NAME
from backend.services.assistant_loop import Turn


def seed(client, store):
    assert client.get("/api/v1/assistant/conversations").json() == []
    visitor = client.cookies.get(COOKIE_NAME)
    first = store.begin(visitor, None, "First question " * 8)
    store.finish(first, Turn(text="Answer", status="done", steps=[{
        "kind": "tool", "name": "search_papers", "result": '{"url":"/paper/one"}'}]))
    second = store.begin(visitor, None, "Second question")
    with store.sessions.begin() as db:
        db.execute(update(AssistantConversation).where(AssistantConversation.id == first.conversation_id)
                   .values(updated_at=datetime.now(UTC) - timedelta(days=1)))
    return first, second


def test_list_open_rename_and_delete(client, store):
    first, second = seed(client, store)
    response = client.get("/api/v1/assistant/conversations")
    assert response.headers["cache-control"] == "no-store"
    assert [row["id"] for row in response.json()] == [second.conversation_id, first.conversation_id]
    # Long first questions are cut at a word boundary with an ellipsis, within 60 characters.
    assert response.json()[1]["title"] == "First question First question First question First question…"
    assert response.json()[0]["title"] == "Second question"
    url = "/api/v1/assistant/conversations/" + first.conversation_id
    opened = client.get(url).json()
    assert opened["messages"][1]["tool_steps"][0]["name"] == "search_papers"
    assert opened["messages"][1]["run_id"] == first.run_id
    old_time = opened["updated_at"]
    renamed = client.patch(url, json={"title": "My research"})
    assert renamed.status_code == 200 and renamed.json()["title"] == "My research"
    assert renamed.json()["updated_at"] > old_time
    assert client.get("/api/v1/assistant/conversations").json()[0]["id"] == first.conversation_id
    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404
    # A completion arriving after deletion must not recreate history or traces.
    store.record_step(first, 2, {"kind": "model", "text": "Late"})
    store.finish(first, Turn(text="Late", status="done"))
    with store.sessions() as db:
        for model in (AssistantToolCall, AssistantRunStep):
            assert db.scalar(select(func.count()).select_from(model)) == 0
        assert db.get(AssistantRun, first.run_id) is None
        assert db.get(AssistantMessage, first.message_id) is None


@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE"])
def test_other_browser_gets_404_for_every_conversation_route(client, store, method):
    first, _ = seed(client, store)
    other = TestClient(client.app, headers={"Origin": "http://testserver"})
    response = other.request(method, f"/api/v1/assistant/conversations/{first.conversation_id}",
                             **({"json": {"title": "Stolen"}} if method == "PATCH" else {}))
    assert response.status_code == 404
    assert other.get("/api/v1/assistant/conversations").json() == []


def test_history_stays_readable_during_provider_cooldown_and_bad_titles_fail(client, store):
    first, _ = seed(client, store)
    store.record_provider_limit("quota", datetime.now(UTC) + timedelta(minutes=30))
    url = f"/api/v1/assistant/conversations/{first.conversation_id}"
    assert client.get(url).status_code == 200
    assert client.get("/api/v1/assistant/conversations").status_code == 200
    for title in ("", "   ", "x" * 61):
        assert client.patch(url, json={"title": title}).status_code == 422


def test_titles_cut_at_a_word_boundary(client, store):
    assert client.get("/api/v1/assistant/conversations").json() == []
    visitor = client.cookies.get(COOKIE_NAME)
    cases = {
        "Compare the industry posts on agent sandboxing in a table: publisher, approach, escape rate":
            "Compare the industry posts on agent sandboxing in a table…",
        "Which posts show cutting-edge harness design for automated pentesting?":
            "Which posts show cutting-edge harness design for automated…",
        "x" * 70: "x" * 59 + "…",
        "  Short   question  ": "Short question",
        "a" * 60: "a" * 60,
    }
    for question, title in cases.items():
        saved = store.begin(visitor, None, question)
        with store.sessions() as db:
            stored = db.get(AssistantConversation, saved.conversation_id).title
        assert stored == title and len(stored) <= 60

