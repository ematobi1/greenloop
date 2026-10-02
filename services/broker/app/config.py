"""Broker settings, read from environment variables (compose passes .env through).

The database URL is a SecretStr so it never appears in repr, logs or error output.
"""

import os
from datetime import timedelta

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from greenloop_contracts.approval import DEFAULT_APPROVAL_TTL, MAX_APPROVAL_TTL

MIN_APPROVAL_TTL_SECONDS = 60


class BrokerSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    database_url: SecretStr | None = None
    approval_ttl_seconds: int = Field(
        default=int(DEFAULT_APPROVAL_TTL.total_seconds()),
        ge=MIN_APPROVAL_TTL_SECONDS,
        le=int(MAX_APPROVAL_TTL.total_seconds()),
    )

    @property
    def approval_ttl(self) -> timedelta:
        return timedelta(seconds=self.approval_ttl_seconds)

    @classmethod
    def from_env(cls) -> "BrokerSettings":
        values: dict[str, object] = {}
        if url := os.environ.get("BROKER_DATABASE_URL", "").strip():
            values["database_url"] = url
        if ttl := os.environ.get("APPROVAL_TTL_SECONDS", "").strip():
            values["approval_ttl_seconds"] = ttl
        return cls.model_validate(values)
