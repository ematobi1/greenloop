"""Settings loaded from environment variables (and a local .env in development).

Secrets are SecretStr so they never appear in repr, logs or error output.
"""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["dev", "test", "prod"] = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    database_url: SecretStr | None = None
    broker_url: str | None = None

    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-opus-5-5"
    elevenlabs_api_key: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
