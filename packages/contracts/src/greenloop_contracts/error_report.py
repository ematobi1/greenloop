"""ErrorReport: a structured failure record and the correction chosen for it.

The message is safe to show a user. Internal detail belongs in `details`,
which is never returned over the public API.
"""

from enum import StrEnum

from pydantic import Field, JsonValue

from greenloop_contracts.base import ContractModel, Identifier, ShortText, Timestamp


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
    error_id: Identifier
    correlation_id: Identifier
    task_id: Identifier | None = None
    category: ErrorCategory
    severity: ErrorSeverity
    message: ShortText
    details: dict[str, JsonValue] = Field(default_factory=dict)
    correction_action: CorrectionAction = CorrectionAction.NONE
    attempt: int = Field(default=1, ge=1)
    occurred_at: Timestamp
