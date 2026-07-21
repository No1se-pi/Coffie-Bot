from datetime import UTC, date, datetime

from app.services.audit_formatter import format_audit_event
from app.services.loyalty_calculations import (
    advance_visit_streak,
    business_day_bounds_utc,
)


def test_business_day_bounds_follow_timezone_dst_transition() -> None:
    started_at, ended_at = business_day_bounds_utc(
        date(2026, 3, 29),
        timezone_name="Europe/Berlin",
        boundary_minutes=0,
    )

    assert started_at == datetime(2026, 3, 28, 23, tzinfo=UTC)
    assert ended_at == datetime(2026, 3, 29, 22, tzinfo=UTC)


def test_additional_visit_same_business_day_can_advance_when_limit_allows() -> None:
    result = advance_visit_streak(
        previous_business_date=date(2026, 7, 21),
        current_business_date=date(2026, 7, 21),
        current_streak=4,
        required_visits=5,
        must_be_consecutive=True,
        allowed_misses=0,
        allowed_misses_used=0,
        reset_on_miss=True,
        restart_cycle_after_reward=True,
        allow_same_business_date=True,
    )

    assert result.reward_earned is True
    assert result.streak_after == 0


def test_pending_and_cancelled_events_have_human_messages() -> None:
    pending = format_audit_event(
        "points.accrual_pending",
        {
            "customer_name": "Марии",
            "points": 50,
            "purchase_amount_minor": 50_000,
        },
    )
    cancelled = format_audit_event(
        "reward.cancelled",
        {
            "customer_name": "Марии",
            "reward_name": "Десерт",
            "reason": "ошибка",
        },
    )

    assert "ожидает подтверждения" in pending
    assert "Причина: ошибка" in cancelled
