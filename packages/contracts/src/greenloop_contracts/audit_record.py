"""AuditRecord: an append-only entry for a consequential decision or action.

When an approval is involved, the record carries the SHA256 of the exact
operation the approval was bound to, so the ledger can prove what was allowed.
"""

from enum import StrEnum

from pydantic import Field, JsonValue, model_validator

from greenloop_contracts.base import ContractModel, Identifier, Sha256Hex, Timestamp


class AuditOutcome(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"
    APPROVAL_REQUIRED = "approval_required"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"


class AuditRecord(ContractModel):
    schema_version = "2"

    audit_id: Identifier
    principal_id: Identifier
    actor: Identifier
    action: Identifier
    resource_type: Identifier
    resource_id: str | None = Field(default=None, min_length=1, max_length=500)
    outcome: AuditOutcome
    correlation_id: Identifier
    operation_hash: Sha256Hex | None = None
    approval_id: Identifier | None = None
    details: dict[str, JsonValue] = Field(default_factory=dict)
    occurred_at: Timestamp

    @model_validator(mode="after")
    def _approval_needs_hash(self) -> "AuditRecord":
        if self.approval_id is not None and self.operation_hash is None:
            raise ValueError("an audit record with an approval must carry the operation hash")
        if self.outcome is AuditOutcome.APPROVED and self.approval_id is None:
            raise ValueError("an approved outcome must reference the approval")
        return self
