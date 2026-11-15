"""Short database transactions for private assistant conversations."""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete, select, update

from backend.assistant_config import get_assistant_settings
from backend.services import assistant_admission
from backend.models.database.assistant import (
    AssistantConversation, AssistantMessage, AssistantToolCall, AssistantRun, AssistantRunStep,
    AssistantProviderLimit,
)
from backend.services.assistant_loop import SYSTEM_PROMPT, PROMPT_VERSION
from backend.services.assistant_provider import USAGE_LIMIT_MESSAGE

QUESTION_LIMIT = 10


def identifier() -> str:
    return str(uuid4())


def visitor_hash(cookie: str) -> str:
    return hashlib.sha256(cookie.encode()).hexdigest()


class ConversationNotFound(Exception):
    pass


class QuestionLimitReached(Exception):
    pass


@dataclass(frozen=True)
class SavedTurn:
    conversation_id: str
    message_id: str
    question_count: int
    history: list[dict]
    run_id: str
    visitor_hash: str

    def metadata(self) -> dict:
        return {"conversation_id": self.conversation_id, "message_id": self.message_id, "run_id": self.run_id,
                "question_count": self.question_count, "question_limit": QUESTION_LIMIT}


class AssistantStore:
    def __init__(self, sessions):
        self.sessions = sessions

    def retention_cutoff(self):
        return datetime.now(UTC) - timedelta(days=get_assistant_settings().retention_days)

    def owned(self, db, conversation_id, visitor, *, lock=False):
        query = select(AssistantConversation).where(
            AssistantConversation.id == conversation_id,
            AssistantConversation.visitor_hash == visitor_hash(visitor),
            AssistantConversation.updated_at >= self.retention_cutoff())
        row = db.scalar(query.with_for_update() if lock else query)
        if row is None:
            raise ConversationNotFound()
        return row

    def begin(self, visitor: str, conversation_id: str | None, question: str, *,
              model: str | None = None, surface: str = "panel", site_path: str = "/",
              analytics_session_id: str | None = None, now: datetime | None = None) -> SavedTurn:
        now = now or datetime.now(UTC)
        run_id = identifier()
        # The title is the first question, cut at a word boundary with an ellipsis to fit 60 characters.
        title = " ".join(question.split())
        if len(title) > 60:
            head = title[:59]
            if title[59] != " " and " " in head:
                head = head.rsplit(" ", 1)[0]
            title = head.rstrip(" ,;:.-") + "…"
        with self.sessions.begin() as db:
            assistant_admission.admit(db, visitor_hash(visitor), run_id, conversation_id is None,
                                      get_assistant_settings(), now)
            if conversation_id is None:
                conversation_id = identifier()
                db.add(AssistantConversation(id=conversation_id, visitor_hash=visitor_hash(visitor),
                       title=title, question_count=0,
                       created_at=now, updated_at=now))
                db.flush()
            else:
                self.owned(db, conversation_id, visitor, lock=True)
            # The conditional increment is atomic across workers and tabs.
            count = db.scalar(update(AssistantConversation).where(
                AssistantConversation.id == conversation_id,
                AssistantConversation.visitor_hash == visitor_hash(visitor),
                AssistantConversation.question_count < QUESTION_LIMIT,
            ).values(question_count=AssistantConversation.question_count + 1, updated_at=now)
                .returning(AssistantConversation.question_count))
            if count is None:
                raise QuestionLimitReached()
            history = [{"role": m.role, "content": m.content} for m in db.scalars(
                select(AssistantMessage).where(AssistantMessage.conversation_id == conversation_id)
                .order_by(AssistantMessage.position)) if m.content]
            answer_id = identifier()
            db.add_all([
                AssistantMessage(id=identifier(), conversation_id=conversation_id,
                                 position=count * 2 - 1, role="user", content=question, status="done", created_at=now),
                AssistantMessage(id=answer_id, conversation_id=conversation_id,
                                 position=count * 2, role="assistant", content="", status="running", created_at=now),
            ])
            db.flush()
            db.add(AssistantRun(id=run_id, conversation_id=conversation_id, message_id=answer_id,
                               question=question, started_at=now, status="running", model=model if model is not None else get_assistant_settings().model,
                               prompt_hash=hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
                               prompt_version=PROMPT_VERSION, surface=surface, site_path=site_path,
                               analytics_session_id=analytics_session_id))
            history.append({"role": "user", "content": question})
            return SavedTurn(conversation_id, answer_id, count, history, run_id, visitor_hash(visitor))

    def release(self, saved: SavedTurn):
        with self.sessions.begin() as db:
            assistant_admission.release(db, saved.run_id)

    def record_step(self, saved: SavedTurn, position: int, step: dict):
        with self.sessions.begin() as db:
            if db.scalar(select(AssistantConversation).where(
                AssistantConversation.id == saved.conversation_id,
                AssistantConversation.updated_at >= self.retention_cutoff()).with_for_update()) is None:
                return
            if db.get(AssistantRun, saved.run_id) is not None:
                db.add(AssistantRunStep(id=identifier(), run_id=saved.run_id, position=position,
                                       kind=step["kind"], detail=step))

    def finish(self, saved: SavedTurn, turn):
        with self.sessions.begin() as db:
            assistant_admission.release(db, saved.run_id)
            if db.scalar(select(AssistantConversation).where(
                AssistantConversation.id == saved.conversation_id,
                AssistantConversation.updated_at >= self.retention_cutoff()).with_for_update()) is None:
                return
            message = db.get(AssistantMessage, saved.message_id)
            if message is None:
                return  # The visitor may delete a chat while it is streaming.
            message.content = turn.text
            message.status = turn.status
            run = db.get(AssistantRun, saved.run_id)
            run.status, run.error, run.ended_at = turn.status, turn.error, datetime.now(UTC)
            positions = set(db.scalars(select(AssistantRunStep.position).where(AssistantRunStep.run_id == saved.run_id)))
            for position, step in enumerate(turn.steps):
                if position not in positions:
                    db.add(AssistantRunStep(id=identifier(), run_id=saved.run_id, position=position,
                                           kind=step["kind"], detail=step))
            db.execute(update(AssistantConversation).where(
                AssistantConversation.id == saved.conversation_id).values(updated_at=datetime.now(UTC)))
            for position, step in enumerate(s for s in turn.steps if s["kind"] == "tool"):
                db.add(AssistantToolCall(id=identifier(), message_id=saved.message_id,
                                        position=position, detail=step))

    def feedback(self, visitor, run_id, rating, note):
        with self.sessions.begin() as db:
            run = db.get(AssistantRun, run_id)
            if run is None:
                raise ConversationNotFound()
            conversation = self.owned(db, run.conversation_id, visitor, lock=True)
            conversation.updated_at = datetime.now(UTC)
            run.feedback_rating, run.feedback_note = rating, note

    @staticmethod
    def summary(row):
        return {"id": row.id, "title": row.title, "updated_at": row.updated_at.replace(tzinfo=UTC).isoformat(),
                "question_count": row.question_count, "question_limit": QUESTION_LIMIT}

    def list_conversations(self, visitor):
        with self.sessions() as db:
            return [self.summary(row) for row in db.scalars(select(AssistantConversation).where(
                AssistantConversation.visitor_hash == visitor_hash(visitor),
                AssistantConversation.updated_at >= self.retention_cutoff())
                .order_by(AssistantConversation.updated_at.desc(), AssistantConversation.id))]

    def get_conversation(self, visitor, conversation_id):
        with self.sessions() as db:
            result = self.summary(self.owned(db, conversation_id, visitor))
            messages = list(db.scalars(select(AssistantMessage).where(
                AssistantMessage.conversation_id == conversation_id).order_by(AssistantMessage.position)))
            runs = {r.message_id: r for r in db.scalars(select(AssistantRun).where(AssistantRun.conversation_id == conversation_id))}
            steps = {}
            for call in db.scalars(select(AssistantToolCall).join(AssistantMessage).where(
                    AssistantMessage.conversation_id == conversation_id).order_by(AssistantToolCall.position)):
                steps.setdefault(call.message_id, []).append(call.detail)
            result["messages"] = [{"id": m.id, "role": m.role, "content": m.content, "status": m.status,
                                   "tool_steps": steps.get(m.id, []),
                                   "run_id": runs[m.id].id if m.id in runs else None,
                                   "error": runs[m.id].error if m.id in runs else None,
                                   "feedback": {"rating": runs[m.id].feedback_rating, "note": runs[m.id].feedback_note}
                                   if m.id in runs else None} for m in messages]
            return result

    def rename(self, visitor, conversation_id, title):
        with self.sessions.begin() as db:
            row = self.owned(db, conversation_id, visitor, lock=True)
            row.title, row.updated_at = title, datetime.now(UTC)
            return self.summary(row)

    def delete_conversation(self, visitor, conversation_id):
        with self.sessions.begin() as db:
            row = self.owned(db, conversation_id, visitor, lock=True)
            db.delete(row)

    @staticmethod
    def trace(db, run):
        steps = [s.detail for s in db.scalars(select(AssistantRunStep).where(
            AssistantRunStep.run_id == run.id).order_by(AssistantRunStep.position))]
        model_steps = [s for s in steps if s["kind"] == "model"]
        tokens = {}
        for key in ("input_tokens", "output_tokens"):
            values = [s.get(key) for s in model_steps]
            tokens[key] = sum(values) if values and all(v is not None for v in values) else None
        answer = db.get(AssistantMessage, run.message_id)
        return {"id": run.id, "conversation_id": run.conversation_id, "question": run.question,
                "answer": answer.content, "started_at": run.started_at.isoformat(),
                "ended_at": run.ended_at.isoformat() if run.ended_at else None,
                "duration_ms": round((run.ended_at - run.started_at).total_seconds() * 1000) if run.ended_at else None,
                "status": run.status, "error": run.error, "model": run.model,
                "prompt_hash": run.prompt_hash, "prompt_version": run.prompt_version,
                "surface": run.surface, "site_path": run.site_path,
                "feedback": {"rating": run.feedback_rating, "note": run.feedback_note},
                "tokens": tokens, "steps": steps}

    def show_run(self, run_id):
        with self.sessions() as db:
            run = db.scalar(select(AssistantRun).join(AssistantConversation).where(
                AssistantRun.id == run_id, AssistantConversation.updated_at >= self.retention_cutoff()))
            if run is None:
                raise ConversationNotFound()
            return self.trace(db, run)

    def runs(self, days):
        cutoff = datetime.now(UTC) - timedelta(days=days)
        with self.sessions() as db:
            rows = db.scalars(select(AssistantRun).join(AssistantConversation).where(
                AssistantRun.started_at >= cutoff, AssistantConversation.updated_at >= self.retention_cutoff())
                              .order_by(AssistantRun.started_at.desc(), AssistantRun.id)
                              .execution_options(yield_per=100))
            for row in rows:
                yield self.trace(db, row)

    def purge(self, retention_days: int, *, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        cutoff = now - timedelta(days=retention_days)
        with self.sessions.begin() as db:
            assistant_admission.purge(db, now)
            return db.execute(delete(AssistantConversation).where(
                AssistantConversation.updated_at < cutoff)).rowcount

    def provider_status(self, *, now=None):
        now = now or datetime.now(UTC)
        with self.sessions() as db:
            reset = db.scalar(select(AssistantProviderLimit.off_until).where(
                AssistantProviderLimit.off_until > now).order_by(AssistantProviderLimit.off_until.desc()).limit(1))
            return {"available": reset is None, "code": "usage_limit" if reset else None,
                    "reason": USAGE_LIMIT_MESSAGE if reset else None,
                    "retry_at": reset.replace(tzinfo=UTC).isoformat() if reset else None}

    def record_provider_limit(self, message, off_until, *, now=None):
        with self.sessions.begin() as db:
            db.add(AssistantProviderLimit(id=identifier(), occurred_at=now or datetime.now(UTC),
                                          off_until=off_until, provider_message=message))
        return self.provider_status(now=now)


def get_assistant_store() -> AssistantStore:
    from backend.database.assistant import assistant_sessions
    return AssistantStore(assistant_sessions())
