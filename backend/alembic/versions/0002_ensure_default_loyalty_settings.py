"""ensure the singleton loyalty configuration exists

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-26 00:00:00.000000
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Repair installations that were started without importing seed data."""

    op.execute(
        sa.text(
            """
            INSERT INTO loyalty_settings (
                id,
                singleton_key,
                currency_name,
                currency_code,
                points_enabled,
                minor_units_per_point,
                redemption_minor_units_per_point,
                minimum_purchase_minor,
                maximum_purchase_minor,
                rounding_mode,
                maximum_redemption_percent,
                minimum_redemption_points,
                welcome_bonus_points,
                points_validity_days,
                daily_accrual_limit_points,
                operation_accrual_limit_points,
                large_operation_threshold_minor,
                large_operation_requires_approval,
                visits_enabled,
                visit_required_count,
                visits_must_be_consecutive,
                visit_daily_limit,
                timezone,
                business_day_boundary_minutes,
                visit_allowed_misses,
                visit_reset_on_miss,
                visit_reward_template_id,
                visit_reward_validity_days,
                visit_restart_cycle,
                stamps_enabled,
                stamp_required_count,
                stamps_per_purchase,
                stamp_operation_limit,
                stamp_reward_template_id,
                stamp_reward_validity_days,
                reset_stamps_after_reward,
                updated_by_staff_id
            )
            VALUES (
                :settings_id,
                'default',
                'баллы',
                'RUB',
                true,
                1000,
                100,
                0,
                1000000,
                'floor',
                50,
                1,
                0,
                NULL,
                NULL,
                NULL,
                NULL,
                false,
                true,
                5,
                true,
                1,
                'Europe/Moscow',
                240,
                0,
                true,
                NULL,
                7,
                true,
                true,
                9,
                1,
                1,
                NULL,
                30,
                true,
                NULL
            )
            ON CONFLICT (singleton_key) DO NOTHING
            """
        ).bindparams(
            sa.bindparam("settings_id", value=uuid4(), type_=sa.Uuid())
        )
    )


def downgrade() -> None:
    # Data is intentionally preserved: the row may have been edited by the owner
    # after this migration created it.
    pass
