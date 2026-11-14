"""Anonymous Cyber assistant history; separate from upstream chat tables."""

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint

from backend.models.database.base import Base


class AssistantConversation(Base):
    __tablename__ = "assistant_conversations"
    __table_args__ = (CheckConstraint("question_count BETWEEN 0 AND 10"),)

    id = Column(String(36), primary_key=True)
    visitor_hash = Column(String(64), nullable=False, index=True)
    title = Column(String(60), nullable=False)
    question_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class AssistantMessage(Base):
    __tablename__ = "assistant_messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "position"),
        CheckConstraint("role IN ('user', 'assistant')"),
    )

    id = Column(String(36), primary_key=True)
    conversation_id = Column(String(36), ForeignKey("assistant_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    position = Column(Integer, nullable=False)
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False, default="")
    status = Column(String(24), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class AssistantToolCall(Base):
    __tablename__ = "assistant_tool_calls"
    __table_args__ = (UniqueConstraint("message_id", "position"),)

    id = Column(String(36), primary_key=True)
    message_id = Column(String(36), ForeignKey("assistant_messages.id", ondelete="CASCADE"), nullable=False, index=True)
    position = Column(Integer, nullable=False)
    detail = Column(JSON, nullable=False)


class AssistantRun(Base):
    __tablename__ = "assistant_runs"

    id = Column(String(36), primary_key=True)
    conversation_id = Column(String(36), ForeignKey("assistant_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    message_id = Column(String(36), ForeignKey("assistant_messages.id", ondelete="CASCADE"), nullable=False, unique=True)
    question = Column(Text, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False, index=True)
    ended_at = Column(DateTime(timezone=True))
    status = Column(String(24), nullable=False)
    error = Column(Text)
    model = Column(String(200), nullable=False)
    prompt_hash = Column(String(64), nullable=False)
    prompt_version = Column(String(80), nullable=False)
    surface = Column(String(20), nullable=False)
    site_path = Column(String(500), nullable=False)
    analytics_session_id = Column(String(36))
    feedback_rating = Column(String(8))
    feedback_note = Column(String(500))


class AssistantRunStep(Base):
    __tablename__ = "assistant_run_steps"
    __table_args__ = (UniqueConstraint("run_id", "position"),)

    id = Column(String(36), primary_key=True)
    run_id = Column(String(36), ForeignKey("assistant_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    position = Column(Integer, nullable=False)
    kind = Column(String(16), nullable=False)
    detail = Column(JSON, nullable=False)
