"""Dispatcher: run one Dispatch on one agent and record what happened.

`dispatch` is the single entry point (the API and, later, the planner): it resolves
the agent, refuses unknown, inactive and not-permitted ones with an audit entry, builds the Dispatch
server-side, runs it and records it. Tool use inside an agent still goes permission
check, approval, broker, audit.

Once an agent has returned, its result is a fact: nothing after that point may hide
or change it. `run` turns every agent failure (exception, timeout, a wrong type, a
result for a different dispatch, times outside the observed window) into a failed
ExecutionResult with a user-safe error. A cancelled dispatch (client gone, shutdown)
is recorded as cancelled before the cancellation propagates. The record runs in a
worker thread, so a second cancellation can't stop it, but the host must drain the
default executor on shutdown (uvicorn and asyncio.run do). `record` never raises: it
writes the execution memory record and the audit entry in one transaction, falls back
to the audit entry alone, and reports what it managed.

Agents must not block the event loop: the timeout can only interrupt an agent at an
`await`.
"""

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from pydantic import JsonValue
from sqlalchemy.orm import Session

from app.agents.base import BaseAgent, result_id
from app.agents.registry import AgentRegistry, UnknownAgentError
from app.audit import recorder
from app.core.auth import Principal
from app.memory.execution import ExecutionMemoryStatus, record_execution
from greenloop_contracts import (
    AgentStatus,
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


class DispatchRefusedError(Exception):
    """No agent ran. `audited` says whether the refusal reached the audit log."""

    def __init__(self, audited: bool) -> None:
        super().__init__()
        self.audited = audited


class AgentNotFoundError(DispatchRefusedError):
    pass


class AgentNotActiveError(DispatchRefusedError):
    pass


class DispatchForbiddenError(DispatchRefusedError):
    pass


@dataclass(frozen=True)
class RecordOutcome:
    memory: ExecutionMemoryStatus
    audited: bool


@dataclass(frozen=True)
class DispatchOutcome:
    result: ExecutionResult
    recorded: RecordOutcome


def new_dispatch_id() -> str:
    return f"dsp-{uuid.uuid4().hex}"


def _ended(
    item: Dispatch, started_at: datetime, status: ExecutionStatus, code: str, message: str
) -> ExecutionResult:
    return ExecutionResult(
        result_id=result_id(item),
        task_id=item.task_id,
        dispatch_id=item.dispatch_id,
        agent_id=item.agent_id,
        status=status,
        error=ErrorDetail(code=code, message=message),
        started_at=started_at,
        finished_at=datetime.now(UTC),
    )


def _failed(item: Dispatch, started_at: datetime, code: str, message: str) -> ExecutionResult:
    return _ended(item, started_at, ExecutionStatus.FAILED, code, message)


async def run(agent: BaseAgent, item: Dispatch) -> ExecutionResult:
    started_at = datetime.now(UTC)
    deadline = asyncio.timeout((item.timeout_ms or DEFAULT_TIMEOUT_MS) / 1000)
    try:
        async with deadline:
            result = await agent.run(item)
    except TimeoutError as err:
        if deadline.expired():
            return _failed(item, started_at, "AGENT_TIMEOUT", "The agent did not finish in time.")
        _log_failure(item, err)
        return _failed(item, started_at, "AGENT_FAILED", "The agent failed.")
    except Exception as err:
        _log_failure(item, err)
        return _failed(item, started_at, "AGENT_FAILED", "The agent failed.")
    if (
        not isinstance(result, ExecutionResult)
        or (
            result.dispatch_id,
            result.task_id,
            result.agent_id,
        )
        != (item.dispatch_id, item.task_id, item.agent_id)
        or not _within(result, started_at, datetime.now(UTC))
    ):
        logger.error("agent_result_invalid", agent_id=item.agent_id, dispatch_id=item.dispatch_id)
        return _failed(
            item, started_at, "AGENT_INVALID_RESULT", "The agent returned an invalid result."
        )
    return result


def _within(result: ExecutionResult, started_at: datetime, finished_at: datetime) -> bool:
    """The agent's reported times must fall inside the window the dispatcher observed,
    since execution memory stores them as verified."""
    return started_at <= result.started_at <= result.finished_at <= finished_at


def _log_failure(item: Dispatch, err: BaseException) -> None:
    """The exception type only: an agent's exception message can carry its inputs or a
    provider's response, which must not reach the logs."""
    logger.error(
        "agent_run_failed",
        agent_id=item.agent_id,
        dispatch_id=item.dispatch_id,
        error_type=type(err).__name__,
    )


async def dispatch(
    registry: AgentRegistry,
    session_factory: Callable[[], Session],
    *,
    principal: Principal,
    correlation_id: str,
    agent_id: str,
    task_id: str,
    inputs: dict[str, JsonValue],
    timeout_ms: int | None,
) -> DispatchOutcome:
    principal_id = principal.principal_id
    try:
        agent = registry.get(agent_id)
    except UnknownAgentError:
        audited = await asyncio.to_thread(
            record_refusal, session_factory, principal_id, correlation_id, agent_id, "agent_unknown"
        )
        raise AgentNotFoundError(audited) from None
    status = agent.descriptor.status
    if status is not AgentStatus.ACTIVE:
        audited = await asyncio.to_thread(
            record_refusal,
            session_factory,
            principal_id,
            correlation_id,
            agent_id,
            f"agent_{status.value}",
        )
        raise AgentNotActiveError(audited)
    if not registry.may_dispatch(principal, agent):
        audited = await asyncio.to_thread(
            record_refusal,
            session_factory,
            principal_id,
            correlation_id,
            agent_id,
            "permission_denied",
        )
        raise DispatchForbiddenError(audited)

    item = Dispatch(
        dispatch_id=new_dispatch_id(),
        task_id=task_id,
        agent_id=agent_id,
        principal_id=principal_id,
        correlation_id=correlation_id,
        inputs=inputs,
        timeout_ms=timeout_ms,
        dispatched_at=datetime.now(UTC),
    )
    started_at = datetime.now(UTC)
    try:
        result = await run(agent, item)
    except asyncio.CancelledError:
        cancelled = _ended(
            item,
            started_at,
            ExecutionStatus.CANCELLED,
            "AGENT_CANCELLED",
            "The dispatch was cancelled before the agent finished.",
        )
        await asyncio.shield(asyncio.to_thread(record, session_factory, item, cancelled))
        raise
    recorded = await asyncio.to_thread(record, session_factory, item, result)
    return DispatchOutcome(result, recorded)


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
            memory = record_execution(session, item.correlation_id, item, result)
            recorder.record(session, _audit(item, result, memory))
            session.commit()
        return RecordOutcome(memory, audited=True)
    except Exception as err:
        logger.error(
            "dispatch_record_failed", dispatch_id=item.dispatch_id, error_type=type(err).__name__
        )
    try:
        with session_factory() as session:
            recorder.record(session, _audit(item, result, ExecutionMemoryStatus.FAILED))
            session.commit()
        return RecordOutcome(ExecutionMemoryStatus.FAILED, audited=True)
    except Exception as err:
        logger.error(
            "dispatch_audit_failed", dispatch_id=item.dispatch_id, error_type=type(err).__name__
        )
        return RecordOutcome(ExecutionMemoryStatus.FAILED, audited=False)


def record_refusal(
    session_factory: Callable[[], Session],
    principal_id: str,
    correlation_id: str,
    agent_id: str,
    reason: str,
) -> bool:
    """Audit a dispatch refused before any agent ran. Never raises; returns whether the
    entry was written."""
    try:
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
        return True
    except Exception as err:
        logger.error("dispatch_refusal_audit_failed", error_type=type(err).__name__)
        return False
