"""Transactional customer orders built from authoritative pricing snapshots."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import NoReturn
from uuid import UUID, uuid4

from fastapi import status

from app.core.errors import AppError
from app.models.audit import AuditEvent
from app.models.content import Location
from app.models.delivery import NotificationOutbox
from app.models.enums import (
    AuditSeverity,
    FulfillmentMode,
    LoyaltyOperationType,
    OperationStatus,
    OrderStatus,
    PaymentMethod,
    PermissionCode,
    WalletMode,
)
from app.models.loyalty import LoyaltyOperation
from app.models.orders import (
    CustomerOrder,
    DeliverySettings,
    DeliveryZone,
    OrderAppliedPromotion,
    OrderEvent,
    OrderLine,
    OrderLineModifier,
    OrderPointRedemption,
    OrderSuborder,
)
from app.repositories.loyalty_v2 import PointLedgerRepository
from app.repositories.orders import OrderAggregate, OrderRepository
from app.security.rbac import Actor
from app.services.customers import normalize_phone
from app.services.loyalty_calculations import (
    LoyaltyRuleViolation,
    RedemptionPolicy,
    calculate_redemption,
)
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
from app.services.point_ledger import PointLedger
from app.services.pricing import CartPricingService, PricingResult, RequestedModifier


@dataclass(frozen=True, slots=True)
class OrderLineCommand:
    line_id: UUID
    menu_item_id: UUID
    quantity: int
    modifiers: tuple[RequestedModifier, ...]


@dataclass(frozen=True, slots=True)
class PointRedemptionCommand:
    venue_id: UUID
    points: int


@dataclass(frozen=True, slots=True)
class OrderCreateCommand:
    fulfillment_mode: FulfillmentMode
    lines: tuple[OrderLineCommand, ...]
    point_redemptions: tuple[PointRedemptionCommand, ...]
    pickup_location_id: UUID | None
    delivery_zone_id: UUID | None
    contact_phone: str
    delivery_address: str | None
    delivery_latitude: float | None
    delivery_longitude: float | None
    entrance: str | None
    apartment: str | None
    floor: str | None
    customer_comment: str | None
    desired_delivery_at: datetime | None
    payment_method: PaymentMethod


@dataclass(frozen=True, slots=True)
class OrderOutcome:
    aggregate: OrderAggregate
    idempotent_replay: bool = False


@dataclass(frozen=True, slots=True)
class OrderOptions:
    """Public checkout options sourced only from persisted configuration."""

    settings: DeliverySettings
    pickup_locations: tuple[Location, ...]
    delivery_zones: tuple[DeliveryZone, ...]
    zone_locations: dict[UUID, Location]


class OrderService:
    def __init__(
        self,
        repository: OrderRepository,
        pricing: CartPricingService,
        ledger_repository: PointLedgerRepository,
    ) -> None:
        self._repository = repository
        self._pricing = pricing
        self._ledger_repository = ledger_repository
        self._ledger = PointLedger(ledger_repository)

    async def get_options(self) -> OrderOptions:
        settings = await self._repository.get_delivery_settings()
        if settings is None:
            _conflict("delivery_settings_missing", "Настройки получения не созданы")
        zones = tuple(await self._repository.list_delivery_zones())
        zone_location_ids = {zone.location_id for zone in zones if zone.location_id is not None}
        zone_locations = {
            location.id: location
            for location_id in zone_location_ids
            if (location := await self._repository.get_location(location_id)) is not None
        }
        return OrderOptions(
            settings=settings,
            pickup_locations=tuple(await self._repository.list_pickup_locations()),
            delivery_zones=zones,
            zone_locations=zone_locations,
        )

    async def create(
        self,
        actor: Actor,
        command: OrderCreateCommand,
        *,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> OrderOutcome:
        current_time = _aware_now(now)
        normalized_phone = normalize_phone(command.contact_phone)
        request_hash = _request_hash(command, normalized_phone=normalized_phone)
        async with self._repository.transaction():
            await self._repository.acquire_idempotency_lock(actor.user_id, idempotency_key)
            existing = await self._repository.get_by_idempotency(actor.user_id, idempotency_key)
            if existing is not None:
                if existing.request_hash != request_hash:
                    _conflict(
                        "order_idempotency_conflict",
                        "Этот Idempotency-Key уже использован с другим заказом",
                    )
                return OrderOutcome(
                    aggregate=await self._repository.aggregate(existing),
                    idempotent_replay=True,
                )

            priced = await self._pricing.preview(
                user_id=actor.user_id,
                lines=tuple(
                    (line.line_id, line.menu_item_id, line.quantity, line.modifiers)
                    for line in command.lines
                ),
                fulfillment_mode=command.fulfillment_mode.value,
                now=current_time,
            )
            delivery = await self._resolve_fulfillment(command, priced=priced, now=current_time)
            order = CustomerOrder(
                id=uuid4(),
                user_id=actor.user_id,
                fulfillment_mode=command.fulfillment_mode,
                status=OrderStatus.NEW,
                status_version=1,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                pickup_location_id=delivery.pickup_location_id,
                consolidation_location_id=delivery.consolidation_location_id,
                delivery_zone_id=command.delivery_zone_id,
                contact_phone=normalized_phone,
                delivery_address=_clean(command.delivery_address),
                delivery_latitude=command.delivery_latitude,
                delivery_longitude=command.delivery_longitude,
                entrance=_clean(command.entrance),
                apartment=_clean(command.apartment),
                floor=_clean(command.floor),
                customer_comment=_clean(command.customer_comment),
                desired_delivery_at=command.desired_delivery_at,
                pickup_name_snapshot=delivery.pickup_name,
                pickup_address_snapshot=delivery.pickup_address,
                delivery_zone_name_snapshot=delivery.zone_name,
                subtotal_minor=priced.subtotal_minor,
                promotion_discount_minor=priced.discount_minor,
                points_discount_minor=0,
                delivery_fee_minor=delivery.fee_minor,
                total_minor=priced.total_minor + delivery.fee_minor,
                payment_method=command.payment_method,
            )
            self._repository.add(order)
            await self._repository.flush()

            point_discounts = await self._redeem_points(
                actor,
                order=order,
                priced=priced,
                commands=command.point_redemptions,
                location_id=(delivery.pickup_location_id or delivery.consolidation_location_id),
                now=current_time,
            )
            order.points_discount_minor = sum(point_discounts.values())
            order.total_minor = (
                priced.total_minor - order.points_discount_minor + delivery.fee_minor
            )
            await self._snapshot_pricing(
                order,
                priced=priced,
                point_discounts=point_discounts,
            )
            self._repository.add_all(
                [
                    OrderEvent(
                        id=uuid4(),
                        order_id=order.id,
                        actor_user_id=actor.user_id,
                        actor_staff_id=actor.staff_member_id,
                        actor_role=actor.role.value,
                        from_status=None,
                        to_status=OrderStatus.NEW,
                        comment="Заказ создан",
                        created_at=current_time,
                    ),
                    NotificationOutbox(
                        id=uuid4(),
                        user_id=actor.user_id,
                        event_type="order.created",
                        payload={"order_id": str(order.id), "order_number": order.number},
                        idempotency_key=f"order.created:{order.id}",
                    ),
                ]
            )
            await self._repository.flush()
            return OrderOutcome(aggregate=await self._repository.aggregate(order))

    async def get_customer_order(self, actor: Actor, order_id: UUID) -> OrderAggregate:
        order = await self._repository.get_order(order_id, user_id=actor.user_id)
        if order is None:
            _not_found("Заказ не найден")
        return await self._repository.aggregate(order)

    async def list_customer_orders(
        self, actor: Actor, *, active: bool | None, limit: int
    ) -> list[OrderAggregate]:
        values = await self._repository.list_customer_orders(
            actor.user_id, active=active, limit=limit
        )
        return [await self._repository.aggregate(order) for order in values]

    async def list_staff_orders(
        self,
        actor: Actor,
        *,
        venue_id: UUID | None,
        statuses: set[OrderStatus],
        limit: int,
    ) -> list[OrderAggregate]:
        _require_permission(actor, PermissionCode.ORDERS_READ)
        values = await self._repository.list_staff_orders(
            venue_id=venue_id, statuses=statuses, limit=limit
        )
        return [await self._repository.aggregate(order) for order in values]

    async def get_staff_order(self, actor: Actor, order_id: UUID) -> OrderAggregate:
        _require_permission(actor, PermissionCode.ORDERS_READ)
        order = await self._repository.get_order(order_id)
        if order is None:
            _not_found("Заказ не найден")
        return await self._repository.aggregate(order)

    async def transition_suborder(
        self,
        actor: Actor,
        suborder_id: UUID,
        target: OrderStatus,
        *,
        reason: str | None,
        comment: str | None,
        now: datetime | None = None,
    ) -> OrderAggregate:
        _require_permission(actor, PermissionCode.ORDERS_MANAGE)
        current_time = _aware_now(now)
        async with self._repository.transaction():
            suborder = await self._repository.get_suborder(suborder_id, for_update=True)
            if suborder is None:
                _not_found("Часть заказа не найдена")
            order = await self._repository.get_order(suborder.order_id, for_update=True)
            if order is None:
                raise RuntimeError("Suborder references a missing order")
            try:
                require_transition(suborder.status, target, suborder=True)
            except OrderRuleViolation as exc:
                _rule_error(exc)
            previous_suborder = suborder.status
            suborder.status = target
            self._repository.add(
                _event(
                    order,
                    actor,
                    from_status=previous_suborder,
                    to_status=target,
                    suborder_id=suborder.id,
                    reason=reason,
                    comment=comment,
                    now=current_time,
                )
            )
            suborders = await self._repository.list_suborders(order.id, for_update=True)
            derived = derive_order_status(
                tuple(value.status for value in suborders),
                fulfillment_mode=order.fulfillment_mode,
            )
            if derived != order.status:
                previous_order = order.status
                order.status = derived
                order.status_version += 1
                if derived is OrderStatus.CONFIRMED:
                    order.confirmed_at = current_time
                self._repository.add_all(
                    [
                        _event(
                            order,
                            actor,
                            from_status=previous_order,
                            to_status=derived,
                            comment="Статус рассчитан по частям заказа",
                            now=current_time,
                        ),
                        _order_notification(order, derived),
                    ]
                )
            self._audit_transition(
                actor,
                order=order,
                suborder_id=suborder.id,
                from_status=previous_suborder,
                to_status=target,
            )
            await self._repository.flush()
            return await self._repository.aggregate(order)

    async def transition_order(
        self,
        actor: Actor,
        order_id: UUID,
        target: OrderStatus,
        *,
        reason: str | None,
        comment: str | None,
        now: datetime | None = None,
    ) -> OrderAggregate:
        _require_permission(actor, PermissionCode.ORDERS_MANAGE)
        current_time = _aware_now(now)
        async with self._repository.transaction():
            order = await self._repository.get_order(order_id, for_update=True)
            if order is None:
                _not_found("Заказ не найден")
            try:
                require_transition(order.status, target)
            except OrderRuleViolation as exc:
                _rule_error(exc)
            if target is OrderStatus.CANCELLED:
                await self._restore_points(order, actor=actor, now=current_time)
            previous = order.status
            suborders = await self._repository.list_suborders(order.id, for_update=True)
            suborder_events: list[OrderEvent] = []
            if target in {
                OrderStatus.CONFIRMED,
                OrderStatus.PREPARING,
                OrderStatus.READY,
                OrderStatus.CANCELLED,
            }:
                for suborder in suborders:
                    if suborder.status is target:
                        continue
                    try:
                        require_transition(suborder.status, target, suborder=True)
                    except OrderRuleViolation as exc:
                        _rule_error(exc)
                    suborder_previous = suborder.status
                    suborder.status = target
                    suborder_events.append(
                        _event(
                            order,
                            actor,
                            from_status=suborder_previous,
                            to_status=target,
                            suborder_id=suborder.id,
                            reason=reason,
                            comment=comment,
                            now=current_time,
                        )
                    )
            effective_target = (
                derive_order_status(
                    tuple(suborder.status for suborder in suborders),
                    fulfillment_mode=order.fulfillment_mode,
                )
                if target
                in {
                    OrderStatus.CONFIRMED,
                    OrderStatus.PREPARING,
                    OrderStatus.READY,
                    OrderStatus.CANCELLED,
                }
                else target
            )
            order.status = effective_target
            order.status_version += 1
            if effective_target is OrderStatus.CONFIRMED:
                order.confirmed_at = current_time
            elif effective_target is OrderStatus.DELIVERED:
                order.completed_at = current_time
            elif effective_target is OrderStatus.CANCELLED:
                order.cancelled_at = current_time
            self._repository.add_all(
                [
                    *suborder_events,
                    _event(
                        order,
                        actor,
                        from_status=previous,
                        to_status=effective_target,
                        reason=reason,
                        comment=comment,
                        now=current_time,
                    ),
                    _order_notification(order, effective_target),
                ]
            )
            self._audit_transition(
                actor,
                order=order,
                suborder_id=None,
                from_status=previous,
                to_status=effective_target,
            )
            await self._repository.flush()
            return await self._repository.aggregate(order)

    async def cancel_customer_order(
        self,
        actor: Actor,
        order_id: UUID,
        *,
        reason: str,
        now: datetime | None = None,
    ) -> OrderAggregate:
        current_time = _aware_now(now)
        normalized_reason = " ".join(reason.split()).strip()
        if not normalized_reason:
            _validation("cancellation_reason_required", "Укажите причину отмены")
        async with self._repository.transaction():
            order = await self._repository.get_order(
                order_id, user_id=actor.user_id, for_update=True
            )
            if order is None:
                _not_found("Заказ не найден")
            if order.status not in {
                OrderStatus.NEW,
                OrderStatus.CONFIRMED,
                OrderStatus.PREPARING,
            }:
                _conflict("order_cannot_be_cancelled", "Заказ уже нельзя отменить")
            await self._restore_points(order, actor=actor, now=current_time)
            previous = order.status
            order.status = OrderStatus.CANCELLED
            order.status_version += 1
            order.cancelled_at = current_time
            for suborder in await self._repository.list_suborders(order.id, for_update=True):
                if suborder.status is not OrderStatus.CANCELLED:
                    suborder_previous = suborder.status
                    suborder.status = OrderStatus.CANCELLED
                    self._repository.add(
                        _event(
                            order,
                            actor,
                            from_status=suborder_previous,
                            to_status=OrderStatus.CANCELLED,
                            suborder_id=suborder.id,
                            reason=normalized_reason,
                            now=current_time,
                        )
                    )
            self._repository.add_all(
                [
                    _event(
                        order,
                        actor,
                        from_status=previous,
                        to_status=OrderStatus.CANCELLED,
                        reason=normalized_reason,
                        now=current_time,
                    ),
                    _order_notification(order, OrderStatus.CANCELLED),
                ]
            )
            await self._repository.flush()
            return await self._repository.aggregate(order)

    async def _resolve_fulfillment(
        self,
        command: OrderCreateCommand,
        *,
        priced: PricingResult,
        now: datetime,
    ) -> _FulfillmentSnapshot:
        settings = await self._repository.get_delivery_settings(lock_mode="share")
        if settings is None:
            _conflict("delivery_settings_missing", "Настройки получения не созданы")
        if command.fulfillment_mode is FulfillmentMode.PICKUP:
            location_id = command.pickup_location_id or settings.default_pickup_location_id
            if location_id is None:
                _validation("pickup_location_required", "Выберите точку получения")
            location = await self._repository.get_pickup_location(location_id)
            if location is None:
                _validation("pickup_location_unavailable", "Точка получения недоступна")
            try:
                validate_operating_hours(
                    now,
                    operating_hours=location.opening_hours,
                    timezone=location.timezone,
                )
            except OrderRuleViolation as exc:
                _rule_error(exc)
            return _FulfillmentSnapshot(
                pickup_location_id=location.id,
                consolidation_location_id=None,
                pickup_name=location.name,
                pickup_address=location.address,
                zone_name=None,
                fee_minor=0,
            )
        if not _clean(command.delivery_address):
            _validation("delivery_address_required", "Укажите адрес доставки")
        if command.delivery_zone_id is None:
            _validation("delivery_zone_required", "Выберите зону доставки")
        zone = await self._repository.get_delivery_zone(command.delivery_zone_id)
        if zone is None:
            _validation("delivery_zone_unavailable", "Зона доставки недоступна")
        if zone.location_id is not None and zone.radius_meters is not None:
            if command.delivery_latitude is None or command.delivery_longitude is None:
                _validation("delivery_coordinates_required", "Поставьте точку адреса на карте")
            center = await self._repository.get_location(zone.location_id)
            if center is None or center.latitude is None or center.longitude is None:
                _conflict(
                    "delivery_zone_not_configured",
                    "У зоны доставки не настроен центр на карте",
                )
            distance = _distance_meters(
                float(center.latitude),
                float(center.longitude),
                command.delivery_latitude,
                command.delivery_longitude,
            )
            if distance > zone.radius_meters:
                _validation(
                    "address_outside_delivery_zone",
                    "Адрес находится за пределами выбранной зоны доставки",
                )
        policy = DeliveryPolicy(
            enabled=settings.delivery_enabled,
            minimum_order_minor=settings.minimum_order_minor,
            fixed_fee_minor=settings.fixed_fee_minor,
            free_delivery_threshold_minor=settings.free_delivery_threshold_minor,
            scheduling_allowed=settings.scheduling_allowed,
            earliest_preparation_minutes=settings.earliest_preparation_minutes,
        )
        try:
            fee = calculate_delivery_fee(
                priced.total_minor,
                policy=policy,
                zone=ZonePolicy(
                    id=zone.id,
                    fee_minor=zone.fee_minor,
                    minimum_order_minor=zone.minimum_order_minor,
                ),
            )
            validate_desired_time(command.desired_delivery_at, now=now, policy=policy)
        except OrderRuleViolation as exc:
            _rule_error(exc)
        location_id = settings.consolidation_location_id or settings.default_pickup_location_id
        if location_id is None:
            _conflict("consolidation_location_missing", "Не настроена точка консолидации")
        location = await self._repository.get_location(location_id)
        if location is None or not location.is_active:
            _conflict("consolidation_location_unavailable", "Точка консолидации недоступна")
        try:
            validate_operating_hours(
                command.desired_delivery_at or now,
                operating_hours=settings.operating_hours,
                timezone=location.timezone,
            )
        except OrderRuleViolation as exc:
            _rule_error(exc)
        return _FulfillmentSnapshot(
            pickup_location_id=None,
            consolidation_location_id=location.id,
            pickup_name=location.name,
            pickup_address=location.address,
            zone_name=zone.name,
            fee_minor=fee,
        )

    async def _redeem_points(
        self,
        actor: Actor,
        *,
        order: CustomerOrder,
        priced: PricingResult,
        commands: tuple[PointRedemptionCommand, ...],
        location_id: UUID | None,
        now: datetime,
    ) -> dict[UUID, int]:
        if not commands:
            return {}
        venue_ids = [value.venue_id for value in commands]
        if len(venue_ids) != len(set(venue_ids)):
            _validation("duplicate_point_redemption", "Баллы заведения указаны дважды")
        settings = await self._ledger_repository.get_settings(lock_mode="share")
        locked = await self._ledger_repository.lock_user_state(actor.user_id)
        if settings is None or locked is None:
            _conflict("loyalty_state_missing", "Балльный счёт недоступен")
        _user, state = locked
        priced_by_venue = {value.venue_id: value for value in priced.venues}
        discounts: dict[UUID, int] = {}
        policy = RedemptionPolicy(
            enabled=settings.points_enabled,
            redemption_minor_units_per_point=settings.redemption_minor_units_per_point,
            minimum_redemption_points=settings.minimum_redemption_points,
            maximum_redemption_percent=settings.maximum_redemption_percent,
            maximum_purchase_minor=settings.maximum_purchase_minor,
        )
        for command in sorted(commands, key=lambda value: str(value.venue_id)):
            venue = priced_by_venue.get(command.venue_id)
            if venue is None:
                _validation(
                    "redemption_venue_not_in_cart",
                    "Баллы можно списать только на товары выбранного заведения",
                )
            wallet_venue_id = (
                None if settings.wallet_mode is WalletMode.SHARED else command.venue_id
            )
            wallet = await self._ledger_repository.get_wallet(
                user_id=actor.user_id,
                venue_id=wallet_venue_id,
                for_update=True,
            )
            available = wallet.balance_points if wallet is not None else 0
            try:
                redemption = calculate_redemption(
                    policy,
                    purchase_amount_minor=venue.total_minor,
                    requested_points=command.points,
                    current_balance_points=available,
                )
            except LoyaltyRuleViolation as exc:
                _validation(exc.code, exc.message)
            operation = LoyaltyOperation(
                id=uuid4(),
                user_id=actor.user_id,
                actor_user_id=actor.user_id,
                actor_staff_id=None,
                location_id=location_id,
                operation_type=LoyaltyOperationType.POINTS_REDEMPTION,
                status=OperationStatus.COMMITTED,
                idempotency_key=f"order:{order.id}:{command.venue_id}",
                request_hash=hashlib.sha256(
                    f"{order.id}:{command.venue_id}:{command.points}".encode()
                ).hexdigest(),
                purchase_amount_minor=venue.total_minor,
                points_delta=-command.points,
                balance_before=state.points_balance,
                balance_after=state.points_balance - command.points,
                reason=f"Оплата заказа #{order.number}",
                occurred_at=now,
            )
            self._repository.add(operation)
            try:
                mutation = await self._ledger.debit_fifo(
                    state=state,
                    settings=settings,
                    operation=operation,
                    points=command.points,
                    venue_id=command.venue_id,
                    now=now,
                )
            except LoyaltyRuleViolation as exc:
                _validation(exc.code, exc.message)
            operation.balance_before = mutation.global_balance_before
            operation.balance_after = mutation.global_balance_after
            state.version += 1
            discounts[command.venue_id] = redemption.discount_minor
            self._repository.add(
                OrderPointRedemption(
                    id=uuid4(),
                    order_id=order.id,
                    venue_id=command.venue_id,
                    loyalty_operation_id=operation.id,
                    points=command.points,
                    discount_minor=redemption.discount_minor,
                )
            )
        return discounts

    async def _snapshot_pricing(
        self,
        order: CustomerOrder,
        *,
        priced: PricingResult,
        point_discounts: dict[UUID, int],
    ) -> None:
        suborders: list[OrderSuborder] = []
        lines: list[OrderLine] = []
        dependents: list[object] = []
        for venue in priced.venues:
            point_discount = point_discounts.get(venue.venue_id, 0)
            suborder = OrderSuborder(
                id=uuid4(),
                order_id=order.id,
                venue_id=venue.venue_id,
                status=OrderStatus.NEW,
                subtotal_minor=venue.subtotal_minor,
                promotion_discount_minor=venue.discount_minor,
                points_discount_minor=point_discount,
                total_minor=venue.total_minor - point_discount,
            )
            suborders.append(suborder)
            point_by_line = allocate_discount(
                point_discount,
                tuple((line.line_id, line.total_minor) for line in venue.lines),
            )
            for sort_order, line in enumerate(venue.lines):
                snapshot_line = OrderLine(
                    id=uuid4(),
                    suborder_id=suborder.id,
                    menu_item_id=line.menu_item_id,
                    client_line_id=line.line_id,
                    item_name=line.item_name,
                    quantity=line.quantity,
                    unit_base_price_minor=line.unit_base_price_minor,
                    unit_modifiers_price_minor=line.unit_modifiers_price_minor,
                    subtotal_minor=line.subtotal_minor,
                    promotion_discount_minor=line.discount_minor,
                    points_discount_minor=point_by_line[line.line_id],
                    total_minor=line.total_minor - point_by_line[line.line_id],
                    sort_order=sort_order,
                )
                lines.append(snapshot_line)
                dependents.extend(
                    OrderLineModifier(
                        id=uuid4(),
                        order_line_id=snapshot_line.id,
                        modifier_option_id=modifier.option_id,
                        group_name=modifier.group_name,
                        option_name=modifier.name,
                        quantity=modifier.quantity,
                        unit_price_delta_minor=modifier.unit_price_delta_minor,
                        total_price_delta_minor=modifier.total_price_delta_minor,
                        sort_order=modifier_order,
                    )
                    for modifier_order, modifier in enumerate(line.modifiers)
                )
            dependents.extend(
                OrderAppliedPromotion(
                    id=uuid4(),
                    suborder_id=suborder.id,
                    promotion_id=promotion.promotion_id,
                    title=promotion.title,
                    priority=promotion.priority,
                    discount_minor=promotion.discount_minor,
                )
                for promotion in venue.promotions
            )
        # These snapshots reference each other only by UUID, not ORM
        # relationships. Explicit flush boundaries guarantee FK-safe insert
        # ordering on PostgreSQL while retaining one outer transaction.
        self._repository.add_all(list(suborders))
        await self._repository.flush()
        self._repository.add_all(list(lines))
        await self._repository.flush()
        self._repository.add_all(dependents)

    async def _restore_points(
        self,
        order: CustomerOrder,
        *,
        actor: Actor,
        now: datetime,
    ) -> None:
        aggregate = await self._repository.aggregate(order)
        if not aggregate.redemptions:
            return
        settings = await self._ledger_repository.get_settings(lock_mode="share")
        locked = await self._ledger_repository.lock_user_state(order.user_id)
        if settings is None or locked is None:
            raise RuntimeError("Order redemption has no loyalty aggregate")
        _user, state = locked
        for redemption in aggregate.redemptions:
            original = await self._ledger_repository.get_operation_by_idempotency(
                operation_type=LoyaltyOperationType.POINTS_REDEMPTION,
                idempotency_key=f"order:{order.id}:{redemption.venue_id}",
            )
            if original is None:
                raise RuntimeError("Order redemption operation is missing")
            reversal = LoyaltyOperation(
                id=uuid4(),
                user_id=order.user_id,
                actor_user_id=actor.user_id,
                actor_staff_id=actor.staff_member_id,
                location_id=original.location_id,
                operation_type=LoyaltyOperationType.OPERATION_REVERSAL,
                status=OperationStatus.COMMITTED,
                idempotency_key=f"order-cancel:{redemption.id}",
                request_hash=hashlib.sha256(f"order-cancel:{redemption.id}".encode()).hexdigest(),
                purchase_amount_minor=original.purchase_amount_minor,
                points_delta=redemption.points,
                balance_before=state.points_balance,
                balance_after=state.points_balance + redemption.points,
                reason=f"Отмена заказа #{order.number}",
                reversal_of_id=original.id,
                occurred_at=now,
            )
            self._repository.add(reversal)
            try:
                mutation = await self._ledger.reverse_spend(
                    state=state,
                    settings=settings,
                    original_operation_id=original.id,
                    reversal=reversal,
                    now=now,
                )
            except LoyaltyRuleViolation as exc:
                _conflict(exc.code, exc.message)
            reversal.balance_before = mutation.global_balance_before
            reversal.balance_after = mutation.global_balance_after
            state.version += 1

    def _audit_transition(
        self,
        actor: Actor,
        *,
        order: CustomerOrder,
        suborder_id: UUID | None,
        from_status: OrderStatus,
        to_status: OrderStatus,
    ) -> None:
        self._repository.add(
            AuditEvent(
                id=uuid4(),
                event_type="order.status_changed",
                actor_user_id=actor.user_id,
                actor_staff_id=actor.staff_member_id,
                object_type="order_suborder" if suborder_id else "customer_order",
                object_id=suborder_id or order.id,
                event_metadata={
                    "order_id": str(order.id),
                    "from": from_status.value,
                    "to": to_status.value,
                },
                severity=AuditSeverity.INFO,
                is_suspicious=False,
            )
        )


@dataclass(frozen=True, slots=True)
class _FulfillmentSnapshot:
    pickup_location_id: UUID | None
    consolidation_location_id: UUID | None
    pickup_name: str | None
    pickup_address: str | None
    zone_name: str | None
    fee_minor: int


def _event(
    order: CustomerOrder,
    actor: Actor,
    *,
    from_status: OrderStatus,
    to_status: OrderStatus,
    now: datetime,
    suborder_id: UUID | None = None,
    reason: str | None = None,
    comment: str | None = None,
) -> OrderEvent:
    return OrderEvent(
        id=uuid4(),
        order_id=order.id,
        suborder_id=suborder_id,
        actor_user_id=actor.user_id,
        actor_staff_id=actor.staff_member_id,
        actor_role=actor.role.value,
        from_status=from_status,
        to_status=to_status,
        reason=_clean(reason),
        comment=_clean(comment),
        created_at=now,
    )


def _order_notification(order: CustomerOrder, target: OrderStatus) -> NotificationOutbox:
    return NotificationOutbox(
        id=uuid4(),
        user_id=order.user_id,
        event_type=f"order.{target.value}",
        payload={"order_id": str(order.id), "order_number": order.number},
        idempotency_key=f"order.status:{order.id}:{order.status_version}:{target.value}",
    )


def _request_hash(command: OrderCreateCommand, *, normalized_phone: str) -> str:
    payload = asdict(command)
    payload["contact_phone"] = normalized_phone
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _clean(value: str | None) -> str | None:
    normalized = " ".join((value or "").split()).strip()
    return normalized or None


def _aware_now(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        _validation("invalid_time", "Время должно содержать часовой пояс")
    return value.astimezone(UTC)


def _require_permission(actor: Actor, permission: PermissionCode) -> None:
    if not actor.can(permission):
        raise AppError(
            code="forbidden",
            message="Недостаточно прав",
            status_code=status.HTTP_403_FORBIDDEN,
        )


def _rule_error(exc: OrderRuleViolation) -> NoReturn:
    _validation(exc.code, exc.message)


def _validation(code: str, message: str) -> NoReturn:
    raise AppError(code=code, message=message, status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)


def _conflict(code: str, message: str) -> NoReturn:
    raise AppError(code=code, message=message, status_code=status.HTTP_409_CONFLICT)


def _not_found(message: str) -> NoReturn:
    raise AppError(code="not_found", message=message, status_code=status.HTTP_404_NOT_FOUND)


def _distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance used for authoritative delivery-radius checks."""

    earth_radius_meters = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    haversine = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * earth_radius_meters * math.atan2(math.sqrt(haversine), math.sqrt(1 - haversine))
