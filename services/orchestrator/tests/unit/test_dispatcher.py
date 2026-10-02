import asyncio
import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.agents.reference import EchoReferenceAgent
from app.db.models import AuditRecordRow
from app.memory import execution
from app.memory.execution import ExecutionMemoryStatus
from app.memory.store import MemoryStore
from app.orchestration import dispatcher
from greenloop_contracts import Dispatch, ExecutionStatus


@pytest.fixture
def item(issue_token) -> Dispatch:
    issue_token("user-1")
    return Dispatch(
        dispatch_id=dispatcher.new_dispatch_id(),
        task_id="task-1",
        agent_id="echo-reference-agent",
        principal_id="user-1",
        correlation_id="req-1",
        inputs={"a": 1},
        dispatched_at=datetime.now(UTC),
    )


class _SlowAgent(EchoReferenceAgent):
    async def run(self, item):
        await asyncio.sleep(5)


class _CrashingAgent(EchoReferenceAgent):
    async def run(self, item):
        raise RuntimeError("internal path C:/secret/place")


class _WrongDispatchAgent(EchoReferenceAgent):
    async def run(self, item):
        result = await super().run(item)
        return result.model_copy(update={"dispatch_id": "dsp-someone-else"})


def test_a_timeout_becomes_a_failed_result(item):
    quick = item.model_copy(update={"timeout_ms": 20})
    result = asyncio.run(dispatcher.run(_SlowAgent(), quick))
    assert result.status is ExecutionStatus.FAILED
    assert result.error.code == "AGENT_TIMEOUT"
    assert result.dispatch_id == item.dispatch_id


def test_an_agent_exception_becomes_a_user_safe_failed_result(item):
    result = asyncio.run(dispatcher.run(_CrashingAgent(), item))
    assert result.error.code == "AGENT_FAILED"
    assert "secret" not in result.model_dump_json()


def test_a_result_for_another_dispatch_is_refused(item):
    result = asyncio.run(dispatcher.run(_WrongDispatchAgent(), item))
    assert result.error.code == "AGENT_INVALID_RESULT"
    assert result.dispatch_id == item.dispatch_id


def test_recording_the_same_dispatch_twice_is_already_recorded(item, session_factory):
    result = asyncio.run(dispatcher.run(EchoReferenceAgent(), item))
    with session_factory() as session:
        store = MemoryStore(session, "req-1")
        assert execution.record_execution(store, item, result) is ExecutionMemoryStatus.RECORDED
        session.commit()
        status = execution.record_execution(store, item, result)
        assert status is ExecutionMemoryStatus.ALREADY_RECORDED


def test_the_execution_record_holds_observed_facts_only(item):
    result = asyncio.run(dispatcher.run(EchoReferenceAgent(), item))
    record = execution.execution_record(item, result)
    assert json.loads(record.content) == {
        "dispatch_id": item.dispatch_id,
        "task_id": "task-1",
        "agent_id": "echo-reference-agent",
        "status": "succeeded",
        "error_code": None,
        "started_at": result.started_at.isoformat(),
        "finished_at": result.finished_at.isoformat(),
    }
    assert record.provenance.created_by == "echo-reference-agent"
    assert record.provenance.source_ref == f"dispatch:{item.dispatch_id}"


def test_record_falls_back_to_the_audit_entry_alone(item, session_factory, monkeypatch):
    result = asyncio.run(dispatcher.run(EchoReferenceAgent(), item))

    def broken(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(dispatcher, "record_execution", broken)
    outcome = dispatcher.record(session_factory, item, result)

    assert outcome == dispatcher.RecordOutcome(ExecutionMemoryStatus.FAILED, audited=True)
    with session_factory() as session:
        [audit] = session.scalars(
            select(AuditRecordRow).where(AuditRecordRow.action == "agent.dispatch")
        ).all()
    assert audit.details["execution_memory"] == "failed"


def test_record_never_raises_even_without_a_database(item):
    result = asyncio.run(dispatcher.run(EchoReferenceAgent(), item))

    def no_database():
        raise ConnectionError("down")

    outcome = dispatcher.record(no_database, item, result)
    assert outcome == dispatcher.RecordOutcome(ExecutionMemoryStatus.FAILED, audited=False)
