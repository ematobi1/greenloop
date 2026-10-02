"""Deterministic reference agents. They make no model or tool calls, so dispatch,
audit and execution memory can be exercised end to end for free."""

from datetime import UTC, datetime

from app.agents.base import BaseAgent, result_id
from greenloop_contracts import (
    Agent,
    AgentDomain,
    AgentStatus,
    Dispatch,
    ErrorDetail,
    ExecutionResult,
    ExecutionStatus,
)

REGISTERED_AT = datetime(2026, 10, 2, tzinfo=UTC)


class EchoReferenceAgent(BaseAgent):
    descriptor = Agent(
        agent_id="echo-reference-agent",
        name="Echo reference agent",
        domain=AgentDomain.OTHER,
        version="1.0.0",
        description="Returns its inputs unchanged. For testing dispatch.",
        capabilities=("echo",),
        status=AgentStatus.ACTIVE,
        created_at=REGISTERED_AT,
        updated_at=REGISTERED_AT,
    )

    async def run(self, item: Dispatch) -> ExecutionResult:
        started = datetime.now(UTC)
        return ExecutionResult(
            result_id=result_id(item),
            task_id=item.task_id,
            dispatch_id=item.dispatch_id,
            agent_id=item.agent_id,
            status=ExecutionStatus.SUCCEEDED,
            output={"echo": item.inputs},
            started_at=started,
            finished_at=datetime.now(UTC),
        )


class FailingReferenceAgent(BaseAgent):
    descriptor = Agent(
        agent_id="failing-reference-agent",
        name="Failing reference agent",
        domain=AgentDomain.OTHER,
        version="1.0.0",
        description="Always fails with a user-safe error. For testing failure handling.",
        capabilities=("fail",),
        status=AgentStatus.ACTIVE,
        created_at=REGISTERED_AT,
        updated_at=REGISTERED_AT,
    )

    async def run(self, item: Dispatch) -> ExecutionResult:
        started = datetime.now(UTC)
        return ExecutionResult(
            result_id=result_id(item),
            task_id=item.task_id,
            dispatch_id=item.dispatch_id,
            agent_id=item.agent_id,
            status=ExecutionStatus.FAILED,
            error=ErrorDetail(
                code="REFERENCE_AGENT_FAILED", message="The reference agent failed on purpose."
            ),
            started_at=started,
            finished_at=datetime.now(UTC),
        )
