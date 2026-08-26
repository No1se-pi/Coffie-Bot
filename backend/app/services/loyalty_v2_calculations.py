"""Pure Loyalty V2 calculations shared by preview and transactional services.

The helpers deliberately know nothing about SQLAlchemy, FastAPI, or mutable
wallet state.  A caller must still repeat the calculation while holding the
relevant database locks before committing a loyalty operation.
"""

from __future__ import annotations

import calendar
from datetime import UTC, date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models.enums import RoundingMode
from app.services.loyalty_calculations import LoyaltyRuleViolation

MINOR_UNITS_PER_RUBLE = 100
BASIS_POINTS_DENOMINATOR = 10_000
ACCRUAL_DENOMINATOR = MINOR_UNITS_PER_RUBLE * BASIS_POINTS_DENOMINATOR


def calculate_percentage_accrual(
    purchase_amount_minor: int,
    accrual_basis_points: int,
    rounding_mode: RoundingMode,
) -> int:
    """Return integer points for a percentage of a RUB-denominated purchase.

    Basis points determine the numeric point award directly from rubles:
    ``100 RUB * 1000 bps == 10 points``.  Redemption value is intentionally
    absent from this API because changing the value of one point must not
    retroactively change the configured accrual percentage.
    """

    if purchase_amount_minor < 0:
        raise LoyaltyRuleViolation(
            "invalid_purchase_amount",
            "Сумма покупки не может быть отрицательной",
        )
    if not 0 <= accrual_basis_points <= BASIS_POINTS_DENOMINATOR:
        raise LoyaltyRuleViolation(
            "invalid_accrual_basis_points",
            "Процент начисления должен быть от 0 до 10000 bps",
        )
    return _rounded_division(
        purchase_amount_minor * accrual_basis_points,
        ACCRUAL_DENOMINATOR,
        rounding_mode,
    )


def calculate_point_expiry(
    earned_at: datetime,
    *,
    validity_months: int | None = 6,
    legacy_validity_days: int | None = None,
) -> datetime:
    """Return the actual UTC expiry instant for a newly earned point lot.

    New V2 policy uses calendar months and clamps a missing target day to the
    last day of that month (for example, 31 August + 6 months = 28/29
    February).  A non-null ``legacy_validity_days`` deliberately overrides the
    month default so an existing installation keeps its configured policy.
    Opening migration lots must bypass this helper and keep ``expires_at=None``.
    """

    canonical_earned_at = _require_aware(earned_at, code="invalid_earned_at").astimezone(UTC)
    if legacy_validity_days is not None:
        if legacy_validity_days <= 0:
            raise LoyaltyRuleViolation(
                "invalid_point_validity",
                "Срок действия в днях должен быть положительным",
            )
        return canonical_earned_at + timedelta(days=legacy_validity_days)
    if validity_months is not None:
        if validity_months <= 0:
            raise LoyaltyRuleViolation(
                "invalid_point_validity",
                "Срок действия в месяцах должен быть положительным",
            )
        return _add_calendar_months(canonical_earned_at, validity_months)
    raise LoyaltyRuleViolation(
        "invalid_point_validity",
        "Нужен положительный срок действия баллов",
    )


def validate_birthday(month: int, day: int) -> None:
    """Validate the minimum-PII annual birthday representation (month/day)."""

    try:
        # Leap year 2000 deliberately permits the product's 29 February case.
        date(2000, month, day)
    except ValueError as exc:
        raise LoyaltyRuleViolation(
            "invalid_birthday",
            "Некорректные месяц или день рождения",
        ) from exc


def is_birthday_window_active(
    month: int,
    day: int,
    *,
    at: datetime,
    timezone_name: str,
    window_days: int,
) -> bool:
    """Return whether ``at`` falls in the reusable annual birthday window.

    A window starts on the observed local birthday and is half-open for
    ``window_days`` calendar days.  Checking both the current and previous
    occurrence makes windows crossing 31 December work without storing a birth
    year.  In a non-leap year, 29 February is observed on 28 February.
    """

    validate_birthday(month, day)
    if window_days <= 0:
        raise LoyaltyRuleViolation(
            "invalid_birthday_window",
            "Окно birthday promotion должно быть положительным",
        )
    aware_at = _require_aware(at, code="invalid_birthday_time")
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise LoyaltyRuleViolation("invalid_timezone", "Неизвестный часовой пояс") from exc
    local_day = aware_at.astimezone(timezone).date()
    for occurrence_year in (local_day.year, local_day.year - 1):
        starts_on = _observed_birthday(occurrence_year, month, day)
        if starts_on <= local_day < starts_on + timedelta(days=window_days):
            return True
    return False


def point_lot_fifo_key(earned_at: datetime, lot_id: UUID) -> tuple[datetime, int]:
    """Return the strict FIFO key: original acquisition instant, then lot id.

    Transfer and merge code must preserve ``earned_at``.  Destination-row
    creation time and ``expires_at`` must never make a lot younger or reorder
    it ahead of an older acquired lot.
    """

    canonical_earned_at = _require_aware(earned_at, code="invalid_earned_at").astimezone(UTC)
    return canonical_earned_at, lot_id.int


def _rounded_division(numerator: int, denominator: int, mode: RoundingMode) -> int:
    quotient, remainder = divmod(numerator, denominator)
    if mode is RoundingMode.FLOOR:
        return quotient
    if mode is RoundingMode.HALF_UP:
        return quotient + int(remainder * 2 >= denominator)
    if mode is RoundingMode.CEILING:
        return quotient + int(remainder > 0)
    raise LoyaltyRuleViolation("invalid_rounding_mode", "Неизвестный режим округления")


def _add_calendar_months(value: datetime, months: int) -> datetime:
    target_index = value.year * 12 + value.month - 1 + months
    target_year, zero_based_month = divmod(target_index, 12)
    target_month = zero_based_month + 1
    target_day = min(value.day, calendar.monthrange(target_year, target_month)[1])
    return value.replace(year=target_year, month=target_month, day=target_day)


def _observed_birthday(year: int, month: int, day: int) -> date:
    if month == 2 and day == 29 and not calendar.isleap(year):
        return date(year, 2, 28)
    return date(year, month, day)


def _require_aware(value: datetime, *, code: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise LoyaltyRuleViolation(code, "Время должно содержать часовой пояс")
    return value
