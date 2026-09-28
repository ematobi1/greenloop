"""Settings loaded from environment variables (and a local .env in development).

Secrets are SecretStr so they never appear in repr, logs or error output. Empty
environment values are ignored, so a blank line in .env falls back to the default.
"""

from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    environment: Literal["dev", "test", "prod"] = "dev"
    version: str = "0.1.0"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    allowed_hosts: list[str] = ["127.0.0.1", "localhost"]
    cors_origins: list[str] = ["http://127.0.0.1:3000", "http://localhost:3000"]

    database_url: SecretStr | None = None
    broker_url: str | None = None

    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-opus-5-5"
    elevenlabs_api_key: SecretStr | None = None

    def secret_values(self) -> list[str]:
        """Every configured secret value, for exact-match redaction."""
        values = [
            field.get_secret_value()
            for field in (getattr(self, name) for name in type(self).model_fields)
            if isinstance(field, SecretStr) and field.get_secret_value()
        ]
        if self.database_url is not None:
            password = urlsplit(self.database_url.get_secret_value()).password
            if password:
                values.append(password)
        return values


@lru_cache
def get_settings() -> Settings:
    return Settings()
