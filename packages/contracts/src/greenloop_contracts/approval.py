"""Approval: a human's permission for one exact tool operation, used at most once.

The approval carries the ToolPermission it allows and that operation's SHA256
(`operation.py`). The broker stores and consumes approvals (ADR 0009); consuming one
needs the same hash, the same principal, status approved, and an unexpired approval.
`principal_id` repeats `operation.principal_id` as the owner and query key; the
validator keeps them equal. Only the owner decides (`decided_by == principal_id`);
that the owner is a human user, not a system principal or a dispatch, is checked by
the service that records the decision.

Expiry is not a status: an approval is expired when `expires_at` has passed, judged
by the store's clock at the moment of use. Status and timestamps must agree:

| status   | decided_by / decided_at | consumed_at |
|----------|-------------------------|-------------|
| pending  | absent                  | absent      |
| approved | present                 | absent      |
| rejected | present                 | absent      |
| consumed | present                 | present     |

and created_at <= decided_at <= consumed_at < expires_at, with decided_at also before
expires_at and updated_at no earlier than any of them.
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
MAX_APPROVAL_TTL = timedelta(hours=24)


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CONSUMED = "consumed"


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
        self._check_binding()
        self._check_status()
        self._check_order()
        return self

    def _check_binding(self) -> None:
        if self.operation_hash != operation_hash(self.operation):
            raise ValueError("operation_hash does not match the operation")
        if self.operation.principal_id != self.principal_id:
            raise ValueError("the operation must belong to the approval's principal")
        if self.decided_by is not None and self.decided_by != self.principal_id:
            raise ValueError("only the owning principal can decide an approval")

    def _check_status(self) -> None:
        if (self.decided_by is None) != (self.decided_at is None):
            raise ValueError("decided_by and decided_at are set together")
        decided = self.decided_at is not None
        if self.status is ApprovalStatus.PENDING and decided:
            raise ValueError("a pending approval has no decision")
        if self.status is not ApprovalStatus.PENDING and not decided:
            raise ValueError(f"a {self.status} approval needs decided_by and decided_at")
        if self.status is ApprovalStatus.CONSUMED and self.consumed_at is None:
            raise ValueError("a consumed approval needs consumed_at")
        if self.status is not ApprovalStatus.CONSUMED and self.consumed_at is not None:
            raise ValueError(f"a {self.status} approval cannot have consumed_at")

    def _check_order(self) -> None:
        if not self.created_at < self.expires_at <= self.created_at + MAX_APPROVAL_TTL:
            raise ValueError(f"expires_at must be after created_at and within {MAX_APPROVAL_TTL}")
        moments = [m for m in (self.decided_at, self.consumed_at) if m is not None]
        if moments != sorted(moments) or any(m < self.created_at for m in moments):
            raise ValueError("created_at, decided_at and consumed_at must be in order")
        if any(m >= self.expires_at for m in moments):
            raise ValueError("an approval cannot be decided or consumed after it expires")
        if any(self.updated_at < m for m in (self.created_at, *moments)):
            raise ValueError("updated_at cannot be before the events it records")
