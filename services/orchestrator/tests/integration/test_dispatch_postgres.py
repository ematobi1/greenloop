"""Dispatch end to end on Postgres: execution memory, audit, idempotent recording."""

import asyncio
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from tests.integration.pg import TEST_DATABASE_URL

from app.agents.reference import EchoReferenceAgent
from app.core import tokens
from app.core.config import Settings
from app.db.models import AuditRecordRow, MemoryRecordRow
from app.main import create_app
from app.memory.execution import ExecutionMemoryStatus, record_execution
from app.orchestration import dispatcher
from greenloop_contracts import Dispatch

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set; Postgres integration skipped"
)


def test_a_dispatch_writes_private_execution_memory_and_an_audit_entry(
    pg_session_factory, principal_id
):
    with pg_session_factory() as session:
        _, token = tokens.issue_token(session, principal_id, "it")
        session.commit()
    app = create_app(Settings(_env_file=None, environment="test", allowed_hosts=["testserver"]))
    app.state.session_factory = pg_session_factory

    response = TestClient(app).post(
        "/v1/dispatches",
        json={"agent_id": "failing-reference-agent", "task_id": "task-it"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.headers["X-Execution-Memory"] == "recorded"
    dispatch_id = response.json()["dispatch_id"]
    with pg_session_factory() as session:
        memory = session.scalars(
            select(MemoryRecordRow).where(MemoryRecordRow.principal_id == principal_id)
        ).one()
        audit = session.scalars(
            select(AuditRecordRow).where(AuditRecordRow.resource_id == dispatch_id)
        ).one()
    assert (memory.scope, memory.confidence) == ("private", "verified")
    assert (audit.action, audit.outcome) == ("agent.dispatch", "failed")


def test_recording_a_dispatch_twice_is_already_recorded_on_postgres(
    pg_session_factory, principal_id
):
    item = Dispatch(
        dispatch_id=dispatcher.new_dispatch_id(),
        task_id="task-it",
        agent_id="echo-reference-agent",
        principal_id=principal_id,
        correlation_id="it",
        dispatched_at=datetime.now(UTC),
    )
    result = asyncio.run(dispatcher.run(EchoReferenceAgent(), item))
    statuses = []
    for _ in range(2):
        with pg_session_factory() as session:
            statuses.append(record_execution(session, "it", item, result))
            session.commit()
    assert statuses == [ExecutionMemoryStatus.RECORDED, ExecutionMemoryStatus.ALREADY_RECORDED]
