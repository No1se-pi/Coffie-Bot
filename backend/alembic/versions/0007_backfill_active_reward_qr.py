"""issue opaque QR payloads for existing active rewards

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-02 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE rewards
            SET qr_payload = 'coffee-reward:v1:' || replace(gen_random_uuid()::text, '-', '')
            WHERE qr_payload IS NULL
              AND reward_type <> 'points'
              AND status = 'active'
            """
        )
    )


def downgrade() -> None:
    # Generated QR identifiers cannot be distinguished safely from identifiers
    # created by the application after this migration.
    pass
