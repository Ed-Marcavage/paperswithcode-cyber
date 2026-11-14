"""Short database transactions for private assistant conversations."""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete, select, update

from backend.models.database.assistant import AssistantConversation, AssistantMessage, AssistantToolCall

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

    def metadata(self) -> dict:
        return {"conversation_id": self.conversation_id, "message_id": self.message_id,
                "question_count": self.question_count, "question_limit": QUESTION_LIMIT}


class AssistantStore:
    def __init__(self, sessions):
        self.sessions = sessions

    @staticmethod
    def owned(db, conversation_id, visitor):
        row = db.scalar(select(AssistantConversation).where(
            AssistantConversation.id == conversation_id,
            AssistantConversation.visitor_hash == visitor_hash(visitor)))
        if row is None:
            raise ConversationNotFound()
        return row

    def begin(self, visitor: str, conversation_id: str | None, question: str) -> SavedTurn:
        now = datetime.now(UTC)
        with self.sessions.begin() as db:
            if conversation_id is None:
                conversation_id = identifier()
                db.add(AssistantConversation(id=conversation_id, visitor_hash=visitor_hash(visitor),
                       title=" ".join(question.split())[:60], question_count=0,
                       created_at=now, updated_at=now))
                db.flush()
            else:
                self.owned(db, conversation_id, visitor)
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
            history.append({"role": "user", "content": question})
            return SavedTurn(conversation_id, answer_id, count, history)

    def finish(self, saved: SavedTurn, turn):
        with self.sessions.begin() as db:
            message = db.get(AssistantMessage, saved.message_id)
            if message is None:
                return  # The visitor may delete a chat while it is streaming.
            message.content = turn.text
            message.status = turn.status
            db.execute(update(AssistantConversation).where(
                AssistantConversation.id == saved.conversation_id).values(updated_at=datetime.now(UTC)))
            for position, step in enumerate(s for s in turn.steps if s["kind"] == "tool"):
                db.add(AssistantToolCall(id=identifier(), message_id=saved.message_id,
                                        position=position, detail=step))

    def purge(self, retention_days: int, *, now: datetime | None = None) -> int:
        cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
        with self.sessions.begin() as db:
            return db.execute(delete(AssistantConversation).where(
                AssistantConversation.created_at < cutoff)).rowcount


def get_assistant_store() -> AssistantStore:
    from backend.database.assistant import assistant_sessions
    return AssistantStore(assistant_sessions())
