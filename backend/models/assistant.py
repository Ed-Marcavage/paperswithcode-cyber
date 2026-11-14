"""Public API models for the anonymous catalog assistant."""

from pydantic import BaseModel, Field, field_validator
from uuid import UUID
from typing import Literal
from urllib.parse import urlsplit


class AssistantTurnRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    conversation_id: UUID | None = None
    surface: Literal["landing", "panel", "chat_page"] = "panel"
    site_path: str = Field(default="/", max_length=500)
    analytics_session_id: UUID | None = None

    @field_validator("site_path")
    @classmethod
    def pathname_only(cls, value: str) -> str:
        if not value.startswith("/") or value.startswith("//") or "\\" in value:
            raise ValueError("Expected a site path.")
        return urlsplit(value).path  # Queries/fragments can contain private text.

    @field_validator("question")
    @classmethod
    def nonblank_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Please enter a question.")
        return value


class AssistantFeedbackRequest(BaseModel):
    rating: Literal["good", "bad"]
    note: str = Field(default="", max_length=500)
