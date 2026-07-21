from datetime import UTC, date, datetime

import pytest

from app.models.enums import RoundingMode
from app.services.loyalty_calculations import (
    AccrualPolicy,
    LoyaltyRuleViolation,
    RedemptionPolicy,
    advance_stamps,
    advance_visit_streak,
    business_date_for,
    calculate_accrual,
    calculate_redemption,
)


def accrual_policy(**overrides: object) -> AccrualPolicy:
    values: dict[str, object] = {
        "enabled": True,
        "minor_units_per_point": 1_000,
        "minimum_purchase_minor": 10_000,
        "maximum_purchase_minor": 10_000_000,
        "rounding_mode": RoundingMode.FLOOR,
    }
    values.update(overrides)
    return AccrualPolicy(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("mode", "amount", "expected"),
    [
        (RoundingMode.FLOOR, 10_499, 10),
        (RoundingMode.HALF_UP, 10_499, 10),
        (RoundingMode.HALF_UP, 10_500, 11),
        (RoundingMode.CEILING, 10_001, 11),
    ],
)
def test_accrual_uses_integer_rounding(mode: RoundingMode, amount: int, expected: int) -> None:
    result = calculate_accrual(
        accrual_policy(rounding_mode=mode),
        purchase_amount_minor=amount,
    )
    assert result.awarded_points == expected


def test_accrual_caps_operation_and_remaining_daily_limit() -> None:
    result = calculate_accrual(
        accrual_policy(operation_limit_points=100, daily_limit_points=80),
        purchase_amount_minor=2_000_000,
        accrued_today_points=30,
    )
    assert result.raw_points == 2_000
    assert result.awarded_points == 50
    assert result.limited_by_operation is True
    assert result.limited_by_daily_total is True


def test_large_accrual_is_marked_for_approval() -> None:
    result = calculate_accrual(
        accrual_policy(
            large_operation_requires_approval=True,
            large_operation_threshold_minor=300_000,
        ),
        purchase_amount_minor=300_000,
    )
    assert result.requires_approval is True


def test_invalid_purchase_is_rejected() -> None:
    with pytest.raises(LoyaltyRuleViolation, match="больше нуля") as error:
        calculate_accrual(accrual_policy(), purchase_amount_minor=0)
    assert error.value.code == "invalid_purchase_amount"


def test_redemption_checks_balance_and_purchase_percentage() -> None:
    policy = RedemptionPolicy(
        enabled=True,
        redemption_minor_units_per_point=100,
        minimum_redemption_points=10,
        maximum_redemption_percent=30,
        maximum_purchase_minor=10_000_000,
    )
    result = calculate_redemption(
        policy,
        purchase_amount_minor=20_000,
        requested_points=60,
        current_balance_points=100,
    )
    assert result.discount_minor == 6_000
    assert result.maximum_points_for_purchase == 60
    assert result.balance_after == 40


def test_redemption_above_purchase_limit_is_rejected() -> None:
    policy = RedemptionPolicy(True, 100, 1, 30, 1_000_000)
    with pytest.raises(LoyaltyRuleViolation) as error:
        calculate_redemption(
            policy,
            purchase_amount_minor=20_000,
            requested_points=61,
            current_balance_points=100,
        )
    assert error.value.code == "redemption_above_purchase_limit"


def test_business_day_uses_timezone_and_boundary() -> None:
    # 00:30 UTC is 03:30 in Moscow, still the previous configured business day.
    occurred_at = datetime(2026, 7, 21, 0, 30, tzinfo=UTC)
    assert business_date_for(
        occurred_at,
        timezone_name="Europe/Moscow",
        boundary_minutes=240,
    ) == date(2026, 7, 20)


def test_visit_streak_allows_configured_missed_day_and_earns_reward() -> None:
    result = advance_visit_streak(
        previous_business_date=date(2026, 7, 18),
        current_business_date=date(2026, 7, 20),
        current_streak=4,
        required_visits=5,
        must_be_consecutive=True,
        allowed_misses=1,
        allowed_misses_used=0,
        reset_on_miss=True,
        restart_cycle_after_reward=True,
    )
    assert result.reward_earned is True
    assert result.streak_after == 0
    assert result.allowed_misses_used == 0


def test_visit_streak_resets_when_gap_is_too_large() -> None:
    result = advance_visit_streak(
        previous_business_date=date(2026, 7, 15),
        current_business_date=date(2026, 7, 20),
        current_streak=4,
        required_visits=5,
        must_be_consecutive=True,
        allowed_misses=1,
        allowed_misses_used=0,
        reset_on_miss=True,
        restart_cycle_after_reward=True,
    )
    assert result.reward_earned is False
    assert result.streak_after == 1


def test_stamps_issue_tenth_drink_reward_after_ninth_paid_item() -> None:
    result = advance_stamps(
        current_stamps=8,
        stamps_to_add=1,
        required_stamps=9,
        operation_limit=1,
        reset_after_reward=True,
    )
    assert result.rewards_earned == 1
    assert result.stamps_after == 0
