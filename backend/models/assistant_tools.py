"""Assistant tool arguments; post-search arguments are shared with the public API."""

import unicodedata

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.models.catalog_posts import FindPostsArguments

__all__ = ["FindPostsArguments", "FollowUpSubmission", "SubmitFollowUpsArguments"]


class FollowUpSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=120)
    support: str = Field(min_length=1, max_length=500, description="One short sentence naming what the search showed; trace only.")

    @field_validator("question")
    @classmethod
    def plain_text_question(cls, value: str) -> str:
        # A suggestion is shown as a button and later sent as the visitor's question:
        # no control, formatting or direction-override characters.
        if any(unicodedata.category(ch) in {"Cc", "Cf", "Co", "Cs", "Zl", "Zp"} for ch in value):
            raise ValueError("question must be plain text without control or formatting characters")
        return value


class SubmitFollowUpsArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    follow_ups: list[FollowUpSubmission] = Field(max_length=3)
