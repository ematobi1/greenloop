"""Memory embeddings for semantic retrieval, in their own table so memory_records
stays append-only: an embedding can be added or backfilled later without touching
the record. Needs the vector extension, which db-bootstrap.ps1 creates.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DIMENSIONS = 768


def upgrade() -> None:
    has_vector = op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT FROM pg_extension WHERE extname = 'vector')")
    )
    if not has_vector:
        raise RuntimeError(
            r"The vector extension is missing. Run .\scripts\db-bootstrap.ps1, then migrate again."
        )
    op.create_table(
        "memory_embeddings",
        sa.Column("record_id", sa.String(length=128), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("embedding", Vector(DIMENSIONS), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["record_id"], ["memory_records.record_id"], name="fk_memory_embeddings_record"
        ),
        sa.PrimaryKeyConstraint("record_id", "model", name="pk_memory_embeddings"),
    )
    op.create_index(
        "ix_memory_embeddings_cosine",
        "memory_embeddings",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_table("memory_embeddings")
