"""Pure integer-only loyalty calculations.

This module deliberately has no database or FastAPI dependency. Transactional
services must re-run these calculations while holding the user's loyalty-state
row lock; a preview is never authoritative.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models.enums import RoundingMode


class LoyaltyRuleViolation(ValueError):
    """A stable business-rule failure that transport layers may translate."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class AccrualPolicy:
    enabled: bool
    minor_units_per_point: int
    minimum_purchase_minor: int
    maximum_purchase_minor: int
    rounding_mode: RoundingMode
    operation_limit_points: int | None = None
    daily_limit_points: int | None = None
    large_operation_threshold_minor: int | None = None
    large_operation_requires_approval: bool = False


@dataclass(frozen=True, slots=True)
class AccrualResult:
    purchase_amount_minor: int
    raw_points: int
    awarded_points: int
    limited_by_operation: bool
    limited_by_daily_total: bool
    requires_approval: bool


@dataclass(frozen=True, slots=True)
class RedemptionPolicy:
    enabled: bool
    redemption_minor_units_per_point: int
    minimum_redemption_points: int
    maximum_redemption_percent: int
    maximum_purchase_minor: int


@dataclass(frozen=True, slots=True)
class RedemptionResult:
    requested_points: int
    discount_minor: int
    maximum_points_for_purchase: int
    balance_after: int


@dataclass(frozen=True, slots=True)
class VisitProgress:
    streak_after: int
    allowed_misses_used: int
    reward_earned: bool
    cycle_completed: bool


@dataclass(frozen=True, slots=True)
class StampProgress:
    stamps_after: int
    rewards_earned: int


def _rounded_division(numerator: int, denominator: int, mode: RoundingMode) -> int:
    if denominator <= 0:
        raise LoyaltyRuleViolation(
            "invalid_accrual_rate", "Курс начисления должен быть положительным"
        )
    quotient, remainder = divmod(numerator, denominator)
    if mode is RoundingMode.FLOOR:
        return quotient
    if mode is RoundingMode.CEILING:
        return quotient + int(remainder > 0)
    if mode is RoundingMode.HALF_UP:
        return quotient + int(remainder * 2 >= denominator)
    raise LoyaltyRuleViolation("invalid_rounding_mode", "Неизвестный режим округления")


def calculate_accrual(
    policy: AccrualPolicy,
    *,
    purchase_amount_minor: int,
    accrued_today_points: int = 0,
) -> AccrualResult:
    """Calculate an accrual without mutating state.

    Limits cap the award instead of silently allowing an excessive value. The
    result reports which cap was applied so the UI can show it before confirm.
    """

    if not policy.enabled:
        raise LoyaltyRuleViolation("points_program_disabled", "Балльная программа отключена")
    if purchase_amount_minor <= 0:
        raise LoyaltyRuleViolation(
            "invalid_purchase_amount", "Сумма покупки должна быть больше нуля"
        )
    if purchase_amount_minor < policy.minimum_purchase_minor:
        raise LoyaltyRuleViolation("purchase_below_minimum", "Сумма покупки меньше минимальной")
    if purchase_amount_minor > policy.maximum_purchase_minor:
        raise LoyaltyRuleViolation(
            "purchase_above_maximum", "Сумма покупки превышает допустимый лимит"
        )
    if accrued_today_points < 0:
        raise LoyaltyRuleViolation(
            "invalid_daily_total", "Дневное начисление не может быть отрицательным"
        )

    raw_points = _rounded_division(
        purchase_amount_minor,
        policy.minor_units_per_point,
        policy.rounding_mode,
    )
    if raw_points <= 0:
        raise LoyaltyRuleViolation("no_points_to_accrue", "Покупка не создаёт ни одного балла")

    awarded_points = raw_points
    limited_by_operation = False
    if policy.operation_limit_points is not None:
        if policy.operation_limit_points <= 0:
            raise LoyaltyRuleViolation(
                "invalid_operation_limit", "Лимит операции должен быть положительным"
            )
        if awarded_points > policy.operation_limit_points:
            awarded_points = policy.operation_limit_points
            limited_by_operation = True

    limited_by_daily_total = False
    if policy.daily_limit_points is not None:
        if policy.daily_limit_points <= 0:
            raise LoyaltyRuleViolation(
                "invalid_daily_limit", "Дневной лимит должен быть положительным"
            )
        remaining = policy.daily_limit_points - accrued_today_points
        if remaining <= 0:
            raise LoyaltyRuleViolation(
                "daily_accrual_limit_reached", "Дневной лимит начисления исчерпан"
            )
        if awarded_points > remaining:
            awarded_points = remaining
            limited_by_daily_total = True

    requires_approval = bool(
        policy.large_operation_requires_approval
        and policy.large_operation_threshold_minor is not None
        and purchase_amount_minor >= policy.large_operation_threshold_minor
    )
    return AccrualResult(
        purchase_amount_minor=purchase_amount_minor,
        raw_points=raw_points,
        awarded_points=awarded_points,
        limited_by_operation=limited_by_operation,
        limited_by_daily_total=limited_by_daily_total,
        requires_approval=requires_approval,
    )


def calculate_redemption(
    policy: RedemptionPolicy,
    *,
    purchase_amount_minor: int,
    requested_points: int,
    current_balance_points: int,
) -> RedemptionResult:
    """Validate a points redemption and return its integer monetary coverage."""

    if not policy.enabled:
        raise LoyaltyRuleViolation("points_program_disabled", "Балльная программа отключена")
    if purchase_amount_minor <= 0 or purchase_amount_minor > policy.maximum_purchase_minor:
        raise LoyaltyRuleViolation("invalid_purchase_amount", "Недопустимая сумма покупки")
    if requested_points <= 0:
        raise LoyaltyRuleViolation(
            "invalid_redemption_points", "Количество баллов должно быть больше нуля"
        )
    if requested_points < policy.minimum_redemption_points:
        raise LoyaltyRuleViolation(
            "redemption_below_minimum", "Количество баллов меньше минимального"
        )
    if current_balance_points < 0:
        raise LoyaltyRuleViolation("invalid_balance", "Баланс не может быть отрицательным")
    if requested_points > current_balance_points:
        raise LoyaltyRuleViolation("insufficient_points", "Недостаточно баллов")
    if policy.redemption_minor_units_per_point <= 0:
        raise LoyaltyRuleViolation(
            "invalid_redemption_rate", "Курс списания должен быть положительным"
        )
    if not 0 <= policy.maximum_redemption_percent <= 100:
        raise LoyaltyRuleViolation(
            "invalid_redemption_percent", "Процент списания должен быть от 0 до 100"
        )

    maximum_discount_minor = purchase_amount_minor * policy.maximum_redemption_percent // 100
    maximum_points = maximum_discount_minor // policy.redemption_minor_units_per_point
    if maximum_points <= 0 or requested_points > maximum_points:
        raise LoyaltyRuleViolation(
            "redemption_above_purchase_limit",
            "Баллы превышают допустимую долю стоимости покупки",
        )
    discount_minor = requested_points * policy.redemption_minor_units_per_point
    return RedemptionResult(
        requested_points=requested_points,
        discount_minor=discount_minor,
        maximum_points_for_purchase=maximum_points,
        balance_after=current_balance_points - requested_points,
    )


def business_date_for(
    occurred_at: datetime,
    *,
    timezone_name: str,
    boundary_minutes: int,
) -> date:
    """Return the configured local business date for an aware timestamp."""

    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise LoyaltyRuleViolation(
            "naive_timestamp", "Время операции должно содержать часовой пояс"
        )
    if not 0 <= boundary_minutes < 24 * 60:
        raise LoyaltyRuleViolation(
            "invalid_business_day_boundary", "Некорректная граница бизнес-дня"
        )
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise LoyaltyRuleViolation("invalid_timezone", "Неизвестный часовой пояс") from exc
    local_time = occurred_at.astimezone(timezone)
    return (local_time - timedelta(minutes=boundary_minutes)).date()


def business_day_bounds_utc(
    business_date: date,
    *,
    timezone_name: str,
    boundary_minutes: int,
) -> tuple[datetime, datetime]:
    """Return the half-open UTC interval for one configured business day."""

    if not 0 <= boundary_minutes < 24 * 60:
        raise LoyaltyRuleViolation(
            "invalid_business_day_boundary", "Некорректная граница бизнес-дня"
        )
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise LoyaltyRuleViolation("invalid_timezone", "Неизвестный часовой пояс") from exc
    local_start = datetime.combine(business_date, time.min, timezone) + timedelta(
        minutes=boundary_minutes
    )
    local_end = datetime.combine(
        business_date + timedelta(days=1),
        time.min,
        timezone,
    ) + timedelta(minutes=boundary_minutes)
    return local_start.astimezone(UTC), local_end.astimezone(UTC)


def advance_visit_streak(
    *,
    previous_business_date: date | None,
    current_business_date: date,
    current_streak: int,
    required_visits: int,
    must_be_consecutive: bool,
    allowed_misses: int,
    allowed_misses_used: int,
    reset_on_miss: bool,
    restart_cycle_after_reward: bool,
    allow_same_business_date: bool = False,
) -> VisitProgress:
    """Advance a visit cycle after database-level daily-limit checks."""

    if current_streak < 0 or required_visits <= 0 or allowed_misses < 0 or allowed_misses_used < 0:
        raise LoyaltyRuleViolation(
            "invalid_visit_state", "Некорректное состояние программы посещений"
        )
    if previous_business_date is not None and (
        current_business_date < previous_business_date
        or (current_business_date == previous_business_date and not allow_same_business_date)
    ):
        raise LoyaltyRuleViolation(
            "duplicate_or_past_visit", "Посещение за этот бизнес-день уже учтено"
        )

    next_streak = current_streak + 1
    next_misses_used = allowed_misses_used
    if previous_business_date is None:
        next_streak = 1
        next_misses_used = 0
    elif must_be_consecutive and current_business_date > previous_business_date:
        missed_days = (current_business_date - previous_business_date).days - 1
        remaining_misses = max(allowed_misses - allowed_misses_used, 0)
        if missed_days > remaining_misses:
            if reset_on_miss:
                next_streak = 1
                next_misses_used = 0
            else:
                raise LoyaltyRuleViolation("visit_streak_broken", "Серия посещений прервана")
        else:
            next_misses_used += missed_days

    reward_earned = next_streak >= required_visits
    cycle_completed = reward_earned
    if reward_earned and restart_cycle_after_reward:
        next_streak = 0
        next_misses_used = 0
    elif reward_earned:
        next_streak = required_visits

    return VisitProgress(
        streak_after=next_streak,
        allowed_misses_used=next_misses_used,
        reward_earned=reward_earned,
        cycle_completed=cycle_completed,
    )


def advance_stamps(
    *,
    current_stamps: int,
    stamps_to_add: int,
    required_stamps: int,
    operation_limit: int,
    reset_after_reward: bool,
) -> StampProgress:
    """Advance the electronic stamp card and report newly earned rewards."""

    if current_stamps < 0 or stamps_to_add <= 0 or required_stamps <= 0 or operation_limit <= 0:
        raise LoyaltyRuleViolation("invalid_stamp_state", "Некорректное состояние карточки штампов")
    if stamps_to_add > operation_limit:
        raise LoyaltyRuleViolation("stamp_operation_limit", "Превышен лимит штампов одной операции")

    total = current_stamps + stamps_to_add
    if reset_after_reward:
        rewards_earned, stamps_after = divmod(total, required_stamps)
    else:
        rewards_earned = int(current_stamps < required_stamps <= total)
        stamps_after = total
    return StampProgress(stamps_after=stamps_after, rewards_earned=rewards_earned)
