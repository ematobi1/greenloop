"""ExecutionResult: the outcome of a task or tool call."""

from enum import StrEnum

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from greenloop_contracts.base import ContractModel, Identifier


class ExecutionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"
    CANCELLED = "cancelled"


class ExecutionResult(ContractModel):
    result_id: Identifier
    task_id: Identifier
    dispatch_id: Identifier | None = None
    status: ExecutionStatus
    output: dict[str, JsonValue] = Field(default_factory=dict)
    error_report_id: Identifier | None = None
    started_at: AwareDatetime
    finished_at: AwareDatetime

    @model_validator(mode="after")
    def _consistent(self) -> "ExecutionResult":
        if self.finished_at < self.started_at:
            raise ValueError("finished_at cannot be before started_at")
        if self.status is ExecutionStatus.FAILED and self.error_report_id is None:
            raise ValueError("a failed result must reference an error report")
        if self.status is ExecutionStatus.SUCCEEDED and self.error_report_id is not None:
            raise ValueError("a succeeded result cannot reference an error report")
        return self
