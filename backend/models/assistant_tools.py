"""Arguments for assistant-only catalog reads; no public API route."""

from datetime import date
from typing import Literal

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


class FollowUpSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=120)
    support: str = Field(min_length=1, max_length=500, description="One short sentence naming what the search showed; trace only.")


class SubmitFollowUpsArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    follow_ups: list[FollowUpSubmission] = Field(max_length=3)
