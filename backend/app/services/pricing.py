"""Deterministic server-side menu pricing for cart and future order snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import status

from app.core.errors import AppError
from app.models.access import User
from app.models.content import MenuItem, ModifierGroup, ModifierOption, Promotion
from app.models.enums import PromotionActionType
from app.models.loyalty import LoyaltySettings
from app.services.loyalty_calculations import LoyaltyRuleViolation
from app.services.loyalty_v2_calculations import is_birthday_window_active


class PricingRuleViolation(ValueError):
    """Stable validation failure returned by the transport as a 422 response."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ModifierOptionSnapshot:
    id: UUID
    group_id: UUID
    group_name: str
    name: str
    price_delta_minor: int
    allows_quantity: bool
    max_quantity: int


@dataclass(frozen=True, slots=True)
class ModifierGroupSnapshot:
    id: UUID
    name: str
    min_selections: int
    max_selections: int
    options: tuple[ModifierOptionSnapshot, ...]


@dataclass(frozen=True, slots=True)
class MenuItemSnapshot:
    id: UUID
    venue_id: UUID
    category_id: UUID
    name: str
    unit_price_minor: int
    modifier_groups: tuple[ModifierGroupSnapshot, ...] = ()


@dataclass(frozen=True, slots=True)
class RequestedModifier:
    option_id: UUID
    quantity: int = 1


@dataclass(frozen=True, slots=True)
class RequestedLine:
    line_id: UUID
    item: MenuItemSnapshot
    quantity: int
    modifiers: tuple[RequestedModifier, ...] = ()


@dataclass(frozen=True, slots=True)
class PromotionSnapshot:
    id: UUID
    venue_id: UUID
    title: str
    action_type: PromotionActionType
    discount_value: int
    priority: int
    stackable: bool
    category_ids: frozenset[UUID] = frozenset()
    menu_item_ids: frozenset[UUID] = frozenset()
    active_from_date: date | None = None
    active_to_date: date | None = None
    active_weekdays: frozenset[int] = frozenset()
    active_time_from: time | None = None
    active_time_to: time | None = None
    fulfillment_modes: frozenset[str] = frozenset()
    customer_birthday_only: bool = False
    minimum_order_minor: int = 0


@dataclass(frozen=True, slots=True)
class SelectedModifierPrice:
    option_id: UUID
    group_id: UUID
    group_name: str
    name: str
    quantity: int
    unit_price_delta_minor: int
    total_price_delta_minor: int


@dataclass(frozen=True, slots=True)
class PricedLine:
    line_id: UUID
    menu_item_id: UUID
    venue_id: UUID
    category_id: UUID
    item_name: str
    quantity: int
    unit_base_price_minor: int
    unit_modifiers_price_minor: int
    subtotal_minor: int
    discount_minor: int
    total_minor: int
    modifiers: tuple[SelectedModifierPrice, ...]


@dataclass(frozen=True, slots=True)
class AppliedPromotion:
    promotion_id: UUID
    title: str
    priority: int
    discount_minor: int


@dataclass(frozen=True, slots=True)
class PricedVenue:
    venue_id: UUID
    subtotal_minor: int
    discount_minor: int
    total_minor: int
    lines: tuple[PricedLine, ...]
    promotions: tuple[AppliedPromotion, ...]


@dataclass(frozen=True, slots=True)
class PricingResult:
    subtotal_minor: int
    discount_minor: int
    total_minor: int
    venues: tuple[PricedVenue, ...]


@dataclass(frozen=True, slots=True)
class PricingContext:
    local_datetime: datetime
    fulfillment_mode: str
    customer_birthday_active: bool


class PricingRepositoryPort(Protocol):
    async def get_available_items(self, item_ids: set[UUID]) -> list[MenuItem]: ...

    async def list_modifier_rows(
        self, item_ids: set[UUID]
    ) -> list[tuple[UUID, ModifierGroup, ModifierOption]]: ...

    async def list_active_promotions(
        self, venue_ids: set[UUID], *, now: datetime
    ) -> list[Promotion]: ...

    async def list_promotion_category_targets(
        self, promotion_ids: set[UUID]
    ) -> list[tuple[UUID, UUID]]: ...

    async def list_promotion_item_targets(
        self, promotion_ids: set[UUID]
    ) -> list[tuple[UUID, UUID]]: ...

    async def get_customer_pricing_context(
        self, user_id: UUID
    ) -> tuple[User, LoyaltySettings] | None: ...

    async def list_birthday_venue_ids(self, settings_id: UUID) -> set[UUID]: ...


class CartPricingService:
    """Load trusted catalogue state, then delegate to the pure pricing engine."""

    def __init__(self, repository: PricingRepositoryPort) -> None:
        self._repository = repository

    async def preview(
        self,
        *,
        user_id: UUID,
        lines: tuple[tuple[UUID, UUID, int, tuple[RequestedModifier, ...]], ...],
        fulfillment_mode: str,
        now: datetime,
    ) -> PricingResult:
        item_ids = {item_id for _line_id, item_id, _quantity, _modifiers in lines}
        items = await self._repository.get_available_items(item_ids)
        item_by_id = {item.id: item for item in items}
        if set(item_by_id) != item_ids:
            raise AppError(
                code="menu_item_unavailable",
                message="Один из товаров недоступен",
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        context_row = await self._repository.get_customer_pricing_context(user_id)
        if context_row is None:
            raise AppError(
                code="customer_not_found",
                message="Профиль клиента не найден",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        user, settings = context_row
        modifier_rows = await self._repository.list_modifier_rows(item_ids)
        snapshots = _item_snapshots(items, modifier_rows)
        requested_lines = tuple(
            RequestedLine(
                line_id=line_id,
                item=snapshots[item_id],
                quantity=quantity,
                modifiers=modifiers,
            )
            for line_id, item_id, quantity, modifiers in lines
        )
        venue_ids = {item.venue_id for item in items}
        promotions = await self._repository.list_active_promotions(venue_ids, now=now)
        promotion_ids = {promotion.id for promotion in promotions}
        category_targets = _targets_by_promotion(
            await self._repository.list_promotion_category_targets(promotion_ids)
        )
        item_targets = _targets_by_promotion(
            await self._repository.list_promotion_item_targets(promotion_ids)
        )
        birthday_active = _birthday_active(user, settings, now)
        promotion_snapshots = [
            _promotion_snapshot(
                promotion,
                category_ids=category_targets.get(promotion.id, frozenset()),
                item_ids=item_targets.get(promotion.id, frozenset()),
            )
            for promotion in promotions
        ]
        birthday_venues = await self._repository.list_birthday_venue_ids(settings.id)
        if settings.birthday_promotion_enabled and birthday_active:
            eligible = birthday_venues or venue_ids
            promotion_snapshots.extend(
                PromotionSnapshot(
                    id=settings.id,
                    venue_id=venue_id,
                    title="Скидка ко дню рождения",
                    action_type=PromotionActionType.PERCENT_DISCOUNT,
                    discount_value=settings.birthday_discount_basis_points,
                    priority=0,
                    stackable=settings.birthday_stackable,
                )
                for venue_id in sorted(venue_ids & eligible, key=str)
            )
        try:
            return price_cart(
                requested_lines,
                tuple(promotion_snapshots),
                PricingContext(
                    local_datetime=now.astimezone(ZoneInfo(settings.timezone)),
                    fulfillment_mode=fulfillment_mode,
                    customer_birthday_active=birthday_active,
                ),
            )
        except PricingRuleViolation as exc:
            raise AppError(
                code=exc.code,
                message=exc.message,
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            ) from exc


def price_cart(
    lines: tuple[RequestedLine, ...],
    promotions: tuple[PromotionSnapshot, ...],
    context: PricingContext,
) -> PricingResult:
    """Price a mixed cart without trusting any amount supplied by a client."""

    if not lines:
        raise PricingRuleViolation("cart_empty", "Корзина пуста")
    if context.fulfillment_mode not in {"pickup", "delivery"}:
        raise PricingRuleViolation("invalid_fulfillment_mode", "Неизвестный способ получения")

    priced = tuple(_price_line(line) for line in lines)
    venue_ids = sorted({line.venue_id for line in priced}, key=str)
    venues = tuple(
        _price_venue(
            venue_id=venue_id,
            lines=tuple(line for line in priced if line.venue_id == venue_id),
            promotions=promotions,
            context=context,
        )
        for venue_id in venue_ids
    )
    return PricingResult(
        subtotal_minor=sum(venue.subtotal_minor for venue in venues),
        discount_minor=sum(venue.discount_minor for venue in venues),
        total_minor=sum(venue.total_minor for venue in venues),
        venues=venues,
    )


def _item_snapshots(
    items: list[MenuItem],
    rows: list[tuple[UUID, ModifierGroup, ModifierOption]],
) -> dict[UUID, MenuItemSnapshot]:
    groups_by_item: dict[UUID, dict[UUID, tuple[ModifierGroup, list[ModifierOption]]]] = {}
    for item_id, group, option in rows:
        item_groups = groups_by_item.setdefault(item_id, {})
        stored_group, options = item_groups.setdefault(group.id, (group, []))
        options.append(option)
        item_groups[group.id] = (stored_group, options)
    result: dict[UUID, MenuItemSnapshot] = {}
    for item in items:
        groups = tuple(
            ModifierGroupSnapshot(
                id=group.id,
                name=group.name,
                min_selections=group.min_selections,
                max_selections=group.max_selections,
                options=tuple(
                    ModifierOptionSnapshot(
                        id=option.id,
                        group_id=group.id,
                        group_name=group.name,
                        name=option.name,
                        price_delta_minor=option.price_delta_minor,
                        allows_quantity=option.allows_quantity,
                        max_quantity=option.max_quantity,
                    )
                    for option in options
                ),
            )
            for group, options in groups_by_item.get(item.id, {}).values()
        )
        result[item.id] = MenuItemSnapshot(
            id=item.id,
            venue_id=item.venue_id,
            category_id=item.category_id,
            name=item.name,
            unit_price_minor=item.price_minor,
            modifier_groups=groups,
        )
    return result


def _targets_by_promotion(rows: list[tuple[UUID, UUID]]) -> dict[UUID, frozenset[UUID]]:
    values: dict[UUID, set[UUID]] = {}
    for promotion_id, target_id in rows:
        values.setdefault(promotion_id, set()).add(target_id)
    return {promotion_id: frozenset(targets) for promotion_id, targets in values.items()}


def _promotion_snapshot(
    promotion: Promotion,
    *,
    category_ids: frozenset[UUID],
    item_ids: frozenset[UUID],
) -> PromotionSnapshot:
    if promotion.action_type is None or promotion.discount_value is None:
        raise RuntimeError("Enabled pricing promotion has no complete action")
    return PromotionSnapshot(
        id=promotion.id,
        venue_id=promotion.venue_id,
        title=promotion.title,
        action_type=promotion.action_type,
        discount_value=promotion.discount_value,
        priority=promotion.priority,
        stackable=promotion.stackable,
        category_ids=category_ids,
        menu_item_ids=item_ids,
        active_from_date=promotion.active_from_date,
        active_to_date=promotion.active_to_date,
        active_weekdays=frozenset(int(value) for value in promotion.active_weekdays),
        active_time_from=promotion.active_time_from,
        active_time_to=promotion.active_time_to,
        fulfillment_modes=frozenset(str(value) for value in promotion.fulfillment_modes),
        customer_birthday_only=promotion.customer_birthday_only,
        minimum_order_minor=promotion.minimum_order_minor,
    )


def _birthday_active(user: User, settings: LoyaltySettings, now: datetime) -> bool:
    if user.birthday_month is None or user.birthday_day is None:
        return False
    try:
        return is_birthday_window_active(
            user.birthday_month,
            user.birthday_day,
            at=now,
            timezone_name=settings.timezone,
            window_days=settings.birthday_window_days,
        )
    except LoyaltyRuleViolation as exc:
        raise RuntimeError("Persisted birthday pricing configuration is invalid") from exc


def _price_line(line: RequestedLine) -> PricedLine:
    if not 1 <= line.quantity <= 99:
        raise PricingRuleViolation("invalid_item_quantity", "Количество товара должно быть 1..99")
    option_lookup = {
        option.id: option for group in line.item.modifier_groups for option in group.options
    }
    selected_by_group: dict[UUID, int] = {}
    selected_ids: set[UUID] = set()
    modifiers: list[SelectedModifierPrice] = []
    unit_modifier_total = 0
    for requested in line.modifiers:
        if requested.option_id in selected_ids:
            raise PricingRuleViolation(
                "duplicate_modifier_option", "Один modifier option нельзя передать дважды"
            )
        selected_ids.add(requested.option_id)
        option = option_lookup.get(requested.option_id)
        if option is None:
            raise PricingRuleViolation(
                "modifier_not_applicable", "Modifier не относится к выбранному товару"
            )
        if requested.quantity < 1:
            raise PricingRuleViolation(
                "invalid_modifier_quantity", "Количество modifier должно быть положительным"
            )
        if not option.allows_quantity and requested.quantity != 1:
            raise PricingRuleViolation(
                "modifier_quantity_not_allowed", "Для modifier нельзя менять количество"
            )
        if requested.quantity > option.max_quantity:
            raise PricingRuleViolation(
                "modifier_quantity_exceeded", "Превышено максимальное количество modifier"
            )
        selected_by_group[option.group_id] = (
            selected_by_group.get(option.group_id, 0) + requested.quantity
        )
        total_delta = option.price_delta_minor * requested.quantity
        unit_modifier_total += total_delta
        modifiers.append(
            SelectedModifierPrice(
                option_id=option.id,
                group_id=option.group_id,
                group_name=option.group_name,
                name=option.name,
                quantity=requested.quantity,
                unit_price_delta_minor=option.price_delta_minor,
                total_price_delta_minor=total_delta,
            )
        )

    for group in line.item.modifier_groups:
        selected = selected_by_group.get(group.id, 0)
        if selected < group.min_selections:
            raise PricingRuleViolation(
                "modifier_group_minimum_not_met",
                f"Для группы «{group.name}» выбрано недостаточно вариантов",
            )
        if selected > group.max_selections:
            raise PricingRuleViolation(
                "modifier_group_maximum_exceeded",
                f"Для группы «{group.name}» выбрано слишком много вариантов",
            )

    subtotal = (line.item.unit_price_minor + unit_modifier_total) * line.quantity
    return PricedLine(
        line_id=line.line_id,
        menu_item_id=line.item.id,
        venue_id=line.item.venue_id,
        category_id=line.item.category_id,
        item_name=line.item.name,
        quantity=line.quantity,
        unit_base_price_minor=line.item.unit_price_minor,
        unit_modifiers_price_minor=unit_modifier_total,
        subtotal_minor=subtotal,
        discount_minor=0,
        total_minor=subtotal,
        modifiers=tuple(modifiers),
    )


def _price_venue(
    *,
    venue_id: UUID,
    lines: tuple[PricedLine, ...],
    promotions: tuple[PromotionSnapshot, ...],
    context: PricingContext,
) -> PricedVenue:
    subtotal = sum(line.subtotal_minor for line in lines)
    candidates: list[tuple[PromotionSnapshot, int, tuple[UUID, ...]]] = []
    for promotion in promotions:
        if promotion.venue_id != venue_id or not _conditions_match(
            promotion, context=context, venue_subtotal=subtotal
        ):
            continue
        targets = tuple(line.line_id for line in lines if _promotion_targets_line(promotion, line))
        target_total = sum(line.subtotal_minor for line in lines if line.line_id in targets)
        discount = _promotion_discount(promotion, target_total)
        if discount > 0:
            candidates.append((promotion, discount, targets))

    candidates.sort(key=lambda value: (-value[0].priority, -value[1], str(value[0].id)))
    selected: list[tuple[PromotionSnapshot, int, tuple[UUID, ...]]] = []
    if candidates:
        selected.append(candidates[0])
        # Explicit stackability is bilateral: a non-stackable winner blocks all
        # others, while a stackable winner may combine only with stackable rules.
        if candidates[0][0].stackable:
            selected.extend(candidate for candidate in candidates[1:] if candidate[0].stackable)

    discounts_by_line = {line.line_id: 0 for line in lines}
    applied: list[AppliedPromotion] = []
    for promotion, requested_discount, target_ids in selected:
        available_by_line = {
            line.line_id: line.subtotal_minor - discounts_by_line[line.line_id]
            for line in lines
            if line.line_id in target_ids
        }
        available_total = sum(available_by_line.values())
        discount = min(requested_discount, available_total)
        if discount <= 0:
            continue
        allocated = 0
        ordered_ids = sorted(available_by_line, key=str)
        for index, line_id in enumerate(ordered_ids):
            available = available_by_line[line_id]
            share = (
                discount - allocated
                if index == len(ordered_ids) - 1
                else discount * available // available_total
            )
            share = min(share, available)
            discounts_by_line[line_id] += share
            allocated += share
        applied.append(
            AppliedPromotion(
                promotion_id=promotion.id,
                title=promotion.title,
                priority=promotion.priority,
                discount_minor=allocated,
            )
        )

    final_lines = tuple(
        PricedLine(
            line_id=line.line_id,
            menu_item_id=line.menu_item_id,
            venue_id=line.venue_id,
            category_id=line.category_id,
            item_name=line.item_name,
            quantity=line.quantity,
            unit_base_price_minor=line.unit_base_price_minor,
            unit_modifiers_price_minor=line.unit_modifiers_price_minor,
            subtotal_minor=line.subtotal_minor,
            discount_minor=discounts_by_line[line.line_id],
            total_minor=line.subtotal_minor - discounts_by_line[line.line_id],
            modifiers=line.modifiers,
        )
        for line in lines
    )
    discount_total = sum(discounts_by_line.values())
    return PricedVenue(
        venue_id=venue_id,
        subtotal_minor=subtotal,
        discount_minor=discount_total,
        total_minor=subtotal - discount_total,
        lines=final_lines,
        promotions=tuple(applied),
    )


def _conditions_match(
    promotion: PromotionSnapshot,
    *,
    context: PricingContext,
    venue_subtotal: int,
) -> bool:
    local = context.local_datetime
    local_date = local.date()
    local_time = local.time().replace(tzinfo=None)
    if promotion.active_from_date is not None and local_date < promotion.active_from_date:
        return False
    if promotion.active_to_date is not None and local_date > promotion.active_to_date:
        return False
    if promotion.active_weekdays and local.weekday() not in promotion.active_weekdays:
        return False
    if not _time_window_matches(local_time, promotion.active_time_from, promotion.active_time_to):
        return False
    if promotion.fulfillment_modes and context.fulfillment_mode not in promotion.fulfillment_modes:
        return False
    if promotion.customer_birthday_only and not context.customer_birthday_active:
        return False
    return venue_subtotal >= promotion.minimum_order_minor


def _time_window_matches(value: time, start: time | None, end: time | None) -> bool:
    if start is None and end is None:
        return True
    if start is None:
        return value < end  # type: ignore[operator]
    if end is None:
        return value >= start
    if start <= end:
        return start <= value < end
    # A window such as 22:00..02:00 intentionally crosses midnight.
    return value >= start or value < end


def _promotion_targets_line(promotion: PromotionSnapshot, line: PricedLine) -> bool:
    if not promotion.category_ids and not promotion.menu_item_ids:
        return True
    return (
        line.category_id in promotion.category_ids or line.menu_item_id in promotion.menu_item_ids
    )


def _promotion_discount(promotion: PromotionSnapshot, target_total: int) -> int:
    if target_total <= 0:
        return 0
    if promotion.action_type is PromotionActionType.PERCENT_DISCOUNT:
        return target_total * promotion.discount_value // 10_000
    if promotion.action_type is PromotionActionType.FIXED_DISCOUNT:
        return min(target_total, promotion.discount_value)
    raise PricingRuleViolation("invalid_promotion_action", "Неизвестное действие акции")
