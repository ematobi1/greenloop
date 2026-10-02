"""Postgres approval store (ADR 0009). The broker trusts only this store: callers
send an operation or an approval_id, never an Approval (rule 7).

- create: binds the exact ToolPermission to its operation_hash. The summary is
  derived from the operation (rule 8). Expiry is the database's now() + ttl.
- decide: one UPDATE that only a pending, unexpired approval owned by the decider
  matches. That the decider is a human user, not a system principal or a dispatch,
  is checked by the caller (rule 6) before it gets here.
- consume: one UPDATE ... WHERE status = 'approved' AND consumed_at IS NULL AND
  expires_at > now() AND operation_hash = ... RETURNING (rule 4). Expiry is judged by
  the database clock. A refused attempt changes nothing. Internal to the broker: it
  has no HTTP endpoint and is used by the tool path in phase 3.

Create and decide take an idempotency key (rule 9): a repeat of the same request
returns the stored result instead of acting twice; the same key for a different
request is refused.

Each method runs in its own transaction and writes its audit event in it, so a
change and its audit row commit together, and a refusal's audit row commits even
though the method then raises ApprovalRefusedError.
"""

import json
import uuid
from datetime import timedelta
from enum import StrEnum

from sqlalchemy import Connection, Engine, RowMapping, func, select, update
from sqlalchemy.dialects.postgresql import insert

from app import audit
from app.db.tables import approvals
from greenloop_contracts import (
    Approval,
    ApprovalStatus,
    AuditOutcome,
    ToolPermission,
    operation_hash,
)

SUMMARY_MAX_CHARS = 500
LIST_LIMIT_MAX = 100


class ApprovalRefusal(StrEnum):
    NOT_FOUND = "not_found"
    NOT_PENDING = "not_pending"
    NOT_APPROVED = "not_approved"
    ALREADY_CONSUMED = "already_consumed"
    EXPIRED = "expired"
    OPERATION_MISMATCH = "operation_mismatch"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"


class ApprovalRefusedError(Exception):
    def __init__(self, reason: ApprovalRefusal, approval_id: str | None = None) -> None:
        super().__init__(reason.value)
        self.reason = reason
        self.approval_id = approval_id


def summarize(permission: ToolPermission) -> str:
    """What the operation does, built only from the operation. Non-ASCII characters
    are escaped (\\uXXXX) so lookalike text is visible."""
    arguments = json.dumps(
        permission.arguments, sort_keys=True, ensure_ascii=True, separators=(", ", ": ")
    )
    text = f"{permission.consequence.value}: {permission.tool}.{permission.operation} {arguments}"
    if len(text) > SUMMARY_MAX_CHARS:
        text = text[: SUMMARY_MAX_CHARS - 3] + "..."
    return text


def _to_contract(row: RowMapping) -> Approval:
    return Approval.model_validate(
        {
            "approval_id": row["approval_id"],
            "principal_id": row["principal_id"],
            "operation": row["operation"],
            "operation_hash": row["operation_hash"],
            "summary": row["summary"],
            "status": row["status"],
            "decided_by": row["decided_by"],
            "decided_at": row["decided_at"],
            "consumed_at": row["consumed_at"],
            "expires_at": row["expires_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
    )


class ApprovalStore:
    def __init__(self, engine: Engine, ttl: timedelta) -> None:
        self._engine = engine
        self._ttl = ttl

    def create(
        self,
        permission: ToolPermission,
        *,
        idempotency_key: str,
        actor: str,
        correlation_id: str,
    ) -> Approval:
        digest = operation_hash(permission)
        statement = (
            insert(approvals)
            .values(
                approval_id=f"apr-{uuid.uuid4().hex}",
                principal_id=permission.principal_id,
                operation=permission.model_dump(mode="json"),
                operation_hash=digest,
                summary=summarize(permission),
                idempotency_key=idempotency_key,
                expires_at=func.now() + self._ttl,
            )
            .on_conflict_do_nothing(constraint="uq_approvals_idempotency")
            .returning(*approvals.c)
        )
        with self._engine.begin() as connection:
            row = connection.execute(statement).mappings().first()
            if row is not None:
                approval = _to_contract(row)
                audit.record(
                    connection,
                    principal_id=approval.principal_id,
                    actor=actor,
                    action="approval.create",
                    outcome=AuditOutcome.APPROVAL_REQUIRED,
                    correlation_id=correlation_id,
                    resource_id=approval.approval_id,
                    approval_id=approval.approval_id,
                    operation_hash=digest,
                    details={"summary": approval.summary},
                )
                return approval
            existing = (
                connection.execute(
                    select(approvals).where(
                        approvals.c.principal_id == permission.principal_id,
                        approvals.c.idempotency_key == idempotency_key,
                    )
                )
                .mappings()
                .one()
            )
            if existing["operation_hash"] == digest:
                return _to_contract(existing)
            audit.record(
                connection,
                principal_id=permission.principal_id,
                actor=actor,
                action="approval.create",
                outcome=AuditOutcome.DENIED,
                correlation_id=correlation_id,
                operation_hash=digest,
                details={"reason": ApprovalRefusal.IDEMPOTENCY_CONFLICT.value},
            )
        raise ApprovalRefusedError(ApprovalRefusal.IDEMPOTENCY_CONFLICT)

    def get(self, approval_id: str, *, principal_id: str) -> Approval | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(approvals).where(
                        approvals.c.approval_id == approval_id,
                        approvals.c.principal_id == principal_id,
                    )
                )
                .mappings()
                .first()
            )
        return None if row is None else _to_contract(row)

    def list_for(
        self, principal_id: str, *, status: ApprovalStatus | None = None, limit: int = 50
    ) -> list[Approval]:
        statement = (
            select(approvals)
            .where(approvals.c.principal_id == principal_id)
            .order_by(approvals.c.created_at.desc(), approvals.c.approval_id)
            .limit(max(1, min(limit, LIST_LIMIT_MAX)))
        )
        if status is not None:
            statement = statement.where(approvals.c.status == status.value)
        with self._engine.connect() as connection:
            return [_to_contract(row) for row in connection.execute(statement).mappings()]

    def decide(
        self,
        approval_id: str,
        *,
        decided_by: str,
        approved: bool,
        idempotency_key: str,
        actor: str,
        correlation_id: str,
    ) -> Approval:
        status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
        statement = (
            update(approvals)
            .where(
                approvals.c.approval_id == approval_id,
                approvals.c.principal_id == decided_by,
                approvals.c.status == ApprovalStatus.PENDING.value,
                approvals.c.expires_at > func.now(),
            )
            .values(
                status=status.value,
                decided_by=decided_by,
                decided_at=func.now(),
                decision_idempotency_key=idempotency_key,
                updated_at=func.now(),
            )
            .returning(*approvals.c)
        )
        with self._engine.begin() as connection:
            row = connection.execute(statement).mappings().first()
            if row is not None:
                approval = _to_contract(row)
                audit.record(
                    connection,
                    principal_id=decided_by,
                    actor=actor,
                    action="approval.decide",
                    outcome=AuditOutcome.APPROVED if approved else AuditOutcome.REJECTED,
                    correlation_id=correlation_id,
                    resource_id=approval_id,
                    approval_id=approval_id,
                    operation_hash=approval.operation_hash,
                )
                return approval
            current = self._current(connection, approval_id, principal_id=decided_by)
            if current is not None and _is_replay(current, status, idempotency_key):
                return _to_contract(current)
            reason = _decide_refusal(current, idempotency_key)
            self._refuse(
                connection,
                "approval.decide",
                reason,
                approval_id,
                decided_by,
                actor,
                correlation_id,
                current,
            )
        raise ApprovalRefusedError(reason, approval_id)

    def consume(
        self, approval_id: str, permission: ToolPermission, *, actor: str, correlation_id: str
    ) -> Approval:
        digest = operation_hash(permission)
        statement = (
            update(approvals)
            .where(
                approvals.c.approval_id == approval_id,
                approvals.c.principal_id == permission.principal_id,
                approvals.c.status == ApprovalStatus.APPROVED.value,
                approvals.c.consumed_at.is_(None),
                approvals.c.expires_at > func.now(),
                approvals.c.operation_hash == digest,
            )
            .values(
                status=ApprovalStatus.CONSUMED.value,
                consumed_at=func.now(),
                updated_at=func.now(),
            )
            .returning(*approvals.c)
        )
        with self._engine.begin() as connection:
            row = connection.execute(statement).mappings().first()
            if row is not None:
                audit.record(
                    connection,
                    principal_id=permission.principal_id,
                    actor=actor,
                    action="approval.consume",
                    outcome=AuditOutcome.ALLOWED,
                    correlation_id=correlation_id,
                    resource_id=approval_id,
                    approval_id=approval_id,
                    operation_hash=digest,
                )
                return _to_contract(row)
            current = self._current(connection, approval_id, principal_id=permission.principal_id)
            reason = _consume_refusal(current, digest)
            self._refuse(
                connection,
                "approval.consume",
                reason,
                approval_id,
                permission.principal_id,
                actor,
                correlation_id,
                current,
                attempted_hash=digest,
            )
        raise ApprovalRefusedError(reason, approval_id)

    @staticmethod
    def _current(
        connection: Connection, approval_id: str, *, principal_id: str
    ) -> RowMapping | None:
        """The row as the owner sees it, with expiry judged by the database clock.
        Someone else's approval reads as not found."""
        return (
            connection.execute(
                select(approvals, (approvals.c.expires_at <= func.now()).label("expired")).where(
                    approvals.c.approval_id == approval_id,
                    approvals.c.principal_id == principal_id,
                )
            )
            .mappings()
            .first()
        )

    @staticmethod
    def _refuse(
        connection: Connection,
        action: str,
        reason: ApprovalRefusal,
        approval_id: str,
        principal_id: str,
        actor: str,
        correlation_id: str,
        current: RowMapping | None,
        attempted_hash: str | None = None,
    ) -> None:
        details: dict[str, str] = {"reason": reason.value}
        if attempted_hash is not None and current is not None:
            details["attempted_operation_hash"] = attempted_hash
        audit.record(
            connection,
            principal_id=principal_id,
            actor=actor,
            action=action,
            outcome=AuditOutcome.DENIED,
            correlation_id=correlation_id,
            resource_id=approval_id,
            approval_id=None if current is None else approval_id,
            operation_hash=attempted_hash if current is None else current["operation_hash"],
            details=details,
        )


def _decided_as(row: RowMapping) -> ApprovalStatus:
    status = ApprovalStatus(row["status"])
    return ApprovalStatus.APPROVED if status is ApprovalStatus.CONSUMED else status


def _is_replay(row: RowMapping, status: ApprovalStatus, idempotency_key: str) -> bool:
    return row["decision_idempotency_key"] == idempotency_key and _decided_as(row) is status


def _decide_refusal(row: RowMapping | None, idempotency_key: str) -> ApprovalRefusal:
    if row is None:
        return ApprovalRefusal.NOT_FOUND
    if row["decision_idempotency_key"] == idempotency_key:
        return ApprovalRefusal.IDEMPOTENCY_CONFLICT
    if row["status"] != ApprovalStatus.PENDING.value:
        return ApprovalRefusal.NOT_PENDING
    return ApprovalRefusal.EXPIRED


def _consume_refusal(row: RowMapping | None, digest: str) -> ApprovalRefusal:
    if row is None:
        return ApprovalRefusal.NOT_FOUND
    if row["status"] == ApprovalStatus.CONSUMED.value:
        return ApprovalRefusal.ALREADY_CONSUMED
    if row["status"] != ApprovalStatus.APPROVED.value:
        return ApprovalRefusal.NOT_APPROVED
    if row["expired"]:
        return ApprovalRefusal.EXPIRED
    if row["operation_hash"] != digest:
        return ApprovalRefusal.OPERATION_MISMATCH
    raise RuntimeError("consume matched no row but no refusal reason applies")
