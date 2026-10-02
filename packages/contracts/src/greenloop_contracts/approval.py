"""Approval: a human's permission for one exact tool operation, used at most once.

The approval carries the ToolPermission it allows and that operation's SHA256
(`operation.py`). The broker stores and consumes approvals (ADR 0009); consuming one
needs the same hash, the same principal, status approved, and an unexpired approval.

Status and timestamps must agree:

| status   | decided_by / decided_at | consumed_at |
|----------|-------------------------|-------------|
| pending  | absent                  | absent      |
| approved | present                 | absent      |
| rejected | present                 | absent      |
| consumed | present                 | present     |
| expired  | either                  | absent      |
"""

from datetime import timedelta
from enum import StrEnum

from pydantic import model_validator

from greenloop_contracts.base import (
    ContractModel,
    Identifier,
    SafeMessage,
    Sha256Hex,
    Timestamp,
    UtcDatetime,
)
from greenloop_contracts.operation import operation_hash
from greenloop_contracts.tool_permission import ToolPermission

DEFAULT_APPROVAL_TTL = timedelta(minutes=15)


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CONSUMED = "consumed"
    EXPIRED = "expired"


class Approval(ContractModel):
    schema_version = "1"

    approval_id: Identifier
    principal_id: Identifier
    operation: ToolPermission
    operation_hash: Sha256Hex
    summary: SafeMessage
    status: ApprovalStatus = ApprovalStatus.PENDING
    decided_by: Identifier | None = None
    decided_at: UtcDatetime | None = None
    consumed_at: UtcDatetime | None = None
    expires_at: UtcDatetime
    created_at: Timestamp
    updated_at: Timestamp

    @model_validator(mode="after")
    def _consistent(self) -> "Approval":
        if self.operation_hash != operation_hash(self.operation):
            raise ValueError("operation_hash does not match the operation")
        if self.operation.principal_id != self.principal_id:
            raise ValueError("the operation must belong to the approval's principal")
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be before created_at")
        if (self.decided_by is None) != (self.decided_at is None):
            raise ValueError("decided_by and decided_at are set together")
        if self.decided_at is not None and self.decided_at < self.created_at:
            raise ValueError("decided_at cannot be before created_at")
        decided = self.decided_at is not None
        status = self.status
        if status is ApprovalStatus.PENDING and decided:
            raise ValueError("a pending approval has no decision")
        decided_states = (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED, ApprovalStatus.CONSUMED)
        if status in decided_states and not decided:
            raise ValueError(f"a {status} approval needs decided_by and decided_at")
        if status is ApprovalStatus.CONSUMED:
            if self.consumed_at is None:
                raise ValueError("a consumed approval needs consumed_at")
            if self.consumed_at < self.decided_at:
                raise ValueError("consumed_at cannot be before decided_at")
        elif self.consumed_at is not None:
            raise ValueError(f"a {status} approval cannot have consumed_at")
        return self
