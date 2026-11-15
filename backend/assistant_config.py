"""Environment-only settings for the independent Cyber catalog assistant."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AssistantSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PWC_ASSISTANT_", env_file=None)

    enabled: bool = False
    follow_ups_enabled: bool = True
    history_context: Literal['answers', 'digest', 'full'] = 'full'
    mcp_url: str = "http://mcp:7860/mcp"
    api_key: SecretStr = SecretStr("")
    base_url: str = "https://ollama.com/v1"
    model: str = "deepseek-v4.1-flash:1017"
    retention_days: int = Field(default=90, ge=1)
    turns_per_hour: int = Field(default=30, ge=1)
    turns_per_day: int = Field(default=100, ge=1)
    conversations_per_hour: int = Field(default=10, ge=1)
    conversations_per_day: int = Field(default=30, ge=1)
    store_analytics_session: bool = False
    limit_cooldown_minutes: int = Field(default=30, ge=1)


@lru_cache
def get_assistant_settings() -> AssistantSettings:
    return AssistantSettings()
