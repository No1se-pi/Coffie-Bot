"""Courier delivery workflow with row-locked claims and privacy boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NoReturn
from uuid import UUID, uuid4

from fastapi import status

from app.core.errors import AppError
from app.models.access import User
from app.models.audit import AuditEvent
from app.models.delivery import NotificationOutbox
from app.models.enums import AuditSeverity, FulfillmentMode, OrderStatus, PermissionCode, Role
from app.models.orders import CustomerOrder, OrderEvent
from app.repositories.orders import OrderRepository
from app.security.rbac import Actor
from app.services.order_rules import OrderRuleViolation, require_transition


@dataclass(frozen=True, slots=True)
class CourierOrderView:
    order: CustomerOrder
    customer: User | None
    venue_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CourierOption:
    id: UUID
    display_name: str


class CourierService:
    """Keep courier actions narrow; no loyalty, audit history, or Telegram identity leaks."""

    def __init__(self, repository: OrderRepository) -> None:
        self._repository = repository

    async def available(self, actor: Actor, *, limit: int) -> list[CourierOrderView]:
        self._require_courier(actor, PermissionCode.COURIER_ORDERS_READ)
        orders = await self._repository.list_available_courier_orders(limit=limit)
        return [await self._view(order, private=False) for order in orders]

    async def options(self, actor: Actor) -> list[CourierOption]:
        """Give order managers only the identity needed for manual assignment."""

        _require_permission(actor, PermissionCode.ORDERS_MANAGE)
        rows = await self._repository.list_active_couriers()
        return [
            CourierOption(
                id=staff.id,
                display_name=staff.display_name
                or " ".join(part for part in (user.first_name, user.last_name) if part),
            )
            for staff, user in rows
        ]

    async def mine(
        self, actor: Actor, *, include_completed: bool, limit: int
    ) -> list[CourierOrderView]:
        courier_id = self._require_courier(actor, PermissionCode.COURIER_ORDERS_READ)
        orders = await self._repository.list_courier_orders(
            courier_id, include_completed=include_completed, limit=limit
        )
        return [await self._view(order, private=True) for order in orders]

    async def detail(self, actor: Actor, order_id: UUID) -> CourierOrderView:
        courier_id = self._require_courier(actor, PermissionCode.COURIER_ORDERS_READ)
        order = await self._repository.get_order(order_id)
        if order is None or order.assigned_courier_staff_id != courier_id:
            _not_found()
        return await self._view(order, private=True)

    async def claim(
        self, actor: Actor, order_id: UUID, *, idempotency_key: str
    ) -> CourierOrderView:
        courier_id = self._require_courier(actor, PermissionCode.COURIER_ORDERS_CLAIM)
        async with self._repository.transaction():
            order = await self._repository.get_order(order_id, for_update=True)
            if order is None:
                _not_found()
            replay = await self._replay(actor, order, "order.courier_claimed", idempotency_key)
            if replay is not None:
                return replay
            if (
                order.fulfillment_mode is not FulfillmentMode.DELIVERY
                or order.status is not OrderStatus.WAITING_FOR_COURIER
                or order.assigned_courier_staff_id is not None
            ):
                _conflict("order_unavailable", "Заказ уже недоступен для назначения")
            order.assigned_courier_staff_id = courier_id
            self._change_status(order, actor, OrderStatus.COURIER_ASSIGNED, "Курьер принял заказ")
            self._audit(
                order,
                actor,
                "order.courier_claimed",
                courier_id,
                idempotency_key=idempotency_key,
            )
            await self._repository.flush()
            return await self._view(order, private=True)

    async def assign(
        self,
        actor: Actor,
        order_id: UUID,
        courier_id: UUID,
        *,
        idempotency_key: str,
    ) -> CourierOrderView:
        _require_permission(actor, PermissionCode.ORDERS_MANAGE)
        async with self._repository.transaction():
            courier = await self._repository.get_active_courier(courier_id, for_update=True)
            if courier is None:
                raise AppError(
                    code="courier_not_found",
                    message="Активный курьер не найден",
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                )
            order = await self._repository.get_order(order_id, for_update=True)
            if order is None:
                _not_found()
            replay = await self._replay(actor, order, "order.courier_assigned", idempotency_key)
            if replay is not None:
                return replay
            if order.fulfillment_mode is not FulfillmentMode.DELIVERY or order.status not in {
                OrderStatus.WAITING_FOR_COURIER,
                OrderStatus.COURIER_ASSIGNED,
            }:
                _conflict("courier_assignment_forbidden", "На этом этапе назначить курьера нельзя")
            previous_courier = order.assigned_courier_staff_id
            order.assigned_courier_staff_id = courier.id
            if order.status is OrderStatus.WAITING_FOR_COURIER:
                self._change_status(
                    order, actor, OrderStatus.COURIER_ASSIGNED, "Курьер назначен сотрудником"
                )
            else:
                order.status_version += 1
            self._audit(
                order,
                actor,
                "order.courier_assigned",
                courier.id,
                previous_courier_id=previous_courier,
                idempotency_key=idempotency_key,
            )
            self._repository.add(
                _courier_notification(order, courier.user_id, event_type="courier.order.assigned")
            )
            await self._repository.flush()
            return await self._view(order, private=True)

    async def decline(
        self, actor: Actor, order_id: UUID, *, idempotency_key: str
    ) -> CourierOrderView:
        courier_id = self._require_courier(actor, PermissionCode.COURIER_ORDERS_UPDATE)
        async with self._repository.transaction():
            order = await self._repository.get_order(order_id, for_update=True)
            if order is None:
                _not_found()
            replay = await self._replay(actor, order, "order.courier_declined", idempotency_key)
            if replay is not None:
                return replay
            self._require_owned(order, courier_id)
            if order.status is not OrderStatus.COURIER_ASSIGNED:
                _conflict("courier_decline_forbidden", "После получения заказа отказаться нельзя")
            self._change_status(order, actor, OrderStatus.WAITING_FOR_COURIER, "Курьер отказался")
            order.assigned_courier_staff_id = None
            self._audit(
                order,
                actor,
                "order.courier_declined",
                courier_id,
                idempotency_key=idempotency_key,
            )
            # A declined order returns to the shared queue, so every active
            # courier gets the same availability alert without customer data.
            for _staff, user in await self._repository.list_active_couriers():
                self._repository.add(
                    _courier_notification(order, user.id, event_type="courier.order.available")
                )
            await self._repository.flush()
            # The returned public view deliberately hides the now-unassigned customer's details.
            return await self._view(order, private=False)

    async def transition(
        self,
        actor: Actor,
        order_id: UUID,
        target: OrderStatus,
        *,
        idempotency_key: str,
    ) -> CourierOrderView:
        courier_id = self._require_courier(actor, PermissionCode.COURIER_ORDERS_UPDATE)
        if target not in {OrderStatus.PICKED_UP, OrderStatus.IN_TRANSIT, OrderStatus.DELIVERED}:
            _conflict("courier_transition_forbidden", "Курьеру недоступен этот статус")
        async with self._repository.transaction():
            order = await self._repository.get_order(order_id, for_update=True)
            if order is None:
                _not_found()
            replay = await self._replay(
                actor, order, "order.courier_status_changed", idempotency_key
            )
            if replay is not None:
                return replay
            self._require_owned(order, courier_id)
            self._change_status(order, actor, target, "Статус обновлён курьером")
            if target is OrderStatus.DELIVERED:
                order.completed_at = datetime.now(UTC)
            self._audit(
                order,
                actor,
                "order.courier_status_changed",
                courier_id,
                idempotency_key=idempotency_key,
            )
            await self._repository.flush()
            return await self._view(order, private=True)

    @staticmethod
    def _require_owned(order: CustomerOrder, courier_id: UUID) -> None:
        if order.assigned_courier_staff_id != courier_id:
            _not_found()

    async def _replay(
        self,
        actor: Actor,
        order: CustomerOrder,
        event_type: str,
        raw_key: str,
    ) -> CourierOrderView | None:
        key = self._audit_key(actor, raw_key)
        existing = await self._repository.get_audit_by_idempotency(key)
        if existing is None:
            return None
        if (
            existing.event_type != event_type
            or existing.object_id != order.id
            or existing.actor_user_id != actor.user_id
        ):
            _conflict("idempotency_mismatch", "Ключ уже использован для другой команды")
        private = event_type != "order.courier_declined"
        return await self._view(order, private=private)

    async def _view(self, order: CustomerOrder, *, private: bool) -> CourierOrderView:
        aggregate = await self._repository.aggregate(order)
        customer = await self._repository.get_user(order.user_id) if private else None
        names = tuple(aggregate.venues[value.venue_id].name for value in aggregate.suborders)
        return CourierOrderView(order=order, customer=customer, venue_names=names)

    def _change_status(
        self, order: CustomerOrder, actor: Actor, target: OrderStatus, comment: str
    ) -> None:
        previous = order.status
        try:
            require_transition(previous, target)
        except OrderRuleViolation as exc:
            _conflict(exc.code, exc.message)
        order.status = target
        order.status_version += 1
        now = datetime.now(UTC)
        self._repository.add_all(
            [
                OrderEvent(
                    id=uuid4(),
                    order_id=order.id,
                    actor_user_id=actor.user_id,
                    actor_staff_id=actor.staff_member_id,
                    actor_role=actor.role.value,
                    from_status=previous,
                    to_status=target,
                    comment=comment,
                    created_at=now,
                ),
                NotificationOutbox(
                    id=uuid4(),
                    user_id=order.user_id,
                    event_type=f"order.{target.value}",
                    payload={"order_id": str(order.id), "order_number": order.number},
                    idempotency_key=(
                        f"order.status:{order.id}:{order.status_version}:{target.value}"
                    ),
                ),
            ]
        )

    def _audit(
        self,
        order: CustomerOrder,
        actor: Actor,
        event_type: str,
        courier_id: UUID,
        *,
        previous_courier_id: UUID | None = None,
        idempotency_key: str,
    ) -> None:
        metadata = {
            "order_id": str(order.id),
            "courier_staff_id": str(courier_id),
            # Keeping the resulting status in the immutable audit row lets the
            # admin log explain the action without reconstructing old state.
            "status": order.status.value,
        }
        if previous_courier_id is not None:
            metadata["previous_courier_staff_id"] = str(previous_courier_id)
        self._repository.add(
            AuditEvent(
                id=uuid4(),
                event_type=event_type,
                actor_user_id=actor.user_id,
                actor_staff_id=actor.staff_member_id,
                object_type="customer_order",
                object_id=order.id,
                idempotency_key=self._audit_key(actor, idempotency_key),
                event_metadata=metadata,
                severity=AuditSeverity.INFO,
                is_suspicious=False,
            )
        )

    @staticmethod
    def _audit_key(actor: Actor, raw_key: str) -> str:
        return f"courier-command:{actor.user_id}:{raw_key}"

    @staticmethod
    def _require_courier(actor: Actor, permission: PermissionCode) -> UUID:
        if (
            actor.role is not Role.COURIER
            or actor.staff_member_id is None
            or not actor.can(permission)
        ):
            raise AppError(code="forbidden", message="Недостаточно прав", status_code=403)
        return actor.staff_member_id


def _require_permission(actor: Actor, permission: PermissionCode) -> None:
    if not actor.can(permission):
        raise AppError(code="forbidden", message="Недостаточно прав", status_code=403)


def _courier_notification(
    order: CustomerOrder, user_id: UUID, *, event_type: str
) -> NotificationOutbox:
    return NotificationOutbox(
        id=uuid4(),
        user_id=user_id,
        event_type=event_type,
        payload={"order_id": str(order.id), "order_number": order.number},
        idempotency_key=f"{event_type}:{order.id}:{order.status_version}:{user_id}",
    )


def _not_found() -> NoReturn:
    raise AppError(code="not_found", message="Заказ не найден", status_code=404)


def _conflict(code: str, message: str) -> NoReturn:
    raise AppError(code=code, message=message, status_code=409)
