"""Approval binding: an approval allows one exact operation, once.

The operation is hashed with greenloop_contracts.operation_hash (canonical JSON,
SHA256), the one definition every service shares. Consuming an approval checks
principal, expiry and hash, then marks it used under a lock, so two concurrent calls
cannot both succeed. A mismatched or expired attempt is refused without consuming
the approval.

TODO(phase-3): Postgres-backed store where consume is a single
`UPDATE ... WHERE consumed_at IS NULL ... RETURNING` statement.
"""

import threading
from dataclasses import dataclass
from datetime import UTC, datetime

from greenloop_contracts import ToolPermission, operation_hash


class ApprovalError(Exception):
    pass


class ApprovalNotFoundError(ApprovalError):
    pass


class ApprovalAlreadyConsumedError(ApprovalError):
    pass


class ApprovalMismatchError(ApprovalError):
    pass


class ApprovalExpiredError(ApprovalError):
    pass


@dataclass
class _Grant:
    operation_hash: str
    principal_id: str
    expires_at: datetime
    consumed_at: datetime | None = None


class InMemoryApprovalStore:
    def __init__(self) -> None:
        self._grants: dict[str, _Grant] = {}
        self._lock = threading.Lock()

    def grant(self, approval_id: str, permission: ToolPermission, expires_at: datetime) -> str:
        digest = operation_hash(permission)
        with self._lock:
            if approval_id in self._grants:
                raise ValueError(f"approval {approval_id} already exists")
            self._grants[approval_id] = _Grant(digest, permission.principal_id, expires_at)
        return digest

    def consume(
        self, approval_id: str, permission: ToolPermission, now: datetime | None = None
    ) -> str:
        now = now or datetime.now(UTC)
        digest = operation_hash(permission)
        with self._lock:
            grant = self._grants.get(approval_id)
            if grant is None:
                raise ApprovalNotFoundError(approval_id)
            if grant.consumed_at is not None:
                raise ApprovalAlreadyConsumedError(approval_id)
            if now >= grant.expires_at:
                raise ApprovalExpiredError(approval_id)
            if grant.principal_id != permission.principal_id or grant.operation_hash != digest:
                raise ApprovalMismatchError(approval_id)
            grant.consumed_at = now
        return digest
