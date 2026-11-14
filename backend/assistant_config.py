"""Environment-only settings for the independent Cyber catalog assistant."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class AssistantSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PWC_ASSISTANT_", env_file=None)

    mcp_url: str = "http://mcp:7860/mcp"


@lru_cache
def get_assistant_settings() -> AssistantSettings:
    return AssistantSettings()
