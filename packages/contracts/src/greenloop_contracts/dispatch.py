"""Dispatch: sending one task to one agent, with retry accounting."""

from pydantic import Field, JsonValue, model_validator

from greenloop_contracts.base import ContractModel, Identifier, Timestamp


class Dispatch(ContractModel):
    dispatch_id: Identifier
    task_id: Identifier
    agent_id: Identifier
    principal_id: Identifier
    correlation_id: Identifier
    inputs: dict[str, JsonValue] = Field(default_factory=dict)
    attempt: int = Field(default=1, ge=1)
    max_attempts: int = Field(default=3, ge=1, le=10)
    dispatched_at: Timestamp

    @model_validator(mode="after")
    def _attempt_within_limit(self) -> "Dispatch":
        if self.attempt > self.max_attempts:
            raise ValueError("attempt cannot exceed max_attempts")
        return self
