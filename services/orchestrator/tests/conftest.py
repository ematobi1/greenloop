from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import tokens
from app.core.config import Settings
from app.db.models import Base, PrincipalRow
from app.main import create_app
from greenloop_contracts import AuditOutcome, AuditRecord, MemoryRecord


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, environment="test", allowed_hosts=["testserver"])


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    """In-memory SQLite for fast gate tests. Postgres-only behavior lives in tests/integration."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def client(settings: Settings, session_factory: sessionmaker[Session]) -> TestClient:
    app = create_app(settings)
    app.state.session_factory = session_factory
    return TestClient(app)


@pytest.fixture
def issue_token(session_factory: sessionmaker[Session]) -> Callable[..., str]:
    """Create the principal if needed and return a fresh bearer token for it."""

    def factory(principal_id: str = "user-1") -> str:
        with session_factory() as session:
            if session.get(PrincipalRow, principal_id) is None:
                tokens.create_principal(session, principal_id, principal_id.title())
            _, token = tokens.issue_token(session, principal_id, "test")
            session.commit()
        return token

    return factory


@pytest.fixture
def make_audit() -> Callable[..., AuditRecord]:
    def factory(
        audit_id: str,
        *,
        principal_id: str = "user-1",
        outcome: AuditOutcome = AuditOutcome.ALLOWED,
        correlation_id: str = "req-1",
        minute: int = 0,
    ) -> AuditRecord:
        return AuditRecord(
            audit_id=audit_id,
            principal_id=principal_id,
            actor="orchestrator",
            action="memory.create",
            resource_type="memory_record",
            resource_id="mem-1",
            outcome=outcome,
            correlation_id=correlation_id,
            details={"note": "synthetic"},
            occurred_at=datetime(2026, 9, 28, 12, minute, tzinfo=UTC),
        )

    return factory


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
