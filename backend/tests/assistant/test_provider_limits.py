import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from openai import RateLimitError
from sqlalchemy import select, update

from backend.assistant_config import AssistantSettings
from backend.models.database.assistant import AssistantProviderLimit
from backend.services.assistant_provider import (
    is_busy, is_usage_limit, quota_reset, reset_from_error, safe_provider_message, USAGE_LIMIT_MESSAGE,
)
from backend.tests.assistant.test_traces import fake_services
from backend.tests.assistant.test_loop import text_chunk, tool_chunk


QUOTA = "you (account) have reached your session usage limit, upgrade for higher limits: https://ollama.com/upgrade"
BUSY = "too many concurrent requests"


def provider_error(message, headers=None):
    response = httpx.Response(429, request=httpx.Request("POST", "https://ollama.com/v1/chat/completions"), headers=headers)
    return RateLimitError(message, response=response, body={"error": message})


@pytest.mark.parametrize("message", [QUOTA, QUOTA.replace("session", "weekly")])
def test_real_error_phrases_are_quota_not_busy(message):
    error = provider_error(message)
    assert is_usage_limit(error) and not is_busy(error)
    assert is_busy(provider_error(BUSY)) and not is_usage_limit(provider_error(BUSY))


def test_reset_from_error_and_live_balance_schema():
    now = datetime(2026, 11, 14, tzinfo=UTC)
    assert reset_from_error(provider_error(QUOTA, {"Retry-After": "60"}), now) == now + timedelta(minutes=1)
    expected = now + timedelta(hours=2)
    async def go():
        def balance(request):
            assert str(request.url) == "https://ollama.com/api/balance"
            assert request.headers["authorization"] == "Bearer fake"
            return httpx.Response(200, json={"included": {"session": {
                "remaining_percent": 0, "resets_at": expected.isoformat()}}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(balance)) as client:
            return await quota_reset(provider_error(QUOTA), AssistantSettings(api_key="fake"), client=client, now=now)
    assert asyncio.run(go()) == expected


@pytest.mark.parametrize("body", [{}, {"included": None}, {"included": {"session": {"resets_at": "not-a-date"}}}])
def test_unavailable_reset_falls_back_to_cooldown(body):
    now = datetime(2026, 11, 14, tzinfo=UTC)
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body))) as client:
            return await quota_reset(provider_error(QUOTA), AssistantSettings(api_key="fake"), client=client, now=now)
    assert asyncio.run(go()) == now + timedelta(minutes=30)


def test_midturn_limit_keeps_notes_only_in_trace_and_disables_without_more_calls(client, store, monkeypatch):
    services = fake_services(monkeypatch, [[text_chunk("Partial"), tool_chunk()],
        httpx.Response(429, json={"error": {"message": QUOTA}})])
    response = client.post("/api/v1/assistant/turn", json={"question": "Find something"})
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert events[-1]["code"] == "usage_limit" and events[-1]["message"] == USAGE_LIMIT_MESSAGE
    run = store.show_run(events[0]["run_id"])
    assert run["status"] == "provider_limit" and run["answer"] == ""
    assert run["steps"][0]["text"] == "Partial"
    assert events[1] == {"type": "working_note", "text": "Partial"}
    status = client.get("/api/v1/assistant/status").json()
    assert not status["available"] and status["retry_at"]
    assert status["reason"] == events[-1]["message"]
    blocked = client.post("/api/v1/assistant/turn", json={"question": "Try again"})
    assert blocked.status_code == 503 and blocked.json()["detail"] == status
    assert len(services.model_requests) == 2
    with store.sessions() as db:
        event = db.scalar(select(AssistantProviderLimit))
        assert "session usage limit" in event.provider_message
        assert "(account)" not in event.provider_message


def test_automatic_return_and_repeated_quota_extends_off_until(client, store, monkeypatch):
    past = datetime.now(UTC) - timedelta(seconds=1)
    store.record_provider_limit("previous limit", past)
    assert client.get("/api/v1/assistant/status").json()["available"]
    services = fake_services(monkeypatch, [httpx.Response(429, json={"error": QUOTA})])
    client.post("/api/v1/assistant/turn", json={"question": "Retry after reset"})
    assert len(services.model_requests) == 1
    assert not client.get("/api/v1/assistant/status").json()["available"]
    with store.sessions.begin() as db:
        assert len(list(db.scalars(select(AssistantProviderLimit)))) == 2
        db.execute(update(AssistantProviderLimit).values(off_until=past))
    fake_services(monkeypatch, [[text_chunk("Back again")]])
    assert "Back again" in client.post("/api/v1/assistant/turn", json={"question": "Try now"}).text
    assert client.get("/api/v1/assistant/status").json()["available"]


def test_busy_retry_is_brief_recorded_and_does_not_disable(client, store, monkeypatch):
    services = fake_services(monkeypatch, [httpx.Response(429, json={"error": BUSY}), [text_chunk("Recovered")]])
    response = client.post("/api/v1/assistant/turn", json={"question": "Hello"})
    assert "Recovered" in response.text
    assert len(services.model_requests) == 2
    assert client.get("/api/v1/assistant/status").json()["available"]
    run = next(store.runs(1))
    assert [s["status"] for s in run["steps"]] == ["failed", "done"]


def test_streamed_usage_limit_is_also_classified(client, store, monkeypatch):
    fake_services(monkeypatch, [[text_chunk("Partial"), {"error": {"message": QUOTA}}]])
    response = client.post("/api/v1/assistant/turn", json={"question": "Hi"})
    assert '"type":"text_delta"' in response.text.replace(" ", "")
    assert "usage_limit" in response.text
    assert next(store.runs(1))["answer"] == "Partial"
    assert not store.provider_status()["available"]


def test_provider_message_redacts_credential():
    assert "secret-key" not in safe_provider_message(provider_error(QUOTA + " secret-key"), "secret-key")
