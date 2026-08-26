"""Unit coverage for deterministic modifier and promotion pricing rules."""

from datetime import UTC, datetime, time
from uuid import UUID

import pytest

from app.models.enums import PromotionActionType
from app.services.pricing import (
    MenuItemSnapshot,
    ModifierGroupSnapshot,
    ModifierOptionSnapshot,
    PricingContext,
    PricingRuleViolation,
    PromotionSnapshot,
    RequestedLine,
    RequestedModifier,
    price_cart,
)

VENUE = UUID("10000000-0000-0000-0000-000000000001")
OTHER_VENUE = UUID("10000000-0000-0000-0000-000000000002")
CATEGORY = UUID("20000000-0000-0000-0000-000000000001")
ITEM = UUID("30000000-0000-0000-0000-000000000001")
GROUP = UUID("40000000-0000-0000-0000-000000000001")
OPTION = UUID("50000000-0000-0000-0000-000000000001")
LINE = UUID("60000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 8, 26, 19, 15, tzinfo=UTC)


def _item(*, venue_id: UUID = VENUE) -> MenuItemSnapshot:
    option = ModifierOptionSnapshot(
        id=OPTION,
        group_id=GROUP,
        group_name="Молоко",
        name="Кокосовое",
        price_delta_minor=6_000,
        allows_quantity=False,
        max_quantity=1,
    )
    return MenuItemSnapshot(
        id=ITEM,
        venue_id=venue_id,
        category_id=CATEGORY,
        name="Латте",
        unit_price_minor=20_000,
        modifier_groups=(
            ModifierGroupSnapshot(
                id=GROUP,
                name="Молоко",
                min_selections=1,
                max_selections=1,
                options=(option,),
            ),
        ),
    )


def _line(*, venue_id: UUID = VENUE) -> RequestedLine:
    return RequestedLine(
        line_id=LINE if venue_id == VENUE else UUID(int=LINE.int + 1),
        item=_item(venue_id=venue_id),
        quantity=2,
        modifiers=(RequestedModifier(option_id=OPTION),),
    )


def _promotion(
    marker: int,
    *,
    venue_id: UUID = VENUE,
    percent: int = 1_500,
    priority: int = 0,
    stackable: bool = False,
) -> PromotionSnapshot:
    return PromotionSnapshot(
        id=UUID(int=marker),
        venue_id=venue_id,
        title=f"Promo {marker}",
        action_type=PromotionActionType.PERCENT_DISCOUNT,
        discount_value=percent,
        priority=priority,
        stackable=stackable,
        category_ids=frozenset({CATEGORY}),
        active_time_from=time(19),
    )


def _context() -> PricingContext:
    return PricingContext(
        local_datetime=NOW,
        fulfillment_mode="pickup",
        customer_birthday_active=False,
    )


def test_modifiers_are_snapshotted_and_percent_discount_uses_full_line_price() -> None:
    result = price_cart((_line(),), (_promotion(1),), _context())

    assert (result.subtotal_minor, result.discount_minor, result.total_minor) == (
        52_000,
        7_800,
        44_200,
    )
    line = result.venues[0].lines[0]
    assert (line.unit_base_price_minor, line.unit_modifiers_price_minor) == (20_000, 6_000)
    assert line.modifiers[0].name == "Кокосовое"


def test_priority_wins_then_equal_priority_uses_best_customer_benefit() -> None:
    high_priority_small = _promotion(1, percent=500, priority=10)
    low_priority_large = _promotion(2, percent=5_000, priority=5)
    same_priority_large = _promotion(3, percent=2_000, priority=10)

    result = price_cart(
        (_line(),),
        (low_priority_large, high_priority_small, same_priority_large),
        _context(),
    )

    assert [item.promotion_id for item in result.venues[0].promotions] == [UUID(int=3)]
    assert result.discount_minor == 10_400


def test_only_explicitly_stackable_promotions_combine_and_never_go_below_zero() -> None:
    first = _promotion(1, percent=8_000, priority=10, stackable=True)
    second = PromotionSnapshot(
        id=UUID(int=2),
        venue_id=VENUE,
        title="Large fixed",
        action_type=PromotionActionType.FIXED_DISCOUNT,
        discount_value=40_000,
        priority=0,
        stackable=True,
    )

    result = price_cart((_line(),), (first, second), _context())

    assert result.total_minor == 0
    assert result.discount_minor == result.subtotal_minor
    assert [item.discount_minor for item in result.venues[0].promotions] == [41_600, 10_400]


def test_mixed_cart_is_partitioned_and_promotions_never_cross_venue() -> None:
    result = price_cart(
        (_line(), _line(venue_id=OTHER_VENUE)),
        (_promotion(1),),
        _context(),
    )

    assert len(result.venues) == 2
    assert result.discount_minor == 7_800
    assert sum(venue.total_minor for venue in result.venues) == result.total_minor


def test_required_group_and_quantity_rules_fail_closed() -> None:
    missing = RequestedLine(line_id=LINE, item=_item(), quantity=1)
    with pytest.raises(PricingRuleViolation, match="недостаточно") as raised:
        price_cart((missing,), (), _context())
    assert raised.value.code == "modifier_group_minimum_not_met"

    too_many = RequestedLine(
        line_id=LINE,
        item=_item(),
        quantity=1,
        modifiers=(RequestedModifier(option_id=OPTION, quantity=2),),
    )
    with pytest.raises(PricingRuleViolation) as raised:
        price_cart((too_many,), (), _context())
    assert raised.value.code == "modifier_quantity_not_allowed"


def test_overnight_time_window_and_fulfillment_condition() -> None:
    promotion = PromotionSnapshot(
        id=UUID(int=1),
        venue_id=VENUE,
        title="Late pickup",
        action_type=PromotionActionType.PERCENT_DISCOUNT,
        discount_value=1_000,
        priority=0,
        stackable=False,
        active_time_from=time(22),
        active_time_to=time(2),
        fulfillment_modes=frozenset({"pickup"}),
    )
    context = PricingContext(
        local_datetime=datetime(2026, 8, 27, 1, tzinfo=UTC),
        fulfillment_mode="pickup",
        customer_birthday_active=False,
    )
    assert price_cart((_line(),), (promotion,), context).discount_minor == 5_200

    delivery = PricingContext(
        local_datetime=context.local_datetime,
        fulfillment_mode="delivery",
        customer_birthday_active=False,
    )
    assert price_cart((_line(),), (promotion,), delivery).discount_minor == 0
