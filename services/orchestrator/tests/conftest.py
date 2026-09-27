from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from greenloop_contracts import MemoryRecord


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, environment="test")


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


@pytest.fixture
def make_record() -> Callable[..., MemoryRecord]:
    def factory(
        content: str = "Prefers morning summaries.",
        *,
        record_id: str = "mem-1",
        principal_id: str = "user-1",
        operation: str = "create",
        supersedes: str | None = None,
        source: str = "user",
    ) -> MemoryRecord:
        return MemoryRecord(
            record_id=record_id,
            principal_id=principal_id,
            scope="private",
            category="user_context",
            content=content,
            provenance={
                "source": source,
                "created_by": principal_id,
                "operation": operation,
                "supersedes": supersedes,
            },
            created_at=datetime(2026, 9, 27, 12, 0, tzinfo=UTC),
        )

    return factory
