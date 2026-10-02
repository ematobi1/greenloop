"""Broker settings, from environment variables and, in development, the repo-root .env.

Same pattern as the orchestrator: secrets are SecretStr so they never appear in repr,
logs or error output; empty values are ignored; real environment variables override
the .env file. GREENLOOP_ENV_FILE points at a different file (Docker, CI); an
explicit path that does not exist is an error rather than a silent fallback.
"""

import os
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from greenloop_contracts.approval import DEFAULT_APPROVAL_TTL, MAX_APPROVAL_TTL

ENV_FILE_VARIABLE = "GREENLOOP_ENV_FILE"
MIN_APPROVAL_TTL_SECONDS = 60
_REPO_ROOT_DEPTH = 3  # services/broker/app/config.py -> repo root


class BrokerSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", env_ignore_empty=True, frozen=True)

    database_url: SecretStr | None = Field(default=None, validation_alias="BROKER_DATABASE_URL")
    approval_ttl_seconds: int = Field(
        default=int(DEFAULT_APPROVAL_TTL.total_seconds()),
        ge=MIN_APPROVAL_TTL_SECONDS,
        le=int(MAX_APPROVAL_TTL.total_seconds()),
        validation_alias="APPROVAL_TTL_SECONDS",
    )

    @property
    def approval_ttl(self) -> timedelta:
        return timedelta(seconds=self.approval_ttl_seconds)


def env_file_path(package_file: Path | str = __file__) -> Path | None:
    """The .env to load: GREENLOOP_ENV_FILE if set, else <repo root>/.env.

    Returns None unless this package sits at services/broker/app inside the repo
    (the Docker image copies only app/ to /srv), so settings then come from the
    environment alone.
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
    ) == ("services", "broker")
    return parents[_REPO_ROOT_DEPTH] / ".env" if in_repo_layout else None


@lru_cache
def get_settings() -> BrokerSettings:
    return BrokerSettings(_env_file=env_file_path())
