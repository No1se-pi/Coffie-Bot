"""ensure default visit and stamp reward templates exist

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-26 00:00:00.000000
"""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VISIT_TEMPLATE_ID = UUID("de642256-4589-5b28-8339-5f9633cbe813")
STAMP_TEMPLATE_ID = UUID("fcf0643d-7cb5-5ce8-beeb-1bbf9df288b4")


def upgrade() -> None:
    """Repair installations created before the seed configuration was imported."""

    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            INSERT INTO reward_templates (
                id, name, description, reward_type, source_program,
                value_int, terms, validity_days, is_active
            )
            VALUES (
                :template_id,
                'Напиток за серию посещений',
                'Награда за пять последовательных посещений.',
                'free_product',
                'visits',
                NULL,
                'Условия выдачи и ассортимент уточняются у сотрудника кофейни.',
                7,
                true
            )
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {"template_id": VISIT_TEMPLATE_ID},
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO reward_templates (
                id, name, description, reward_type, source_program,
                value_int, terms, validity_days, is_active
            )
            VALUES (
                :template_id,
                'Десятый напиток бесплатно',
                'Выдаётся после девяти оплаченных напитков.',
                'free_product',
                'stamps',
                NULL,
                'Условия выдачи и ассортимент уточняются у сотрудника кофейни.',
                30,
                true
            )
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {"template_id": STAMP_TEMPLATE_ID},
    )
    connection.execute(
        sa.text(
            """
            UPDATE loyalty_settings
            SET
                visit_reward_template_id = COALESCE(
                    visit_reward_template_id, :visit_template_id
                ),
                stamp_reward_template_id = COALESCE(
                    stamp_reward_template_id, :stamp_template_id
                ),
                updated_at = CURRENT_TIMESTAMP
            WHERE singleton_key = 'default'
            """
        ),
        {
            "visit_template_id": VISIT_TEMPLATE_ID,
            "stamp_template_id": STAMP_TEMPLATE_ID,
        },
    )


def downgrade() -> None:
    # Templates and references are preserved because issued rewards may depend on them.
    pass
