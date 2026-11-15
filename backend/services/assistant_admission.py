"""Atomic rolling quotas and a bounded in-flight lease, keyed only by cookie hash."""

from datetime import UTC, timedelta

from sqlalchemy import delete, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from backend.models.database.assistant import AssistantAdmission

# HTTP streams cancel provider work after 120 seconds. A longer lease recovers
# after a crashed worker without admitting overlapping live provider turns.
TURN_TIMEOUT_SECONDS = 120
LEASE_SECONDS = 300


class VisitorLimitReached(Exception):
    pass


def admit(db, visitor_hash, run_id, new_conversation, settings, now):
    insert = sqlite_insert if db.bind.dialect.name == "sqlite" else pg_insert
    # A no-op UPSERT locks even a brand-new visitor atomically across workers.
    # Both PostgreSQL and SQLite serialize writers before reading the counters.
    row = db.scalar(insert(AssistantAdmission).values(
        visitor_hash=visitor_hash, turns=[], conversations=[], updated_at=now,
    ).on_conflict_do_update(
        index_elements=[AssistantAdmission.visitor_hash], set_={"visitor_hash": visitor_hash},
    ).returning(AssistantAdmission))
    timestamp = now.timestamp()
    if row.active_until and row.active_until.replace(tzinfo=UTC).timestamp() > timestamp:
        raise VisitorLimitReached("You already have an answer in progress. Please wait for it to finish.")
    turns = [t for t in row.turns if t > timestamp - 86400]
    conversations = [t for t in row.conversations if t > timestamp - 86400]
    for times, hourly, daily, label in (
        (turns, settings.turns_per_hour, settings.turns_per_day, "questions"),
        (conversations, settings.conversations_per_hour, settings.conversations_per_day, "new chats"),
    ):
        if label == "new chats" and not new_conversation:
            continue
        if sum(t > timestamp - 3600 for t in times) >= hourly:
            raise VisitorLimitReached(f"You've sent plenty of {label} this hour. Please try again in an hour.")
        if len(times) >= daily:
            raise VisitorLimitReached(f"You've reached today's limit for {label}. Please try again tomorrow.")
    row.turns = [*turns, timestamp]
    row.conversations = [*conversations, timestamp] if new_conversation else conversations
    row.active_run_id = run_id
    row.active_until = now + timedelta(seconds=LEASE_SECONDS)
    row.updated_at = now


def release(db, run_id):
    db.execute(update(AssistantAdmission).where(AssistantAdmission.active_run_id == run_id)
               .values(active_run_id=None, active_until=None))


def purge(db, now):
    db.execute(delete(AssistantAdmission).where(AssistantAdmission.updated_at <= now - timedelta(days=1)))
