"""Principal roles: `user` (default) or `system`. Only system principals may verify memory.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "principals",
        sa.Column("role", sa.String(length=16), server_default="user", nullable=False),
    )
    op.create_check_constraint("ck_principals_role", "principals", "role IN ('user', 'system')")


def downgrade() -> None:
    op.drop_constraint("ck_principals_role", "principals", type_="check")
    op.drop_column("principals", "role")
