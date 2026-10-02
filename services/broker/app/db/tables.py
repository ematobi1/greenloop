"""Broker tables, all in the broker schema (ADR 0009). The Alembic migrations in
app/db/migrations must match `metadata`.

approvals: one row per approval. `operation` is json, not jsonb: json keeps the text
exactly as written, while jsonb rewrites numbers (1e16 comes back as an int), which
would break the operation_hash binding; status and timestamps obey the same table as the
Approval contract, enforced again by check constraints. audit_events: append-only
(a trigger rejects UPDATE, DELETE and TRUNCATE). service_tokens: SHA256 of each
service token, never the token.
"""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Index,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, JSONB

from greenloop_contracts import ApprovalStatus, AuditOutcome

SCHEMA = "broker"
metadata = MetaData(schema=SCHEMA)


def _in(column: str, values: type) -> str:
    return f"{column} IN ({', '.join(repr(member.value) for member in values)})"


def _timestamps() -> list[Column]:
    return [
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    ]


approvals = Table(
    "approvals",
    metadata,
    Column("approval_id", String(128), primary_key=True),
    Column("principal_id", String(128), nullable=False),
    Column("operation", JSON, nullable=False),
    Column("operation_hash", String(64), nullable=False),
    Column("summary", String(500), nullable=False),
    Column("status", String(16), nullable=False, server_default=ApprovalStatus.PENDING.value),
    Column("idempotency_key", String(128), nullable=False),
    Column("decided_by", String(128), nullable=True),
    Column("decided_at", DateTime(timezone=True), nullable=True),
    Column("decision_idempotency_key", String(128), nullable=True),
    Column("consumed_at", DateTime(timezone=True), nullable=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    *_timestamps(),
    CheckConstraint(_in("status", ApprovalStatus), name="ck_approvals_status"),
    CheckConstraint("operation_hash ~ '^[0-9a-f]{64}$'", name="ck_approvals_operation_hash"),
    CheckConstraint(
        "created_at < expires_at AND expires_at <= created_at + interval '24 hours'",
        name="ck_approvals_lifetime",
    ),
    CheckConstraint(
        "(status = 'pending') = (decided_at IS NULL)"
        " AND (decided_by IS NULL) = (decided_at IS NULL)"
        " AND (decision_idempotency_key IS NULL) = (decided_at IS NULL)",
        name="ck_approvals_decision",
    ),
    CheckConstraint("decided_by IS NULL OR decided_by = principal_id", name="ck_approvals_owner"),
    CheckConstraint(
        "(status = 'consumed') = (consumed_at IS NOT NULL)", name="ck_approvals_consumed"
    ),
    CheckConstraint(
        "(decided_at IS NULL OR (created_at <= decided_at AND decided_at < expires_at))"
        " AND (consumed_at IS NULL"
        " OR (decided_at <= consumed_at AND consumed_at < expires_at))",
        name="ck_approvals_order",
    ),
    UniqueConstraint("principal_id", "idempotency_key", name="uq_approvals_idempotency"),
    Index("ix_approvals_principal_status", "principal_id", "status", "created_at"),
)

audit_events = Table(
    "audit_events",
    metadata,
    Column("audit_id", String(128), primary_key=True),
    Column("principal_id", String(128), nullable=False),
    Column("actor", String(128), nullable=False),
    Column("action", String(128), nullable=False),
    Column("resource_type", String(128), nullable=False),
    Column("resource_id", String(500), nullable=True),
    Column("outcome", String(32), nullable=False),
    Column("correlation_id", String(128), nullable=False),
    Column("operation_hash", String(64), nullable=True),
    Column("approval_id", String(128), nullable=True),
    Column("details", JSONB, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    *_timestamps(),
    CheckConstraint(_in("outcome", AuditOutcome), name="ck_audit_events_outcome"),
    Index("ix_audit_events_correlation_id", "correlation_id"),
    Index("ix_audit_events_principal_occurred", "principal_id", "occurred_at"),
    Index("ix_audit_events_approval_id", "approval_id"),
)

service_tokens = Table(
    "service_tokens",
    metadata,
    Column("token_id", String(128), primary_key=True),
    Column("name", String(100), nullable=False),
    Column("token_hash", String(64), nullable=False),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    *_timestamps(),
    CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="ck_service_tokens_token_hash"),
    UniqueConstraint("token_hash", name="uq_service_tokens_token_hash"),
)
