"""Pure order state, delivery-fee, and snapshot allocation rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models.enums import FulfillmentMode, OrderStatus


class OrderRuleViolation(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


SUBORDER_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.NEW: frozenset({OrderStatus.CONFIRMED, OrderStatus.CANCELLED}),
    OrderStatus.CONFIRMED: frozenset({OrderStatus.PREPARING, OrderStatus.CANCELLED}),
    OrderStatus.PREPARING: frozenset({OrderStatus.READY, OrderStatus.CANCELLED}),
    OrderStatus.READY: frozenset({OrderStatus.CANCELLED}),
    OrderStatus.CANCELLED: frozenset(),
}

ORDER_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.NEW: frozenset({OrderStatus.CONFIRMED, OrderStatus.CANCELLED}),
    OrderStatus.CONFIRMED: frozenset({OrderStatus.PREPARING, OrderStatus.CANCELLED}),
    OrderStatus.PREPARING: frozenset({OrderStatus.READY, OrderStatus.CANCELLED}),
    OrderStatus.READY: frozenset(
        {OrderStatus.WAITING_FOR_COURIER, OrderStatus.DELIVERED, OrderStatus.CANCELLED}
    ),
    OrderStatus.WAITING_FOR_COURIER: frozenset(
        {OrderStatus.COURIER_ASSIGNED, OrderStatus.CANCELLED}
    ),
    OrderStatus.COURIER_ASSIGNED: frozenset(
        {OrderStatus.WAITING_FOR_COURIER, OrderStatus.PICKED_UP, OrderStatus.CANCELLED}
    ),
    OrderStatus.PICKED_UP: frozenset({OrderStatus.IN_TRANSIT}),
    OrderStatus.IN_TRANSIT: frozenset({OrderStatus.DELIVERED}),
    OrderStatus.DELIVERED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
}


def require_transition(
    current: OrderStatus,
    target: OrderStatus,
    *,
    suborder: bool = False,
) -> None:
    """Reject arbitrary or backward status changes."""

    allowed = SUBORDER_TRANSITIONS if suborder else ORDER_TRANSITIONS
    if target not in allowed.get(current, frozenset()):
        raise OrderRuleViolation(
            "invalid_order_transition",
            f"Переход {current.value} → {target.value} запрещён",
        )


def derive_order_status(
    suborder_statuses: tuple[OrderStatus, ...],
    *,
    fulfillment_mode: FulfillmentMode,
) -> OrderStatus:
    """Derive the customer status from all venue preparation states."""

    active = tuple(value for value in suborder_statuses if value is not OrderStatus.CANCELLED)
    if not active:
        return OrderStatus.CANCELLED
    if all(value is OrderStatus.READY for value in active):
        return (
            OrderStatus.READY
            if fulfillment_mode is FulfillmentMode.PICKUP
            else OrderStatus.WAITING_FOR_COURIER
        )
    if any(value is OrderStatus.PREPARING for value in active):
        return OrderStatus.PREPARING
    if all(value in {OrderStatus.CONFIRMED, OrderStatus.READY} for value in active):
        return OrderStatus.CONFIRMED
    return OrderStatus.NEW


@dataclass(frozen=True, slots=True)
class DeliveryPolicy:
    enabled: bool
    minimum_order_minor: int
    fixed_fee_minor: int
    free_delivery_threshold_minor: int | None
    scheduling_allowed: bool
    earliest_preparation_minutes: int


@dataclass(frozen=True, slots=True)
class ZonePolicy:
    id: UUID
    fee_minor: int
    minimum_order_minor: int | None


def calculate_delivery_fee(
    subtotal_after_discounts_minor: int,
    *,
    policy: DeliveryPolicy,
    zone: ZonePolicy,
) -> int:
    """Validate simple-zone delivery and return its trusted fee."""

    if not policy.enabled:
        raise OrderRuleViolation("delivery_disabled", "Доставка сейчас отключена")
    minimum = zone.minimum_order_minor or policy.minimum_order_minor
    if subtotal_after_discounts_minor < minimum:
        raise OrderRuleViolation(
            "delivery_minimum_not_met",
            "Сумма заказа меньше минимальной для доставки",
        )
    if (
        policy.free_delivery_threshold_minor is not None
        and subtotal_after_discounts_minor >= policy.free_delivery_threshold_minor
    ):
        return 0
    return zone.fee_minor if zone.fee_minor > 0 else policy.fixed_fee_minor


def validate_desired_time(
    desired_at: datetime | None,
    *,
    now: datetime,
    policy: DeliveryPolicy,
) -> None:
    if desired_at is None:
        return
    if not policy.scheduling_allowed:
        raise OrderRuleViolation("delivery_scheduling_disabled", "Отложенная доставка отключена")
    if desired_at.tzinfo is None or desired_at.utcoffset() is None:
        raise OrderRuleViolation(
            "invalid_delivery_time", "Время доставки должно иметь часовой пояс"
        )
    earliest = now.astimezone(UTC) + timedelta(minutes=policy.earliest_preparation_minutes)
    if desired_at.astimezone(UTC) < earliest:
        raise OrderRuleViolation(
            "delivery_time_too_early", "Недостаточно времени на приготовление заказа"
        )


def validate_operating_hours(
    moment: datetime,
    *,
    operating_hours: dict[str, Any],
    timezone: str,
) -> None:
    """Validate a configured weekly interval in the location timezone.

    Empty configuration intentionally means unrestricted operation for backward
    compatibility. A configured week treats an absent/closed day as unavailable.
    """

    if not operating_hours:
        return
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise OrderRuleViolation("invalid_delivery_time", "Время должно иметь часовой пояс")
    try:
        local = moment.astimezone(ZoneInfo(timezone))
    except ZoneInfoNotFoundError as exc:
        raise OrderRuleViolation(
            "invalid_delivery_hours", "В настройках указан неизвестный часовой пояс"
        ) from exc
    day_name = (
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    )[local.weekday()]
    interval = operating_hours.get(day_name)
    if not isinstance(interval, str) or interval.strip().casefold() in {"", "closed"}:
        raise OrderRuleViolation("delivery_closed", "В выбранное время доставка не работает")
    try:
        raw_start, raw_end = (value.strip() for value in interval.split("-", maxsplit=1))
        start = time.fromisoformat(raw_start)
        end = time.fromisoformat(raw_end)
    except (TypeError, ValueError) as exc:
        raise OrderRuleViolation(
            "invalid_delivery_hours", "Некорректный интервал часов доставки"
        ) from exc
    current_minutes = local.hour * 60 + local.minute
    start_minutes = start.hour * 60 + start.minute
    end_minutes = end.hour * 60 + end.minute
    # Equal boundaries represent a full day; an earlier end is an overnight interval.
    if start_minutes == end_minutes:
        return
    inside = (
        start_minutes <= current_minutes < end_minutes
        if end_minutes > start_minutes
        else current_minutes >= start_minutes or current_minutes < end_minutes
    )
    if not inside:
        raise OrderRuleViolation("delivery_closed", "В выбранное время доставка не работает")


def allocate_discount(
    discount_minor: int,
    line_amounts: tuple[tuple[UUID, int], ...],
) -> dict[UUID, int]:
    """Allocate an integer discount proportionally with deterministic remainder."""

    if discount_minor < 0 or any(amount < 0 for _line_id, amount in line_amounts):
        raise OrderRuleViolation("invalid_discount", "Скидка не может быть отрицательной")
    total = sum(amount for _line_id, amount in line_amounts)
    if discount_minor > total:
        raise OrderRuleViolation("discount_exceeds_total", "Скидка превышает стоимость")
    if total == 0:
        return {line_id: 0 for line_id, _amount in line_amounts}
    allocated = 0
    result: dict[UUID, int] = {}
    ordered = sorted(line_amounts, key=lambda value: str(value[0]))
    for index, (line_id, amount) in enumerate(ordered):
        share = (
            discount_minor - allocated
            if index == len(ordered) - 1
            else discount_minor * amount // total
        )
        share = min(share, amount)
        result[line_id] = share
        allocated += share
    return result
