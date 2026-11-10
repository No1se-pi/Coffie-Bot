from datetime import UTC, date, datetime

import pytest

from app.core.errors import AppError
from app.services.staff_benefits import bonus_cost, month_bounds


def test_moscow_month_changes_at_local_midnight_and_expires_in_utc() -> None:
    period, expiry = month_bounds(datetime(2026, 11, 30, 21, tzinfo=UTC), "Europe/Moscow")
    assert period == date(2026, 12, 1)
    assert expiry == datetime(2026, 12, 31, 21, tzinfo=UTC)


def test_december_rolls_to_the_next_year() -> None:
    period, expiry = month_bounds(datetime(2026, 12, 1, tzinfo=UTC), "Europe/Moscow")
    assert period == date(2026, 12, 1)
    assert expiry == datetime(2026, 12, 31, 21, tzinfo=UTC)


@pytest.mark.parametrize(("minor", "expected"), [(1, 1), (100, 1), (101, 2), (300000, 3000)])
def test_bonus_price_uses_integer_rounding(minor: int, expected: int) -> None:
    assert bonus_cost(minor) == expected


def test_zero_price_cannot_issue_a_free_employee_reward() -> None:
    with pytest.raises(AppError):
        bonus_cost(0)


def test_point_value_is_configurable() -> None:
    assert bonus_cost(201, 200) == 2
