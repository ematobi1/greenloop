"""Dispatcher: run one Dispatch on one agent and record what happened.

Tool use inside an agent still goes permission check, approval, broker, audit.

Once an agent has returned, its result is a fact: nothing after that point may hide
or change it. `run` turns every agent failure (exception, timeout, a result for a
different dispatch) into a failed ExecutionResult with a user-safe error, and
`record` never raises: it writes the execution memory record and the audit entry in
one transaction, falls back to the audit entry alone, and reports what it managed.
"""

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy.orm import Session

from app.agents.base import BaseAgent, result_id
from app.audit import recorder
from app.memory.execution import ExecutionMemoryStatus, record_execution
from app.memory.store import MemoryStore
from greenloop_contracts import (
    AuditOutcome,
    AuditRecord,
    Dispatch,
    ErrorDetail,
    ExecutionResult,
    ExecutionStatus,
)

logger = structlog.get_logger(__name__)

DEFAULT_TIMEOUT_MS = 30_000

_OUTCOMES = {
    ExecutionStatus.SUCCEEDED: AuditOutcome.EXECUTED,
    ExecutionStatus.PARTIAL: AuditOutcome.EXECUTED,
    ExecutionStatus.FAILED: AuditOutcome.FAILED,
    ExecutionStatus.CANCELLED: AuditOutcome.FAILED,
    ExecutionStatus.DENIED: AuditOutcome.DENIED,
}


def new_dispatch_id() -> str:
    return f"dsp-{uuid.uuid4().hex}"


def _failed(item: Dispatch, started_at: datetime, code: str, message: str) -> ExecutionResult:
    return ExecutionResult(
        result_id=result_id(item),
        task_id=item.task_id,
        dispatch_id=item.dispatch_id,
        agent_id=item.agent_id,
        status=ExecutionStatus.FAILED,
        error=ErrorDetail(code=code, message=message),
        started_at=started_at,
        finished_at=datetime.now(UTC),
    )


async def run(agent: BaseAgent, item: Dispatch) -> ExecutionResult:
    started_at = datetime.now(UTC)
    timeout_seconds = (item.timeout_ms or DEFAULT_TIMEOUT_MS) / 1000
    try:
        result = await asyncio.wait_for(agent.run(item), timeout_seconds)
    except TimeoutError:
        return _failed(item, started_at, "AGENT_TIMEOUT", "The agent did not finish in time.")
    except Exception:
        logger.error("agent_run_failed", agent_id=item.agent_id, exc_info=True)
        return _failed(item, started_at, "AGENT_FAILED", "The agent failed.")
    if (result.dispatch_id, result.task_id, result.agent_id) != (
        item.dispatch_id,
        item.task_id,
        item.agent_id,
    ):
        logger.error("agent_result_mismatch", agent_id=item.agent_id)
        return _failed(
            item, started_at, "AGENT_INVALID_RESULT", "The agent returned an invalid result."
        )
    return result


@dataclass(frozen=True)
class RecordOutcome:
    memory: ExecutionMemoryStatus
    audited: bool


def _audit(item: Dispatch, result: ExecutionResult, memory: ExecutionMemoryStatus) -> AuditRecord:
    return AuditRecord(
        audit_id=f"aud-{item.dispatch_id.removeprefix('dsp-')}",
        principal_id=item.principal_id,
        actor=item.principal_id,
        action="agent.dispatch",
        resource_type="dispatch",
        resource_id=item.dispatch_id,
        outcome=_OUTCOMES[result.status],
        correlation_id=item.correlation_id,
        details={
            "agent_id": item.agent_id,
            "task_id": item.task_id,
            "status": result.status.value,
            "error_code": result.error.code if result.error else None,
            "execution_memory": memory.value,
        },
    )


def record(
    session_factory: Callable[[], Session], item: Dispatch, result: ExecutionResult
) -> RecordOutcome:
    try:
        with session_factory() as session:
            memory = record_execution(MemoryStore(session, item.correlation_id), item, result)
            recorder.record(session, _audit(item, result, memory))
            session.commit()
        return RecordOutcome(memory, audited=True)
    except Exception:
        logger.error("dispatch_record_failed", dispatch_id=item.dispatch_id, exc_info=True)
    try:
        with session_factory() as session:
            recorder.record(session, _audit(item, result, ExecutionMemoryStatus.FAILED))
            session.commit()
        return RecordOutcome(ExecutionMemoryStatus.FAILED, audited=True)
    except Exception:
        logger.error("dispatch_audit_failed", dispatch_id=item.dispatch_id, exc_info=True)
        return RecordOutcome(ExecutionMemoryStatus.FAILED, audited=False)


def record_refusal(
    session_factory: Callable[[], Session],
    principal_id: str,
    correlation_id: str,
    agent_id: str,
    reason: str,
) -> None:
    """Audit a dispatch refused before any agent ran. Raises on database errors: nothing
    has happened yet, so the request can fail."""
    with session_factory() as session:
        recorder.record(
            session,
            AuditRecord(
                audit_id=f"aud-{uuid.uuid4().hex}",
                principal_id=principal_id,
                actor=principal_id,
                action="agent.dispatch",
                resource_type="agent",
                resource_id=agent_id,
                outcome=AuditOutcome.DENIED,
                correlation_id=correlation_id,
                details={"reason": reason},
            ),
        )
        session.commit()
