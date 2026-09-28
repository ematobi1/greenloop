"""Baseline: principals, api_tokens, append-only audit_records.

Revision ID: 0001
Revises:
Create Date: 2026-09-28

audit_records rejects UPDATE, DELETE and TRUNCATE through triggers, so the ledger
stays append-only even for code that bypasses the recorder.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AUDIT_OUTCOMES = (
    "'allowed', 'denied', 'approval_required', 'approved', 'rejected', 'executed', 'failed'"
)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "principals",
        sa.Column("principal_id", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("principal_id"),
    )
    op.create_table(
        "api_tokens",
        sa.Column("token_id", sa.String(length=128), nullable=False),
        sa.Column("principal_id", sa.String(length=128), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["principal_id"], ["principals.principal_id"]),
        sa.PrimaryKeyConstraint("token_id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_api_tokens_principal_id", "api_tokens", ["principal_id"])
    op.create_table(
        "audit_records",
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
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(f"outcome IN ({AUDIT_OUTCOMES})", name="ck_audit_records_outcome"),
        sa.ForeignKeyConstraint(["principal_id"], ["principals.principal_id"]),
        sa.PrimaryKeyConstraint("audit_id"),
    )
    op.create_index("ix_audit_records_correlation_id", "audit_records", ["correlation_id"])
    op.create_index(
        "ix_audit_records_principal_occurred", "audit_records", ["principal_id", "occurred_at"]
    )
    op.execute(
        """
        CREATE FUNCTION audit_records_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_records is append-only (% rejected)', TG_OP
                USING ERRCODE = 'restrict_violation';
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER audit_records_no_update_delete BEFORE UPDATE OR DELETE ON audit_records "
        "FOR EACH ROW EXECUTE FUNCTION audit_records_append_only()"
    )
    op.execute(
        "CREATE TRIGGER audit_records_no_truncate BEFORE TRUNCATE ON audit_records "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit_records_append_only()"
    )


def downgrade() -> None:
    op.drop_table("audit_records")
    op.execute("DROP FUNCTION audit_records_append_only()")
    op.drop_index("ix_api_tokens_principal_id", table_name="api_tokens")
    op.drop_table("api_tokens")
    op.drop_table("principals")
