"""ErrorReport: a structured failure record and the correction chosen for it.

`code`, `message` and `fields` are the user-safe part and have exactly the
ErrorDetail shape (see `detail()`). Internal detail belongs in `details`,
which is never returned over the public API.
"""

from enum import StrEnum

from pydantic import Field, JsonValue

from greenloop_contracts.base import (
    AgentIdentifier,
    ContractModel,
    ErrorCode,
    Identifier,
    SafeMessage,
    Timestamp,
)
from greenloop_contracts.error_detail import ErrorDetail


class ErrorCategory(StrEnum):
    VALIDATION = "validation"
    PERMISSION_DENIED = "permission_denied"
    TOOL_FAILURE = "tool_failure"
    MODEL_FAILURE = "model_failure"
    TIMEOUT = "timeout"
    INTERNAL = "internal"


class ErrorSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CorrectionAction(StrEnum):
    NONE = "none"
    RETRY = "retry"
    REPLAN = "replan"
    ESCALATE = "escalate"
    ABANDON = "abandon"


class ErrorReport(ContractModel):
    schema_version = "2"

    error_id: Identifier
    correlation_id: Identifier
    task_id: Identifier | None = None
    agent_id: AgentIdentifier | None = None
    code: ErrorCode
    message: SafeMessage
    fields: dict[str, SafeMessage] = Field(default_factory=dict)
    category: ErrorCategory
    severity: ErrorSeverity
    details: dict[str, JsonValue] = Field(default_factory=dict)
    correction_action: CorrectionAction = CorrectionAction.NONE
    attempt: int = Field(default=1, ge=1)
    occurred_at: Timestamp

    def detail(self) -> ErrorDetail:
        return ErrorDetail(code=self.code, message=self.message, fields=self.fields)
