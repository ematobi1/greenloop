"""Dispatches: run one task on one registered agent for the authenticated principal.

The server builds the Dispatch (id, principal, correlation id, time); the caller only
names the agent, the task and the inputs. Only active agents run. The response is the
agent's ExecutionResult. Recording it can't change it: `X-Execution-Memory` says
whether the execution memory record was written (recorded, already_recorded, failed),
and `X-Audit-Persistence: failed` appears only if even the audit entry could not be
written.
"""

import asyncio
import json
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictInt, field_validator

from app.agents.registry import UnknownAgentError
from app.api.v1.agents import Registry, agent_not_found
from app.core.auth import CurrentPrincipal
from app.core.errors import ApiError
from app.orchestration import dispatcher
from greenloop_contracts import AgentStatus, Dispatch, ExecutionResult
from greenloop_contracts.base import AgentIdentifier, Identifier
from greenloop_contracts.dispatch import MAX_TIMEOUT_MS

router = APIRouter(prefix="/dispatches", tags=["dispatches"])

MAX_INPUT_BYTES = 65_536


class DispatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: AgentIdentifier
    task_id: Identifier
    inputs: dict[str, JsonValue] = Field(default_factory=dict)
    timeout_ms: Annotated[StrictInt, Field(ge=1, le=MAX_TIMEOUT_MS)] | None = None

    @field_validator("inputs")
    @classmethod
    def _bounded(cls, inputs: dict[str, JsonValue]) -> dict[str, JsonValue]:
        if len(json.dumps(inputs).encode("utf-8")) > MAX_INPUT_BYTES:
            raise ValueError(f"At most {MAX_INPUT_BYTES} bytes as JSON.")
        return inputs


@router.post("", status_code=201)
async def create_dispatch(
    body: DispatchCreate,
    request: Request,
    response: Response,
    principal: CurrentPrincipal,
    registry: Registry,
) -> ExecutionResult:
    session_factory = request.app.state.session_factory
    if session_factory is None:
        raise ApiError(503, "DATABASE_UNAVAILABLE", "The database is not configured.")
    correlation_id = request.state.correlation_id
    try:
        agent = registry.get(body.agent_id)
    except UnknownAgentError:
        raise agent_not_found() from None
    if agent.descriptor.status is not AgentStatus.ACTIVE:
        await asyncio.to_thread(
            dispatcher.record_refusal,
            session_factory,
            principal.principal_id,
            correlation_id,
            body.agent_id,
            f"agent_{agent.descriptor.status.value}",
        )
        raise ApiError(409, "AGENT_NOT_ACTIVE", "This agent is not active.")

    item = Dispatch(
        dispatch_id=dispatcher.new_dispatch_id(),
        task_id=body.task_id,
        agent_id=body.agent_id,
        principal_id=principal.principal_id,
        correlation_id=correlation_id,
        inputs=body.inputs,
        timeout_ms=body.timeout_ms,
        dispatched_at=datetime.now(UTC),
    )
    result = await dispatcher.run(agent, item)
    outcome = await asyncio.to_thread(dispatcher.record, session_factory, item, result)
    response.headers["X-Execution-Memory"] = outcome.memory.value
    if not outcome.audited:
        response.headers["X-Audit-Persistence"] = "failed"
    return result
