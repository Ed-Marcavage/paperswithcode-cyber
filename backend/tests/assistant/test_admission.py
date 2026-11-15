from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from backend.assistant_config import get_assistant_settings
from backend.models.database.assistant import AssistantAdmission, AssistantConversation
from backend.services.assistant_admission import LEASE_SECONDS, VisitorLimitReached
from backend.services.assistant_loop import Turn
from backend.services.assistant_store import ConversationNotFound, visitor_hash


@pytest.mark.parametrize("setting,new_chat,window", [
    ("turns_per_hour", False, 3600), ("turns_per_day", False, 86400),
    ("conversations_per_hour", True, 3600), ("conversations_per_day", True, 86400),
])
def test_rolling_limits_and_exact_reset(store, monkeypatch, setting, new_chat, window):
    settings = get_assistant_settings()
    monkeypatch.setattr(settings, setting, 2)
    now = datetime.now(UTC)
    first = store.begin("owner", None, "First", now=now)
    store.finish(first, Turn(status="done"))
    second = store.begin("owner", None if new_chat else first.conversation_id, "Second", now=now + timedelta(seconds=10))
    store.finish(second, Turn(status="done"))
    with pytest.raises(VisitorLimitReached, match="new chats" if new_chat else "questions"):
        store.begin("owner", None if new_chat else first.conversation_id, "Too soon", now=now + timedelta(seconds=window - 1))
    # Only the oldest request expires; this is a rolling window, not a bucket.
    reset = store.begin("owner", None if new_chat else first.conversation_id, "Reset", now=now + timedelta(seconds=window))
    store.finish(reset, Turn(status="done"))
    with pytest.raises(VisitorLimitReached):
        store.begin("owner", None if new_chat else first.conversation_id, "Still full", now=now + timedelta(seconds=window + 1))
    store.begin("owner", None if new_chat else first.conversation_id, "Second resets", now=now + timedelta(seconds=window + 10))


@pytest.mark.parametrize("status", ["done", "failed", "cancelled"])
def test_one_in_flight_across_conversations_and_release(store, status):
    first = store.begin("owner", None, "One")
    for conversation_id in (None, first.conversation_id):
        with pytest.raises(VisitorLimitReached, match="in progress"):
            store.begin("owner", conversation_id, "Overlap")
    store.begin("someone-else", None, "Independent visitor")
    store.finish(first, Turn(status=status))
    store.begin("owner", None, "Next")


def test_deleted_conversations_do_not_reset_limits_or_inflight(store, monkeypatch):
    monkeypatch.setattr(get_assistant_settings(), "conversations_per_hour", 1)
    saved = store.begin("owner", None, "One")
    store.delete_conversation("owner", saved.conversation_id)
    with pytest.raises(VisitorLimitReached, match="in progress"):
        store.begin("owner", None, "Still streaming")
    store.finish(saved, Turn(status="cancelled"))
    with pytest.raises(VisitorLimitReached, match="new chats"):
        store.begin("owner", None, "Still counted")


def test_crashed_worker_lease_expires_without_old_release_unlocking_new_turn(store):
    now = datetime.now(UTC)
    first = store.begin("owner", None, "One", now=now)
    with pytest.raises(VisitorLimitReached):
        store.begin("owner", None, "Too early", now=now + timedelta(seconds=LEASE_SECONDS - 1))
    store.begin("owner", None, "Recovered", now=now + timedelta(seconds=LEASE_SECONDS))
    store.release(first)
    with pytest.raises(VisitorLimitReached):
        store.begin("owner", None, "Overlap", now=now + timedelta(seconds=LEASE_SECONDS + 1))


def test_failed_begin_rolls_back_admission(store):
    with pytest.raises(ConversationNotFound):
        store.begin("owner", "missing", "Invalid")
    with store.sessions() as db:
        assert db.scalar(select(AssistantAdmission)) is None
    store.begin("owner", None, "Valid")


def test_quota_storage_has_no_raw_identity_and_purges_after_day(store):
    now = datetime.now(UTC)
    store.begin("private-cookie", None, "One", now=now)
    with store.sessions() as db:
        row = db.scalar(select(AssistantAdmission))
        assert row.visitor_hash == visitor_hash("private-cookie")
        assert row.turns == row.conversations == [now.timestamp()]
        assert not {"ip", "ip_address", "user_agent", "cookie"} & set(row.__table__.columns.keys())
    store.purge(90, now=now + timedelta(days=1))
    with store.sessions() as db:
        assert db.scalar(select(AssistantAdmission)) is None
        assert db.scalar(select(AssistantConversation)) is not None


def test_friendly_http_429_before_provider_call(client, store, monkeypatch):
    from backend.routers.assistant import COOKIE_NAME
    client.get("/api/v1/assistant/conversations")
    saved = store.begin(client.cookies.get(COOKIE_NAME), None, "Busy")
    response = client.post("/api/v1/assistant/turn", json={"question": "Overlap"})
    assert response.status_code == 429
    assert response.json() == {"detail": "You already have an answer in progress. Please wait for it to finish."}
    store.release(saved)
    monkeypatch.setattr(get_assistant_settings(), "turns_per_hour", 1)
    response = client.post("/api/v1/assistant/turn", json={"question": "Too many"})
    assert response.status_code == 429
    assert "hour" in response.json()["detail"]


def test_simultaneous_first_requests_across_store_instances(store, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend.models.database.base import Base
    from backend.services.assistant_store import AssistantStore

    engine = create_engine(f"sqlite:///{tmp_path / 'admission.sqlite'}")
    tables = [t for t in Base.metadata.tables.values() if t.name.startswith("assistant_")]
    Base.metadata.create_all(engine, tables=tables)
    barrier = Barrier(2)
    def start():
        independent = AssistantStore(sessionmaker(bind=engine, expire_on_commit=False))
        barrier.wait()
        try:
            independent.begin("same-cookie", None, "Race")
            return "accepted"
        except VisitorLimitReached:
            return "limited"
    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            assert sorted(workers.map(lambda _: start(), range(2))) == ["accepted", "limited"]
    finally:
        engine.dispose()


def test_stream_timeout_releases_admission(client, store, monkeypatch):
    import asyncio
    from backend.routers import assistant

    async def silent(*args):
        yield assistant.sse({"type": "meta"})
        await asyncio.Event().wait()
    monkeypatch.setattr(assistant, "turn_events", silent)
    monkeypatch.setattr(assistant, "TURN_TIMEOUT_SECONDS", .02)
    for _ in range(2):
        assert client.post("/api/v1/assistant/turn", json={"question": "Timeout"}).status_code == 200
    with store.sessions() as db:
        assert db.scalar(select(AssistantAdmission)).active_run_id is None


def test_active_lease_compares_instants_for_aware_timestamps_in_any_zone():
    """PostgreSQL may return the lease in a non-UTC session zone; it must not be reread as UTC."""
    from datetime import UTC, datetime, timedelta, timezone
    from types import SimpleNamespace

    import pytest

    from backend.services import assistant_admission

    now = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
    for offset in (-5, 9):
        zone = timezone(timedelta(hours=offset))
        row = SimpleNamespace(active_until=(now + timedelta(minutes=5)).astimezone(zone), turns=[], conversations=[])
        db = SimpleNamespace(bind=SimpleNamespace(dialect=SimpleNamespace(name="sqlite")), scalar=lambda statement: row)
        with pytest.raises(assistant_admission.VisitorLimitReached):
            assistant_admission.admit(db, "v", "run", True, SimpleNamespace(), now)
