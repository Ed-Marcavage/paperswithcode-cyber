"""Public API models for the anonymous catalog assistant."""

from pydantic import BaseModel, Field, field_validator
from uuid import UUID


class AssistantTurnRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    conversation_id: UUID | None = None

    @field_validator("question")
    @classmethod
    def nonblank_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Please enter a question.")
        return value
