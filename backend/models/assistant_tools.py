"""Arguments for assistant-only catalog reads; no public API route."""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FindPostsArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    query: str = Field(default="", max_length=200, description="Keywords across title and tldr, with English stemming; sparse all-word matches fall back to ranked any-word matches. Omit when topic/type suffice.")
    topic: str = Field(default="", max_length=100, description="One catalog topic slug, or omit.")
    subtopic: str = Field(default="", max_length=100, description="One exact reviewed subtopic, case-insensitive.")
    post_type: str = Field(default="", max_length=64, description="Reviewed type, e.g. engineering-practice, benchmark-or-evaluation, malware-or-threat-intel, detection-engineering, tool-or-release.")
    tier: Literal["", "featured", "catalog"] = ""
    publisher: str = Field(default="", max_length=160, description="Exact displayed publisher name, case-insensitive.")
    min_agent_relevance: int = Field(default=3, ge=0, le=4, description="Use 0 for general vulnerabilities, malware or threat reporting. An omitted default is removed for sparse text searches; an explicit value is always kept.")
    harness_engineering: bool | None = Field(default=None, description="True requires agent harness engineering; false excludes it; omitted allows both.")
    published_after: date | None = Field(default=None, description="Exclusive publication-date lower bound, YYYY-MM-DD.")
    sort: Literal["score", "recent", "score_recent"] = "score"
    limit: int = Field(default=10, ge=1, le=10)

    @field_validator("published_after", mode="before")
    @classmethod
    def parse_date(cls, value):
        return date.fromisoformat(value) if isinstance(value, str) else value


class FollowUpPostCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    query: str = Field(default="", max_length=200)
    topic: str = Field(default="", max_length=100)
    subtopic: str = Field(default="", max_length=100)
    post_type: str = Field(default="", max_length=64)
    publisher: str = Field(default="", max_length=160)
    harness_engineering: bool | None = None
    min_agent_relevance: int = Field(default=3, ge=0, le=4)
    published_after: date | None = None

    _parse_date = field_validator("published_after", mode="before")(FindPostsArguments.parse_date.__func__)


class FollowUpCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=120, description="A self-contained question the visitor would type; no implied topic from this turn.")
    check: FollowUpPostCheck | Annotated[str, Field(min_length=1, max_length=200)] = Field(description="Post filters, or a short paper search phrase. Checks must find several useful unseen works.")

    @field_validator("check")
    @classmethod
    def bounded_phrase(cls, value):
        if isinstance(value, str) and not 1 <= len(value.strip()) <= 200:
            raise ValueError("Use a paper search phrase of 1–200 characters.")
        return value


class SuggestFollowUpsArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    candidates: list[FollowUpCandidate] = Field(max_length=4)
