import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.assistant_config import get_assistant_settings
from backend.config import get_settings
from backend.main import create_app
from backend.routers import assistant
from backend.services.assistant_loop import Turn, run_turn
from backend.tests.assistant.test_loop import text_chunk


@pytest.fixture
def client(monkeypatch):
    settings = get_assistant_settings()
    monkeypatch.setattr(settings, "enabled", True)
    monkeypatch.setattr(settings, "api_key", SecretStr("fake"))
    monkeypatch.setattr(get_settings(), "discovery_catalog", True)
    return TestClient(create_app())


def test_sse_events_and_validation(client, monkeypatch):
    async def fake(payload, settings):
        for event in [
            {"type": "tool_started", "id": "one", "name": "search_papers"},
            {"type": "tool_finished", "id": "one", "name": "search_papers", "error": False},
            {"type": "text_delta", "text": "Answer"}, {"type": "done", "status": "done"},
        ]:
            yield assistant.sse(event)
    monkeypatch.setattr(assistant, "turn_events", fake)
    response = client.post("/api/v1/assistant/turn", json={"question": "Hello"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-accel-buffering"] == "no"
    assert [json.loads(line[6:])["type"] for line in response.text.splitlines() if line.startswith("data: ")] == [
        "tool_started", "tool_finished", "text_delta", "done"]
    for question in ["x" * 1001, "", "   "]:
        assert client.post("/api/v1/assistant/turn", json={"question": question}).status_code == 422
    assert client.post("/api/v1/assistant/turn", json={"question": "x" * 1000}).status_code == 200


def test_missing_key_503_without_model_call(client, monkeypatch):
    monkeypatch.setattr(get_assistant_settings(), "api_key", SecretStr(""))
    def forbidden(*args):
        pytest.fail("Model called without a key")
    monkeypatch.setattr(assistant, "model_client", forbidden)
    response = client.post("/api/v1/assistant/turn", json={"question": "Hello"})
    assert response.status_code == 503
    assert response.json() == {"detail": "The assistant is not configured yet."}


def test_disabled_routes_are_not_registered(monkeypatch):
    monkeypatch.setattr(get_assistant_settings(), "enabled", False)
    app = create_app()
    assert not any(getattr(route, "path", "").startswith("/api/v1/assistant/") for route in app.routes)


@pytest.mark.parametrize("method", ["POST", "DELETE", "PUT", "PATCH"])
@pytest.mark.parametrize("path", ["/api/v1/papers/1", "/api/v1/assistant-other/turn", "/api%2Fv1/papers/1"])
def test_every_other_api_write_stays_read_only(client, method, path):
    assert client.request(method, path, json={}).status_code == 405


def test_delete_is_admitted_only_inside_assistant(client):
    @client.app.delete("/api/v1/assistant/test-delete")
    def delete():
        return {"deleted": True}
    assert client.delete("/api/v1/assistant/test-delete").json() == {"deleted": True}


@pytest.mark.parametrize("spec", ["2.0", "2.4"])
def test_disconnect_cancels_silent_model_and_closes_stream(spec):
    from openai.types.chat import ChatCompletionChunk

    async def go():
        producing = asyncio.Event()
        closed = asyncio.Event()
        class Stream:
            def __aiter__(self):
                async def items():
                    yield ChatCompletionChunk.model_validate(text_chunk("Partial"))
                    producing.set()
                    await asyncio.Event().wait()
                return items()

            async def close(self):
                closed.set()

        class Model:
            async def create(self, **kwargs):
                return Stream()

        class Catalog:
            async def tools(self):
                return []

        turn = Turn()
        model = SimpleNamespace(chat=SimpleNamespace(completions=Model()))
        async def body():
            async for event in run_turn(model, Catalog(), "fake", [], turn):
                yield assistant.sse(event)
        async def receive():
            await producing.wait()
            return {"type": "http.disconnect"}
        sent = []
        async def send(message):
            sent.append(message)
        await asyncio.wait_for(assistant.AssistantStreamResponse(body())(
            {"type": "http", "asgi": {"spec_version": spec}}, receive, send), 1)
        assert closed.is_set()
        assert turn.status == "cancelled"
        assert turn.text == "Partial"
    asyncio.run(go())
