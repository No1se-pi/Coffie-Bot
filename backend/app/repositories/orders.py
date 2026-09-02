"""PostgreSQL persistence adapter for the customer order aggregate."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.access import StaffMember, User
from app.models.audit import AuditEvent
from app.models.content import Location, Venue
from app.models.enums import FulfillmentMode, OrderStatus, Role
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


@dataclass(frozen=True, slots=True)
class OrderAggregate:
    order: CustomerOrder
    suborders: tuple[OrderSuborder, ...]
    venues: dict[UUID, Venue]
    lines: tuple[OrderLine, ...]
    modifiers: tuple[OrderLineModifier, ...]
    promotions: tuple[OrderAppliedPromotion, ...]
    redemptions: tuple[OrderPointRedemption, ...]
    events: tuple[OrderEvent, ...]


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def transaction(self) -> AbstractAsyncContextManager[None]:
        return self._transaction()

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[None]:
        # Loading the authenticated actor uses this same request-scoped session
        # and may have already started SQLAlchemy's implicit read transaction.
        # Mutations still need one explicit commit/rollback boundary, but must
        # not attempt to nest ``session.begin()`` after that authentication read.
        if not self._session.in_transaction():
            async with self._session.begin():
                yield
            return
        try:
            yield
        except BaseException:
            await self._session.rollback()
            raise
        else:
            await self._session.commit()

    async def acquire_idempotency_lock(self, user_id: UUID, key: str) -> None:
        digest = hashlib.sha256(f"order:{user_id}:{key}".encode()).digest()
        lock_id = int.from_bytes(digest[:8], byteorder="big", signed=True)
        await self._session.execute(select(func.pg_advisory_xact_lock(lock_id)))

    async def get_by_idempotency(self, user_id: UUID, key: str) -> CustomerOrder | None:
        return cast(
            CustomerOrder | None,
            await self._session.scalar(
                select(CustomerOrder).where(
                    CustomerOrder.user_id == user_id,
                    CustomerOrder.idempotency_key == key,
                )
            ),
        )

    async def get_order(
        self,
        order_id: UUID,
        *,
        user_id: UUID | None = None,
        for_update: bool = False,
    ) -> CustomerOrder | None:
        statement = select(CustomerOrder).where(CustomerOrder.id == order_id)
        if user_id is not None:
            statement = statement.where(CustomerOrder.user_id == user_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(CustomerOrder | None, await self._session.scalar(statement))

    async def list_customer_orders(
        self,
        user_id: UUID,
        *,
        active: bool | None,
        limit: int,
    ) -> list[CustomerOrder]:
        statement = select(CustomerOrder).where(CustomerOrder.user_id == user_id)
        terminal = {"delivered", "cancelled"}
        if active is True:
            statement = statement.where(CustomerOrder.status.not_in(terminal))
        elif active is False:
            statement = statement.where(CustomerOrder.status.in_(terminal))
        return list(
            await self._session.scalars(
                statement.order_by(CustomerOrder.created_at.desc(), CustomerOrder.id.desc()).limit(
                    limit
                )
            )
        )

    async def list_staff_orders(
        self,
        *,
        venue_id: UUID | None,
        statuses: set[OrderStatus],
        limit: int,
    ) -> list[CustomerOrder]:
        statement = select(CustomerOrder)
        if venue_id is not None:
            statement = statement.join(
                OrderSuborder, OrderSuborder.order_id == CustomerOrder.id
            ).where(OrderSuborder.venue_id == venue_id)
        if statuses:
            statement = statement.where(CustomerOrder.status.in_(statuses))
        return list(
            await self._session.scalars(
                statement.distinct()
                .order_by(CustomerOrder.created_at, CustomerOrder.id)
                .limit(limit)
            )
        )

    async def list_available_courier_orders(self, *, limit: int) -> list[CustomerOrder]:
        """Return only unclaimed deliveries; private customer fields are serialized elsewhere."""

        return list(
            await self._session.scalars(
                select(CustomerOrder)
                .where(
                    CustomerOrder.fulfillment_mode == FulfillmentMode.DELIVERY,
                    CustomerOrder.status == OrderStatus.WAITING_FOR_COURIER,
                    CustomerOrder.assigned_courier_staff_id.is_(None),
                )
                .order_by(CustomerOrder.created_at, CustomerOrder.id)
                .limit(limit)
            )
        )

    async def list_courier_orders(
        self, courier_staff_id: UUID, *, include_completed: bool, limit: int
    ) -> list[CustomerOrder]:
        statement = select(CustomerOrder).where(
            CustomerOrder.assigned_courier_staff_id == courier_staff_id,
            CustomerOrder.fulfillment_mode == FulfillmentMode.DELIVERY,
        )
        if not include_completed:
            statement = statement.where(
                CustomerOrder.status.not_in({OrderStatus.DELIVERED, OrderStatus.CANCELLED})
            )
        return list(
            await self._session.scalars(
                statement.order_by(CustomerOrder.created_at.desc(), CustomerOrder.id.desc()).limit(
                    limit
                )
            )
        )

    async def get_active_courier(
        self, staff_member_id: UUID, *, for_update: bool = False
    ) -> StaffMember | None:
        statement = select(StaffMember).where(
            StaffMember.id == staff_member_id,
            StaffMember.role == Role.COURIER,
            StaffMember.is_active.is_(True),
            StaffMember.archived_at.is_(None),
        )
        if for_update:
            statement = statement.with_for_update()
        return cast(StaffMember | None, await self._session.scalar(statement))

    async def list_active_couriers(self) -> list[tuple[StaffMember, User]]:
        rows = await self._session.execute(
            select(StaffMember, User)
            .join(User, User.id == StaffMember.user_id)
            .where(
                StaffMember.role == Role.COURIER,
                StaffMember.is_active.is_(True),
                StaffMember.archived_at.is_(None),
            )
            .order_by(StaffMember.display_name, User.first_name, StaffMember.id)
        )
        return [(staff, user) for staff, user in rows.all()]

    async def get_user(self, user_id: UUID) -> User | None:
        return cast(User | None, await self._session.scalar(select(User).where(User.id == user_id)))

    async def get_audit_by_idempotency(self, key: str) -> AuditEvent | None:
        return cast(
            AuditEvent | None,
            await self._session.scalar(select(AuditEvent).where(AuditEvent.idempotency_key == key)),
        )

    async def get_suborder(self, suborder_id: UUID, *, for_update: bool) -> OrderSuborder | None:
        statement = select(OrderSuborder).where(OrderSuborder.id == suborder_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(OrderSuborder | None, await self._session.scalar(statement))

    async def list_suborders(
        self, order_id: UUID, *, for_update: bool = False
    ) -> list[OrderSuborder]:
        statement = (
            select(OrderSuborder)
            .where(OrderSuborder.order_id == order_id)
            .order_by(OrderSuborder.venue_id, OrderSuborder.id)
        )
        if for_update:
            statement = statement.with_for_update()
        return list(await self._session.scalars(statement))

    async def get_delivery_settings(
        self, *, lock_mode: Literal["none", "share", "update"] = "none"
    ) -> DeliverySettings | None:
        statement = select(DeliverySettings).where(DeliverySettings.singleton_key == "default")
        if lock_mode == "share":
            statement = statement.with_for_update(read=True)
        elif lock_mode == "update":
            statement = statement.with_for_update()
        return cast(DeliverySettings | None, await self._session.scalar(statement))

    async def get_delivery_zone(self, zone_id: UUID) -> DeliveryZone | None:
        return cast(
            DeliveryZone | None,
            await self._session.scalar(
                select(DeliveryZone).where(
                    DeliveryZone.id == zone_id,
                    DeliveryZone.is_active.is_(True),
                    DeliveryZone.archived_at.is_(None),
                )
            ),
        )

    async def get_delivery_zone_admin(
        self, zone_id: UUID, *, for_update: bool = False
    ) -> DeliveryZone | None:
        statement = select(DeliveryZone).where(DeliveryZone.id == zone_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(DeliveryZone | None, await self._session.scalar(statement))

    async def list_delivery_zones(self, *, include_archived: bool = False) -> list[DeliveryZone]:
        statement = select(DeliveryZone)
        if not include_archived:
            statement = statement.where(
                DeliveryZone.is_active.is_(True), DeliveryZone.archived_at.is_(None)
            )
        return list(
            await self._session.scalars(
                statement.order_by(DeliveryZone.sort_order, DeliveryZone.name, DeliveryZone.id)
            )
        )

    async def get_pickup_location(self, location_id: UUID) -> Location | None:
        return cast(
            Location | None,
            await self._session.scalar(
                select(Location).where(
                    Location.id == location_id,
                    Location.is_active.is_(True),
                    Location.pickup_enabled.is_(True),
                )
            ),
        )

    async def get_location(self, location_id: UUID, *, for_update: bool = False) -> Location | None:
        statement = select(Location).where(Location.id == location_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(Location | None, await self._session.scalar(statement))

    async def get_location_by_slug(self, slug: str) -> Location | None:
        return cast(
            Location | None,
            await self._session.scalar(select(Location).where(Location.slug == slug)),
        )

    async def get_venue(self, venue_id: UUID) -> Venue | None:
        return cast(
            Venue | None,
            await self._session.scalar(
                select(Venue).where(
                    Venue.id == venue_id,
                    Venue.is_active.is_(True),
                    Venue.archived_at.is_(None),
                )
            ),
        )

    async def list_locations(self) -> list[Location]:
        return list(
            await self._session.scalars(
                select(Location).order_by(Location.sort_order, Location.name, Location.id)
            )
        )

    async def list_pickup_locations(self) -> list[Location]:
        return list(
            await self._session.scalars(
                select(Location)
                .where(Location.is_active.is_(True), Location.pickup_enabled.is_(True))
                .order_by(Location.is_default.desc(), Location.sort_order, Location.id)
            )
        )

    async def aggregate(self, order: CustomerOrder) -> OrderAggregate:
        # Database-generated timestamps may be expired by SQLAlchemy after an
        # UPDATE flush.  Load them while we are still in the async repository
        # boundary so response serialization never attempts implicit I/O.
        await self._session.refresh(order)
        suborders = tuple(await self.list_suborders(order.id))
        suborder_ids = {value.id for value in suborders}
        venue_ids = {value.venue_id for value in suborders}
        venues = {
            venue.id: venue
            for venue in await self._session.scalars(select(Venue).where(Venue.id.in_(venue_ids)))
        }
        lines = tuple(
            await self._session.scalars(
                select(OrderLine)
                .where(OrderLine.suborder_id.in_(suborder_ids))
                .order_by(OrderLine.suborder_id, OrderLine.sort_order, OrderLine.id)
            )
        )
        line_ids = {value.id for value in lines}
        modifiers = tuple(
            await self._session.scalars(
                select(OrderLineModifier)
                .where(OrderLineModifier.order_line_id.in_(line_ids))
                .order_by(
                    OrderLineModifier.order_line_id,
                    OrderLineModifier.sort_order,
                    OrderLineModifier.id,
                )
            )
        )
        promotions = tuple(
            await self._session.scalars(
                select(OrderAppliedPromotion)
                .where(OrderAppliedPromotion.suborder_id.in_(suborder_ids))
                .order_by(OrderAppliedPromotion.suborder_id, OrderAppliedPromotion.id)
            )
        )
        redemptions = tuple(
            await self._session.scalars(
                select(OrderPointRedemption)
                .where(OrderPointRedemption.order_id == order.id)
                .order_by(OrderPointRedemption.venue_id, OrderPointRedemption.id)
            )
        )
        events = tuple(
            await self._session.scalars(
                select(OrderEvent)
                .where(OrderEvent.order_id == order.id)
                .order_by(OrderEvent.created_at, OrderEvent.id)
            )
        )
        return OrderAggregate(
            order=order,
            suborders=suborders,
            venues=venues,
            lines=lines,
            modifiers=modifiers,
            promotions=promotions,
            redemptions=redemptions,
            events=events,
        )

    def add(self, value: object) -> None:
        self._session.add(value)

    def add_all(self, values: list[object]) -> None:
        self._session.add_all(values)

    async def flush(self) -> None:
        await self._session.flush()
