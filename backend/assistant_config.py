"""Environment-only settings for the independent Cyber catalog assistant."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AssistantSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PWC_ASSISTANT_", env_file=None)

    enabled: bool = False
    mcp_url: str = "http://mcp:7860/mcp"
    api_key: SecretStr = SecretStr("")
    base_url: str = "https://ollama.com/v1"
    model: str = "glm-5.3-flash"


@lru_cache
def get_assistant_settings() -> AssistantSettings:
    return AssistantSettings()
