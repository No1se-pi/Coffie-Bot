"""Real PostgreSQL coverage for atomic order creation and status history."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.access import User
from app.models.audit import AuditEvent
from app.models.content import Location, MenuCategory, MenuItem, Venue
from app.models.delivery import NotificationOutbox
from app.models.enums import (
    FulfillmentMode,
    OrderStatus,
    PaymentMethod,
    PermissionCode,
    Role,
    UserStatus,
)
from app.models.orders import (
    CustomerOrder,
    DeliverySettings,
    OrderAppliedPromotion,
    OrderEvent,
    OrderLine,
    OrderLineModifier,
    OrderSuborder,
)
from app.repositories.loyalty_v2 import PointLedgerRepository
from app.repositories.orders import OrderRepository
from app.repositories.pricing import PricingRepository
from app.schemas.orders import order_response
from app.security.rbac import Actor
from app.services.orders import OrderCreateCommand, OrderLineCommand, OrderService
from app.services.pricing import CartPricingService


def _database_url() -> str:
    value = os.getenv("DATABASE_URL")
    if not value or not value.startswith("postgresql+asyncpg://"):
        pytest.skip("An async PostgreSQL DATABASE_URL is required")
    return value


def _actor(user_id: UUID, *, staff: bool = False) -> Actor:
    return Actor(
        user_id=user_id,
        telegram_id=1,
        session_id=uuid4(),
        role=Role.STAFF if staff else Role.CUSTOMER,
        staff_member_id=None,
        permissions=(
            frozenset({PermissionCode.ORDERS_READ, PermissionCode.ORDERS_MANAGE})
            if staff
            else frozenset()
        ),
    )


@pytest.mark.asyncio
async def test_order_creation_is_idempotent_and_statuses_are_append_only() -> None:
    engine = create_async_engine(_database_url())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id, venue_id, category_id, item_id, location_id = (uuid4() for _ in range(5))
    original_default = None
    async with sessions() as session, session.begin():
        settings = await session.scalar(
            select(DeliverySettings).where(DeliverySettings.singleton_key == "default")
        )
        assert settings is not None
        original_default = settings.default_pickup_location_id
        session.add_all(
            [
                User(
                    id=user_id,
                    telegram_id=None,
                    first_name="Order customer",
                    status=UserStatus.ACTIVE,
                ),
                Venue(
                    id=venue_id,
                    slug=f"order-{venue_id.hex}",
                    name="Order venue",
                    is_active=True,
                    sort_order=0,
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                MenuCategory(
                    id=category_id,
                    venue_id=venue_id,
                    name="Order category",
                    is_visible=True,
                    sort_order=0,
                ),
                Location(
                    id=location_id,
                    venue_id=venue_id,
                    slug=f"order-location-{location_id.hex}",
                    name="Order pickup",
                    address="Test address",
                    timezone="Europe/Moscow",
                    opening_hours={},
                    is_active=True,
                    pickup_enabled=True,
                    sort_order=0,
                ),
            ]
        )
        await session.flush()
        session.add(
            MenuItem(
                id=item_id,
                venue_id=venue_id,
                category_id=category_id,
                name="Order coffee",
                price_minor=12_500,
                labels=[],
                is_available=True,
                is_visible=True,
                sort_order=0,
            )
        )
        settings.default_pickup_location_id = location_id

    command = OrderCreateCommand(
        fulfillment_mode=FulfillmentMode.PICKUP,
        lines=(OrderLineCommand(uuid4(), item_id, 2, ()),),
        point_redemptions=(),
        pickup_location_id=location_id,
        delivery_zone_id=None,
        contact_phone="+79990000000",
        delivery_address=None,
        entrance=None,
        apartment=None,
        floor=None,
        customer_comment="No sugar",
        desired_delivery_at=None,
        payment_method=PaymentMethod.CARD_ON_RECEIPT,
    )
    key = str(uuid4())

    try:
        async with sessions() as session:
            service = OrderService(
                OrderRepository(session),
                CartPricingService(PricingRepository(session)),
                PointLedgerRepository(session),
            )
            created = await service.create(
                _actor(user_id), command, idempotency_key=key, now=datetime.now(UTC)
            )
            replayed = await service.create(
                _actor(user_id), command, idempotency_key=key, now=datetime.now(UTC)
            )
            assert replayed.idempotent_replay is True
            assert replayed.aggregate.order.id == created.aggregate.order.id
            assert created.aggregate.order.total_minor == 25_000
            assert len(created.aggregate.suborders) == 1

        async with sessions() as session:
            service = OrderService(
                OrderRepository(session),
                CartPricingService(PricingRepository(session)),
                PointLedgerRepository(session),
            )
            confirmed = await service.transition_order(
                _actor(user_id, staff=True),
                created.aggregate.order.id,
                OrderStatus.CONFIRMED,
                reason=None,
                comment="Accepted",
            )
            assert confirmed.order.status is OrderStatus.CONFIRMED
            assert confirmed.suborders[0].status is OrderStatus.CONFIRMED
            assert [event.to_status for event in confirmed.events if event.suborder_id is None] == [
                OrderStatus.NEW,
                OrderStatus.CONFIRMED,
            ]
            # Regression: serialization happens after the service transaction
            # commits, when database-generated updated_at used to trigger an
            # async lazy load and crash with MissingGreenlet in production.
            response = order_response(confirmed)
            assert response.updated_at is not None
    finally:
        async with sessions() as session, session.begin():
            settings = await session.scalar(
                select(DeliverySettings).where(DeliverySettings.singleton_key == "default")
            )
            assert settings is not None
            settings.default_pickup_location_id = original_default
            order_ids = select(CustomerOrder.id).where(CustomerOrder.user_id == user_id)
            suborder_ids = select(OrderSuborder.id).where(OrderSuborder.order_id.in_(order_ids))
            line_ids = select(OrderLine.id).where(OrderLine.suborder_id.in_(suborder_ids))
            # Synthetic test aggregates are removed from leaves to root because
            # production order history intentionally uses RESTRICT FKs.
            await session.execute(
                delete(OrderLineModifier).where(OrderLineModifier.order_line_id.in_(line_ids))
            )
            await session.execute(delete(OrderLine).where(OrderLine.suborder_id.in_(suborder_ids)))
            await session.execute(
                delete(OrderAppliedPromotion).where(
                    OrderAppliedPromotion.suborder_id.in_(suborder_ids)
                )
            )
            await session.execute(delete(OrderEvent).where(OrderEvent.order_id.in_(order_ids)))
            await session.execute(
                delete(OrderSuborder).where(OrderSuborder.order_id.in_(order_ids))
            )
            await session.execute(
                delete(NotificationOutbox).where(NotificationOutbox.user_id == user_id)
            )
            await session.execute(
                delete(AuditEvent).where(
                    AuditEvent.actor_user_id == user_id,
                    AuditEvent.event_type == "order.status_changed",
                )
            )
            await session.execute(delete(CustomerOrder).where(CustomerOrder.user_id == user_id))
            await session.execute(delete(MenuItem).where(MenuItem.id == item_id))
            await session.execute(delete(MenuCategory).where(MenuCategory.id == category_id))
            await session.execute(delete(Location).where(Location.id == location_id))
            await session.execute(delete(Venue).where(Venue.id == venue_id))
            await session.execute(delete(User).where(User.id == user_id))
        await engine.dispose()
