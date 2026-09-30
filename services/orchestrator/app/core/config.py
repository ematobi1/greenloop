"""Settings loaded from environment variables and, in development, the repo-root .env.

Secrets are SecretStr so they never appear in repr, logs or error output. Empty
environment values are ignored, so a blank line in .env falls back to the default.
Real environment variables always override values from the .env file.

The .env file is found relative to this package, not the working directory, so
uvicorn, alembic and the CLI all read the same file from services/orchestrator.
GREENLOOP_ENV_FILE points at a different file (Docker, CI); an explicit path that
does not exist is an error rather than a silent fallback.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE_VARIABLE = "GREENLOOP_ENV_FILE"
_REPO_ROOT_DEPTH = 4  # services/orchestrator/app/core/config.py -> repo root


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", env_ignore_empty=True)

    environment: Literal["dev", "test", "prod"] = "dev"
    version: str = "0.1.0"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    allowed_hosts: list[str] = ["127.0.0.1", "localhost"]
    cors_origins: list[str] = ["http://127.0.0.1:3000", "http://localhost:3000"]

    database_url: SecretStr | None = None
    broker_url: str | None = None

    anthropic_api_key: SecretStr | None = None
    chat_model: str = Field(
        default="claude-opus-5-5",
        validation_alias="GREENLOOP_CHAT_MODEL",
        max_length=128,
        pattern=r"^[A-Za-z0-9._:/-]+$",
    )
    anthropic_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str | None = None
    elevenlabs_api_key: SecretStr | None = None

    ai_default_provider: Literal["anthropic", "ollama"] = "anthropic"
    ai_timeout_seconds: float = Field(default=120.0, gt=0, le=600)
    ai_max_retries: int = Field(default=2, ge=0, le=5)
    ai_max_output_tokens: int = Field(default=16000, ge=256, le=128000)
    ai_context_token_limit: int = Field(default=150000, ge=4000)
    ai_history_message_limit: int = Field(default=40, ge=0, le=500)
    ai_max_message_chars: int = Field(default=20000, ge=1, le=200000)
    ai_memory_record_limit: int = Field(default=20, ge=0, le=100)

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


def env_file_path(package_file: Path | str = __file__) -> Path | None:
    """The .env to load: GREENLOOP_ENV_FILE if set, else <repo root>/.env.

    Returns None unless this package sits at services/orchestrator/app inside the
    repo (the Docker image copies only app/ to /srv), so settings then come from
    the environment alone.
    """
    override = os.environ.get(ENV_FILE_VARIABLE, "").strip()
    if override:
        path = Path(override)
        if not path.is_file():
            raise FileNotFoundError(f"{ENV_FILE_VARIABLE} does not name a file: {path}")
        return path
    parents = Path(package_file).resolve().parents
    in_repo_layout = len(parents) > _REPO_ROOT_DEPTH and (
        parents[_REPO_ROOT_DEPTH - 1].name,
        parents[_REPO_ROOT_DEPTH - 2].name,
    ) == ("services", "orchestrator")
    return parents[_REPO_ROOT_DEPTH] / ".env" if in_repo_layout else None


@lru_cache
def get_settings() -> Settings:
    return Settings(_env_file=env_file_path())
