"""ExecutionResult: the outcome of a task attempt or tool call.

Output and error follow the status:

| status    | output         | error                          |
|-----------|----------------|--------------------------------|
| succeeded | required       | forbidden                      |
| partial   | optional       | optional                       |
| failed    | forbidden      | required                       |
| denied    | forbidden      | required, code in DENIAL_CODES |
| cancelled | optional       | optional                       |

`error` is the user-safe ErrorDetail. Internal detail lives only in the linked
ErrorReport (`error_report_id`).
"""

from enum import StrEnum

from pydantic import JsonValue, model_validator

from greenloop_contracts.base import AgentIdentifier, ContractModel, Identifier, UtcDatetime
from greenloop_contracts.error_detail import ErrorDetail

DENIAL_CODES = frozenset(
    {"PERMISSION_DENIED", "POLICY_DENIED", "APPROVAL_REJECTED", "APPROVAL_EXPIRED"}
)


class ExecutionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    DENIED = "denied"
    CANCELLED = "cancelled"


class ExecutionResult(ContractModel):
    schema_version = "2"

    result_id: Identifier
    task_id: Identifier
    dispatch_id: Identifier | None = None
    agent_id: AgentIdentifier | None = None
    status: ExecutionStatus
    output: dict[str, JsonValue] | None = None
    error: ErrorDetail | None = None
    error_report_id: Identifier | None = None
    started_at: UtcDatetime
    finished_at: UtcDatetime

    @model_validator(mode="after")
    def _consistent(self) -> "ExecutionResult":
        if self.finished_at < self.started_at:
            raise ValueError("finished_at cannot be before started_at")
        status = self.status
        if status is ExecutionStatus.SUCCEEDED:
            if self.output is None:
                raise ValueError("a succeeded result requires output")
            if self.error is not None or self.error_report_id is not None:
                raise ValueError("a succeeded result cannot carry an error")
        if status in (ExecutionStatus.FAILED, ExecutionStatus.DENIED):
            if self.error is None:
                raise ValueError(f"a {status} result requires an error")
            if self.output is not None:
                raise ValueError(f"a {status} result cannot carry output")
        if status is ExecutionStatus.DENIED and self.error.code not in DENIAL_CODES:
            raise ValueError(f"a denied result needs a denial code: {sorted(DENIAL_CODES)}")
        return self
