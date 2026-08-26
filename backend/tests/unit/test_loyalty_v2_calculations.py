from datetime import UTC, date, datetime, timedelta, timezone
from uuid import UUID

import pytest

from app.models.enums import RoundingMode
from app.services.loyalty_calculations import LoyaltyRuleViolation
from app.services.loyalty_v2_calculations import (
    calculate_percentage_accrual,
    calculate_point_expiry,
    is_birthday_window_active,
    point_lot_fifo_key,
    validate_birthday,
)


@pytest.mark.parametrize(
    ("basis_points", "expected_points"),
    [(1_000, 10), (700, 7), (500, 5)],
)
def test_percentage_accrual_matches_demo_venue_rates(
    basis_points: int,
    expected_points: int,
) -> None:
    assert calculate_percentage_accrual(10_000, basis_points, RoundingMode.FLOOR) == expected_points


def test_percentage_accrual_is_independent_from_redemption_point_value() -> None:
    # There is deliberately no redemption-value argument: 100 RUB at 10%
    # always awards 10 numeric points, whether one point later covers 1 or 2 RUB.
    assert calculate_percentage_accrual(10_000, 1_000, RoundingMode.FLOOR) == 10


@pytest.mark.parametrize(
    ("mode", "expected_points"),
    [
        (RoundingMode.FLOOR, 1),
        (RoundingMode.HALF_UP, 2),
        (RoundingMode.CEILING, 2),
    ],
)
def test_percentage_accrual_uses_integer_only_rounding(
    mode: RoundingMode,
    expected_points: int,
) -> None:
    # 15 RUB at 10% is exactly 1.5 points.
    assert calculate_percentage_accrual(1_500, 1_000, mode) == expected_points


def test_percentage_accrual_validates_amount_and_basis_points() -> None:
    with pytest.raises(LoyaltyRuleViolation) as amount_error:
        calculate_percentage_accrual(-1, 1_000, RoundingMode.FLOOR)
    assert amount_error.value.code == "invalid_purchase_amount"

    for invalid_basis_points in (-1, 10_001):
        with pytest.raises(LoyaltyRuleViolation) as rate_error:
            calculate_percentage_accrual(10_000, invalid_basis_points, RoundingMode.FLOOR)
        assert rate_error.value.code == "invalid_accrual_basis_points"

    assert calculate_percentage_accrual(0, 1_000, RoundingMode.CEILING) == 0
    assert calculate_percentage_accrual(10_000, 0, RoundingMode.CEILING) == 0


@pytest.mark.parametrize(
    ("earned_at", "expected"),
    [
        (
            datetime(2026, 8, 31, 12, 30, tzinfo=UTC),
            datetime(2027, 2, 28, 12, 30, tzinfo=UTC),
        ),
        (
            datetime(2027, 8, 31, 12, 30, tzinfo=UTC),
            datetime(2028, 2, 29, 12, 30, tzinfo=UTC),
        ),
    ],
)
def test_calendar_month_expiry_clamps_missing_target_day(
    earned_at: datetime,
    expected: datetime,
) -> None:
    assert calculate_point_expiry(earned_at, validity_months=6) == expected


def test_point_expiry_uses_explicit_legacy_days_fallback() -> None:
    earned_at = datetime(2026, 1, 31, 9, tzinfo=UTC)
    assert calculate_point_expiry(
        earned_at,
        validity_months=None,
        legacy_validity_days=180,
    ) == earned_at + timedelta(days=180)

    # A non-null legacy setting wins so an upgraded installation does not
    # silently change its already configured validity policy.
    assert calculate_point_expiry(
        earned_at,
        validity_months=1,
        legacy_validity_days=180,
    ) == earned_at + timedelta(days=180)


def test_point_expiry_requires_aware_time_and_positive_policy() -> None:
    with pytest.raises(LoyaltyRuleViolation) as timestamp_error:
        calculate_point_expiry(
            datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None),
            validity_months=6,
        )
    assert timestamp_error.value.code == "invalid_earned_at"

    for months, days in ((0, None), (None, None), (None, 0)):
        with pytest.raises(LoyaltyRuleViolation) as policy_error:
            calculate_point_expiry(
                datetime(2026, 1, 1, tzinfo=UTC),
                validity_months=months,
                legacy_validity_days=days,
            )
        assert policy_error.value.code == "invalid_point_validity"


def test_birthday_validation_stores_no_year_but_accepts_february_29() -> None:
    assert validate_birthday(2, 29) is None
    for month, day in ((0, 1), (13, 1), (4, 31), (2, 30)):
        with pytest.raises(LoyaltyRuleViolation) as error:
            validate_birthday(month, day)
        assert error.value.code == "invalid_birthday"


def test_birthday_window_uses_server_timezone_and_is_reusable() -> None:
    before_local_midnight = datetime(2026, 8, 23, 20, 59, 59, tzinfo=UTC)
    local_midnight = datetime(2026, 8, 23, 21, 0, tzinfo=UTC)
    local_midday = datetime(2026, 8, 24, 9, 0, tzinfo=UTC)

    assert not is_birthday_window_active(
        8,
        24,
        at=before_local_midnight,
        timezone_name="Europe/Moscow",
        window_days=1,
    )
    assert is_birthday_window_active(
        8,
        24,
        at=local_midnight,
        timezone_name="Europe/Moscow",
        window_days=1,
    )
    assert is_birthday_window_active(
        8,
        24,
        at=local_midday,
        timezone_name="Europe/Moscow",
        window_days=1,
    )


def test_february_29_is_observed_on_february_28_only_in_non_leap_year() -> None:
    assert is_birthday_window_active(
        2,
        29,
        at=datetime(2026, 2, 28, 12, tzinfo=UTC),
        timezone_name="UTC",
        window_days=1,
    )
    assert not is_birthday_window_active(
        2,
        29,
        at=datetime(2026, 3, 1, 12, tzinfo=UTC),
        timezone_name="UTC",
        window_days=1,
    )
    assert not is_birthday_window_active(
        2,
        29,
        at=datetime(2028, 2, 28, 12, tzinfo=UTC),
        timezone_name="UTC",
        window_days=1,
    )
    assert is_birthday_window_active(
        2,
        29,
        at=datetime(2028, 2, 29, 12, tzinfo=UTC),
        timezone_name="UTC",
        window_days=1,
    )


def test_birthday_window_crosses_new_year_from_previous_occurrence() -> None:
    for active_day in (date(2026, 12, 31), date(2027, 1, 1), date(2027, 1, 2)):
        assert is_birthday_window_active(
            12,
            31,
            at=datetime.combine(active_day, datetime.min.time(), UTC),
            timezone_name="UTC",
            window_days=3,
        )
    assert not is_birthday_window_active(
        12,
        31,
        at=datetime(2027, 1, 3, tzinfo=UTC),
        timezone_name="UTC",
        window_days=3,
    )


def test_birthday_window_rejects_client_naive_time_and_invalid_timezone() -> None:
    with pytest.raises(LoyaltyRuleViolation) as time_error:
        is_birthday_window_active(
            8,
            24,
            at=datetime(2026, 8, 24, tzinfo=UTC).replace(tzinfo=None),
            timezone_name="UTC",
            window_days=1,
        )
    assert time_error.value.code == "invalid_birthday_time"

    with pytest.raises(LoyaltyRuleViolation) as timezone_error:
        is_birthday_window_active(
            8,
            24,
            at=datetime(2026, 8, 24, tzinfo=UTC),
            timezone_name="Invalid/Timezone",
            window_days=1,
        )
    assert timezone_error.value.code == "invalid_timezone"


def test_fifo_key_uses_original_earned_at_then_stable_id() -> None:
    older = datetime(2026, 1, 1, tzinfo=UTC)
    newer = datetime(2026, 1, 2, tzinfo=UTC)
    low_id = UUID(int=1)
    high_id = UUID(int=2)

    assert point_lot_fifo_key(older, high_id) < point_lot_fifo_key(newer, low_id)
    assert point_lot_fifo_key(older, low_id) < point_lot_fifo_key(older, high_id)


def test_fifo_key_canonicalizes_equivalent_aware_instants() -> None:
    utc_value = datetime(2026, 1, 1, tzinfo=UTC)
    plus_three = datetime(2026, 1, 1, 3, tzinfo=timezone(timedelta(hours=3)))
    lot_id = UUID(int=1)
    assert point_lot_fifo_key(utc_value, lot_id) == point_lot_fifo_key(plus_three, lot_id)
