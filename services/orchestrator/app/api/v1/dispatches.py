"""Dispatches: run one task on one registered agent for the authenticated principal.

A thin adapter over app/orchestration/dispatcher.py, which owns the checks. The caller
names the agent, the task and the inputs; the server builds the rest. The dispatch
runs synchronously and is not a stored resource, so success is 200 with the agent's
ExecutionResult (ADR 0008).

Recording can't change the result: `X-Execution-Memory` says whether the execution
memory record was written (recorded, already_recorded, failed), and
`X-Audit-Persistence: failed` appears only if the audit entry could not be written.
"""

import json
from typing import Annotated

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictInt, field_validator

from app.api.v1.agents import Registry, agent_not_found
from app.core.auth import CurrentPrincipal
from app.core.errors import ApiError
from app.orchestration import dispatcher
from greenloop_contracts import ExecutionResult
from greenloop_contracts.base import AgentIdentifier, Identifier

router = APIRouter(prefix="/dispatches", tags=["dispatches"])

MAX_INPUT_BYTES = 65_536
MAX_API_TIMEOUT_MS = 120_000
"""Well below the contract maximum: a dispatch holds its HTTP request open."""
MAX_INTEGER_DIGITS = 18

_HEADERS = {
    "X-Execution-Memory": {
        "description": "recorded, already_recorded or failed",
        "schema": {"type": "string"},
    },
    "X-Audit-Persistence": {
        "description": "Present as `failed` only when the audit entry could not be written",
        "schema": {"type": "string"},
    },
}


class DispatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: AgentIdentifier
    task_id: Identifier
    inputs: dict[str, JsonValue] = Field(default_factory=dict)
    timeout_ms: Annotated[StrictInt, Field(ge=1, le=MAX_API_TIMEOUT_MS)] | None = None

    @field_validator("inputs")
    @classmethod
    def _bounded(cls, inputs: dict[str, JsonValue]) -> dict[str, JsonValue]:
        try:
            text = json.dumps(inputs, ensure_ascii=False, allow_nan=False)
        except ValueError:
            raise ValueError("NaN and Infinity are not valid JSON.") from None
        if len(text.encode("utf-8")) > MAX_INPUT_BYTES:
            raise ValueError(f"At most {MAX_INPUT_BYTES} bytes as JSON.")
        if _has_huge_integer(inputs):
            raise ValueError(f"Integers must fit in {MAX_INTEGER_DIGITS} digits.")
        return inputs


def _has_huge_integer(value: JsonValue) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return abs(value) >= 10**MAX_INTEGER_DIGITS
    if isinstance(value, dict):
        return any(_has_huge_integer(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_huge_integer(item) for item in value)
    return False


def _refused(error: ApiError, refusal: dispatcher.DispatchRefusedError) -> ApiError:
    if not refusal.audited:
        error.headers = {**(error.headers or {}), "X-Audit-Persistence": "failed"}
    return error


@router.post("", responses={200: {"headers": _HEADERS}})
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
    try:
        outcome = await dispatcher.dispatch(
            registry,
            session_factory,
            principal_id=principal.principal_id,
            correlation_id=request.state.correlation_id,
            agent_id=body.agent_id,
            task_id=body.task_id,
            inputs=body.inputs,
            timeout_ms=body.timeout_ms,
        )
    except dispatcher.AgentNotFoundError as refusal:
        raise _refused(agent_not_found(), refusal) from None
    except dispatcher.DispatchForbiddenError as refusal:
        raise _refused(
            ApiError(403, "DISPATCH_FORBIDDEN", "You may not dispatch this agent."), refusal
        ) from None
    except dispatcher.AgentNotActiveError as refusal:
        raise _refused(
            ApiError(409, "AGENT_NOT_ACTIVE", "This agent is not active."), refusal
        ) from None
    response.headers["X-Execution-Memory"] = outcome.recorded.memory.value
    if not outcome.recorded.audited:
        response.headers["X-Audit-Persistence"] = "failed"
    return outcome.result
