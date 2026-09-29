"""Append-only memory_records with a database-enforced supersede chain.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-28

- Unique `supersedes`: a record has at most one successor, so a chain never forks.
- Composite foreign key (supersedes, principal_id, chain_id, scope): a successor
  keeps its predecessor's principal, chain and scope.
- Triggers reject UPDATE, DELETE and TRUNCATE. `reject_mutation()` is generic and
  names the table, so later append-only tables can reuse it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCOPES = "'private', 'shared'"
CATEGORIES = (
    "'general_knowledge', 'project_context', 'task_execution_history', 'user_context', "
    "'organization_context', 'decision', 'verified_outcome', 'correction', 'agent_performance'"
)
CONFIDENCES = "'unverified', 'verified', 'corrected'"
OPERATIONS = "'create', 'supersede', 'correct', 'delete'"
SOURCES = "'user', 'agent', 'tool', 'import', 'system'"


def upgrade() -> None:
    op.create_table(
        "memory_records",
        sa.Column("record_id", sa.String(length=128), nullable=False),
        sa.Column("principal_id", sa.String(length=128), nullable=False),
        sa.Column("chain_id", sa.String(length=128), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("related_task_id", sa.String(length=128), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_ref", sa.String(length=500), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("operation", sa.String(length=16), nullable=False),
        sa.Column("supersedes", sa.String(length=128), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("record_id"),
        sa.ForeignKeyConstraint(["principal_id"], ["principals.principal_id"]),
        sa.UniqueConstraint("supersedes", name="uq_memory_records_supersedes"),
        sa.UniqueConstraint(
            "record_id", "principal_id", "chain_id", "scope", name="uq_memory_records_lineage"
        ),
        sa.ForeignKeyConstraint(
            ["supersedes", "principal_id", "chain_id", "scope"],
            [
                "memory_records.record_id",
                "memory_records.principal_id",
                "memory_records.chain_id",
                "memory_records.scope",
            ],
            name="fk_memory_records_predecessor",
        ),
        sa.CheckConstraint(f"scope IN ({SCOPES})", name="ck_memory_records_scope"),
        sa.CheckConstraint(f"category IN ({CATEGORIES})", name="ck_memory_records_category"),
        sa.CheckConstraint(f"confidence IN ({CONFIDENCES})", name="ck_memory_records_confidence"),
        sa.CheckConstraint(f"operation IN ({OPERATIONS})", name="ck_memory_records_operation"),
        sa.CheckConstraint(f"source IN ({SOURCES})", name="ck_memory_records_source"),
        sa.CheckConstraint(
            "(operation = 'create') = (supersedes IS NULL)", name="ck_memory_records_supersedes"
        ),
        sa.CheckConstraint(
            "(operation = 'create') = (chain_id = record_id)", name="ck_memory_records_chain_root"
        ),
        sa.CheckConstraint(
            "(operation = 'delete') = (content = '')", name="ck_memory_records_tombstone"
        ),
    )
    op.create_index(
        "ix_memory_records_principal_chain", "memory_records", ["principal_id", "chain_id"]
    )
    op.create_index(
        "ix_memory_records_principal_created", "memory_records", ["principal_id", "created_at"]
    )
    op.execute(
        """
        CREATE FUNCTION reject_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only (% rejected)', TG_TABLE_NAME, TG_OP
                USING ERRCODE = 'restrict_violation';
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER memory_records_no_update_delete BEFORE UPDATE OR DELETE ON memory_records "
        "FOR EACH ROW EXECUTE FUNCTION reject_mutation()"
    )
    op.execute(
        "CREATE TRIGGER memory_records_no_truncate BEFORE TRUNCATE ON memory_records "
        "FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation()"
    )


def downgrade() -> None:
    op.drop_table("memory_records")
    op.execute("DROP FUNCTION reject_mutation()")
