"""Approvals, append-only audit events and hashed service tokens (ADR 0009).

Revision ID: b0001
Revises:
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "broker"
APPROVAL_STATUSES = "'pending', 'approved', 'rejected', 'consumed'"
AUDIT_OUTCOMES = (
    "'allowed', 'denied', 'approval_required', 'approved', 'rejected', 'executed', 'failed'"
)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "approvals",
        sa.Column("approval_id", sa.String(length=128), nullable=False),
        sa.Column("principal_id", sa.String(length=128), nullable=False),
        sa.Column("operation", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("operation_hash", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("decided_by", sa.String(length=128), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(f"status IN ({APPROVAL_STATUSES})", name="ck_approvals_status"),
        sa.CheckConstraint("operation_hash ~ '^[0-9a-f]{64}$'", name="ck_approvals_operation_hash"),
        sa.CheckConstraint(
            "created_at < expires_at AND expires_at <= created_at + interval '24 hours'",
            name="ck_approvals_lifetime",
        ),
        sa.CheckConstraint(
            "(status = 'pending') = (decided_at IS NULL)"
            " AND (decided_by IS NULL) = (decided_at IS NULL)"
            " AND (decision_idempotency_key IS NULL) = (decided_at IS NULL)",
            name="ck_approvals_decision",
        ),
        sa.CheckConstraint(
            "decided_by IS NULL OR decided_by = principal_id", name="ck_approvals_owner"
        ),
        sa.CheckConstraint(
            "(status = 'consumed') = (consumed_at IS NOT NULL)", name="ck_approvals_consumed"
        ),
        sa.CheckConstraint(
            "(decided_at IS NULL OR (created_at <= decided_at AND decided_at < expires_at))"
            " AND (consumed_at IS NULL"
            " OR (decided_at <= consumed_at AND consumed_at < expires_at))",
            name="ck_approvals_order",
        ),
        sa.PrimaryKeyConstraint("approval_id"),
        sa.UniqueConstraint("principal_id", "idempotency_key", name="uq_approvals_idempotency"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_approvals_principal_status",
        "approvals",
        ["principal_id", "status", "created_at"],
        schema=SCHEMA,
    )

    op.create_table(
        "audit_events",
        sa.Column("audit_id", sa.String(length=128), nullable=False),
        sa.Column("principal_id", sa.String(length=128), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("resource_type", sa.String(length=128), nullable=False),
        sa.Column("resource_id", sa.String(length=500), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column("operation_hash", sa.String(length=64), nullable=True),
        sa.Column("approval_id", sa.String(length=128), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        *_timestamps(),
        sa.CheckConstraint(f"outcome IN ({AUDIT_OUTCOMES})", name="ck_audit_events_outcome"),
        sa.PrimaryKeyConstraint("audit_id"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_audit_events_correlation_id", "audit_events", ["correlation_id"], schema=SCHEMA
    )
    op.create_index(
        "ix_audit_events_principal_occurred",
        "audit_events",
        ["principal_id", "occurred_at"],
        schema=SCHEMA,
    )
    op.create_index("ix_audit_events_approval_id", "audit_events", ["approval_id"], schema=SCHEMA)
    op.execute(
        """
        CREATE FUNCTION broker.audit_events_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only (% rejected)', TG_OP
                USING ERRCODE = 'restrict_violation';
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER audit_events_no_update_delete BEFORE UPDATE OR DELETE"
        " ON broker.audit_events FOR EACH ROW EXECUTE FUNCTION broker.audit_events_append_only()"
    )
    op.execute(
        "CREATE TRIGGER audit_events_no_truncate BEFORE TRUNCATE ON broker.audit_events"
        " FOR EACH STATEMENT EXECUTE FUNCTION broker.audit_events_append_only()"
    )

    op.create_table(
        "service_tokens",
        sa.Column("token_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="ck_service_tokens_token_hash"),
        sa.PrimaryKeyConstraint("token_id"),
        sa.UniqueConstraint("token_hash", name="uq_service_tokens_token_hash"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("service_tokens", schema=SCHEMA)
    op.drop_table("audit_events", schema=SCHEMA)
    op.execute("DROP FUNCTION broker.audit_events_append_only()")
    op.drop_index("ix_approvals_principal_status", table_name="approvals", schema=SCHEMA)
    op.drop_table("approvals", schema=SCHEMA)
