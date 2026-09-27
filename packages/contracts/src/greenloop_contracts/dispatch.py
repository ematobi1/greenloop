"""Dispatch: sending one task to one agent for one attempt.

`inputs` is the one deliberately open field: its shape belongs to the agent's
domain. Everything around it (which task, which agent, when, what bounds) is fixed.
"""

from typing import Annotated

from pydantic import Field, JsonValue, StrictInt, model_validator

from greenloop_contracts.base import AgentIdentifier, ContractModel, Identifier, Timestamp

MAX_TIMEOUT_MS = 3_600_000


class Dispatch(ContractModel):
    schema_version = "2"

    dispatch_id: Identifier
    task_id: Identifier
    agent_id: AgentIdentifier
    principal_id: Identifier
    correlation_id: Identifier
    inputs: dict[str, JsonValue] = Field(default_factory=dict)
    timeout_ms: Annotated[StrictInt, Field(ge=1, le=MAX_TIMEOUT_MS)] | None = None
    attempt: int = Field(default=1, ge=1)
    max_attempts: int = Field(default=3, ge=1, le=10)
    dispatched_at: Timestamp

    @model_validator(mode="after")
    def _attempt_within_limit(self) -> "Dispatch":
        if self.attempt > self.max_attempts:
            raise ValueError("attempt cannot exceed max_attempts")
        return self
