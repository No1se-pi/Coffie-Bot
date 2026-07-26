"""add soft archive state for staff members

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-27 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "staff_members",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_staff_members_archived_at"),
        "staff_members",
        ["archived_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_staff_members_archived_at"), table_name="staff_members")
    op.drop_column("staff_members", "archived_at")
