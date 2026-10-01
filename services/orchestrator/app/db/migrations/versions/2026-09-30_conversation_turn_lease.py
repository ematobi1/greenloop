"""Turn lease on conversations: at most one chat turn in flight per conversation.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("active_turn_id", sa.String(length=128)))
    op.add_column("conversations", sa.Column("turn_lease_expires_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("conversations", "turn_lease_expires_at")
    op.drop_column("conversations", "active_turn_id")
