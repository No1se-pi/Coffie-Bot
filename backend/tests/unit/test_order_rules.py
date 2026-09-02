from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.models.enums import FulfillmentMode, OrderStatus
from app.services.order_rules import (
    DeliveryPolicy,
    OrderRuleViolation,
    ZonePolicy,
    allocate_discount,
    calculate_delivery_fee,
    derive_order_status,
    require_transition,
    validate_desired_time,
    validate_operating_hours,
)
from app.services.orders import _distance_meters


def test_mixed_suborders_become_waiting_only_when_every_part_is_ready() -> None:
    assert (
        derive_order_status(
            (OrderStatus.READY, OrderStatus.PREPARING),
            fulfillment_mode=FulfillmentMode.DELIVERY,
        )
        is OrderStatus.PREPARING
    )
    assert (
        derive_order_status(
            (OrderStatus.READY, OrderStatus.READY),
            fulfillment_mode=FulfillmentMode.DELIVERY,
        )
        is OrderStatus.WAITING_FOR_COURIER
    )


def test_backward_transition_is_rejected() -> None:
    with pytest.raises(OrderRuleViolation) as raised:
        require_transition(OrderStatus.DELIVERED, OrderStatus.PREPARING)
    assert raised.value.code == "invalid_order_transition"


def test_zone_fee_and_free_threshold_are_server_side() -> None:
    policy = DeliveryPolicy(True, 50_000, 10_000, 100_000, True, 30)
    zone = ZonePolicy(uuid4(), fee_minor=15_000, minimum_order_minor=60_000)
    assert calculate_delivery_fee(75_000, policy=policy, zone=zone) == 15_000
    assert calculate_delivery_fee(100_000, policy=policy, zone=zone) == 0
    with pytest.raises(OrderRuleViolation):
        calculate_delivery_fee(59_999, policy=policy, zone=zone)


def test_desired_delivery_respects_scheduling_and_preparation_time() -> None:
    now = datetime(2026, 8, 27, 10, tzinfo=UTC)
    policy = DeliveryPolicy(True, 0, 0, None, True, 30)
    validate_desired_time(now + timedelta(minutes=30), now=now, policy=policy)
    with pytest.raises(OrderRuleViolation):
        validate_desired_time(now + timedelta(minutes=29), now=now, policy=policy)


def test_integer_discount_allocation_preserves_exact_total() -> None:
    first, second = uuid4(), uuid4()
    values = allocate_discount(101, ((first, 300), (second, 700)))
    assert sum(values.values()) == 101
    assert all(value >= 0 for value in values.values())


def test_delivery_hours_use_configured_location_timezone() -> None:
    moment = datetime(2026, 8, 27, 10, 30, tzinfo=UTC)  # Thursday 13:30 Moscow.
    validate_operating_hours(
        moment,
        operating_hours={"thursday": "12:00-14:00"},
        timezone="Europe/Moscow",
    )
    with pytest.raises(OrderRuleViolation) as raised:
        validate_operating_hours(
            moment + timedelta(hours=2),
            operating_hours={"thursday": "12:00-14:00"},
            timezone="Europe/Moscow",
        )
    assert raised.value.code == "delivery_closed"


def test_overnight_delivery_interval_accepts_late_time() -> None:
    validate_operating_hours(
        datetime(2026, 8, 27, 20, 30, tzinfo=UTC),  # Thursday 23:30 Moscow.
        operating_hours={"thursday": "11:00-00:00"},
        timezone="Europe/Moscow",
    )


def test_delivery_distance_uses_real_world_meters() -> None:
    # Roughly one kilometre north at Moscow's latitude.
    distance = _distance_meters(55.751244, 37.618423, 55.760227, 37.618423)
    assert 990 <= distance <= 1010
