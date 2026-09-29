from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import tokens
from app.core.config import Settings
from app.db.models import Base, PrincipalRole, PrincipalRow
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

    # pysqlite skips BEGIN, which breaks SAVEPOINT; take over transaction control.
    @event.listens_for(engine, "connect")
    def _disable_pysqlite_transactions(dbapi_connection, _record):
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _begin(connection):
        connection.exec_driver_sql("BEGIN")

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

    def factory(principal_id: str = "user-1", role: PrincipalRole = PrincipalRole.USER) -> str:
        with session_factory() as session:
            if session.get(PrincipalRow, principal_id) is None:
                tokens.create_principal(session, principal_id, principal_id.title(), role)
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


class FakeProvider:
    """Scripted ModelProvider: yields `chunks`, then Done, or raises `error` after
    `error_after` chunks. `hang` stalls before the first chunk. Records every request."""

    def __init__(
        self,
        chunks=("Hello", " there."),
        *,
        error=None,
        error_after=None,
        hang=False,
        usage=(12, 3),
    ):
        from app.ai.providers.base import ProviderConfig

        self.config = ProviderConfig(name="fake", model="fake-1", timeout_seconds=5, max_retries=0)
        self.chunks = list(chunks)
        self.error = error
        self.error_after = error_after
        self.hang = hang
        self.usage = usage
        self.requests = []

    async def stream(self, request):
        import asyncio

        from app.ai.providers.base import Done, TextDelta

        self.requests.append(request)
        if self.hang:
            await asyncio.Event().wait()
        for index, chunk in enumerate(self.chunks):
            if self.error is not None and index == self.error_after:
                raise self.error
            yield TextDelta(chunk)
            await asyncio.sleep(0)
        if self.error is not None:
            raise self.error
        yield Done(
            stop_reason="end_turn",
            input_tokens=self.usage[0],
            output_tokens=self.usage[1],
            request_id="req_fake",
        )


@pytest.fixture
def fake_provider():
    return FakeProvider()


@pytest.fixture
def use_provider(client):
    """Install providers on the test app: use_provider(FakeProvider(...), name="fake")."""
    from app.ai.providers.registry import ProviderRegistry

    def install(provider, name="fake"):
        client.app.state.provider_registry = ProviderRegistry({name: provider}, name)
        return provider

    return install
