"""Real PostgreSQL proof that only one courier can claim a delivery."""

from __future__ import annotations

import asyncio
import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.errors import AppError
from app.models.access import StaffMember, User
from app.models.audit import AuditEvent
from app.models.delivery import NotificationOutbox
from app.models.enums import (
    FulfillmentMode,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    PermissionCode,
    Role,
    UserStatus,
)
from app.models.orders import CustomerOrder, OrderEvent
from app.repositories.orders import OrderRepository
from app.security.rbac import Actor
from app.services.couriers import CourierService


def _database_url() -> str:
    value = os.getenv("DATABASE_URL")
    if not value or not value.startswith("postgresql+asyncpg://"):
        pytest.skip("An async PostgreSQL DATABASE_URL is required")
    return value


def _actor(user_id: UUID, staff_id: UUID) -> Actor:
    return Actor(
        user_id=user_id,
        telegram_id=1,
        session_id=uuid4(),
        role=Role.COURIER,
        staff_member_id=staff_id,
        permissions=frozenset(
            {
                PermissionCode.COURIER_ORDERS_READ,
                PermissionCode.COURIER_ORDERS_CLAIM,
                PermissionCode.COURIER_ORDERS_UPDATE,
            }
        ),
    )


@pytest.mark.asyncio
async def test_concurrent_courier_claim_has_exactly_one_winner() -> None:
    engine = create_async_engine(_database_url())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    customer_id, first_user_id, second_user_id = (uuid4() for _ in range(3))
    first_staff_id, second_staff_id, order_id = (uuid4() for _ in range(3))
    async with sessions() as session, session.begin():
        session.add_all(
            [
                User(
                    id=customer_id,
                    telegram_id=None,
                    first_name="Courier test customer",
                    status=UserStatus.ACTIVE,
                ),
                User(
                    id=first_user_id,
                    telegram_id=None,
                    first_name="Courier one",
                    status=UserStatus.ACTIVE,
                ),
                User(
                    id=second_user_id,
                    telegram_id=None,
                    first_name="Courier two",
                    status=UserStatus.ACTIVE,
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                StaffMember(
                    id=first_staff_id,
                    user_id=first_user_id,
                    role=Role.COURIER,
                    is_active=True,
                ),
                StaffMember(
                    id=second_staff_id,
                    user_id=second_user_id,
                    role=Role.COURIER,
                    is_active=True,
                ),
            ]
        )
        await session.flush()
        session.add(
            CustomerOrder(
                id=order_id,
                user_id=customer_id,
                fulfillment_mode=FulfillmentMode.DELIVERY,
                status=OrderStatus.WAITING_FOR_COURIER,
                status_version=1,
                idempotency_key=f"courier-claim-{order_id}",
                request_hash="0" * 64,
                contact_phone="+79990000000",
                delivery_address="Test address",
                subtotal_minor=100,
                promotion_discount_minor=0,
                points_discount_minor=0,
                delivery_fee_minor=0,
                total_minor=100,
                payment_method=PaymentMethod.CASH,
                payment_status=PaymentStatus.UNPAID,
            )
        )

    async def claim(actor: Actor, key: str) -> UUID | str:
        async with sessions() as session:
            try:
                result = await CourierService(OrderRepository(session)).claim(
                    actor, order_id, idempotency_key=key
                )
                return result.order.assigned_courier_staff_id or "missing"
            except AppError as exc:
                return exc.code

    first_actor = _actor(first_user_id, first_staff_id)
    second_actor = _actor(second_user_id, second_staff_id)
    first_key, second_key = str(uuid4()), str(uuid4())
    results = await asyncio.gather(claim(first_actor, first_key), claim(second_actor, second_key))
    assert results.count("order_unavailable") == 1
    winners = [value for value in results if isinstance(value, UUID)]
    assert len(winners) == 1

    winner_actor, winner_key = (
        (first_actor, first_key) if winners[0] == first_staff_id else (second_actor, second_key)
    )
    # A lost HTTP response can be retried safely with the same command key.
    assert await claim(winner_actor, winner_key) == winners[0]

    async with sessions() as session:
        stored = await session.scalar(select(CustomerOrder).where(CustomerOrder.id == order_id))
        assert stored is not None
        assert stored.status is OrderStatus.COURIER_ASSIGNED
        assert stored.assigned_courier_staff_id == winners[0]

    # Append-only dependencies are removed from leaves to root only for this synthetic test data.
    async with sessions() as session, session.begin():
        await session.execute(
            delete(NotificationOutbox).where(NotificationOutbox.user_id == customer_id)
        )
        await session.execute(delete(OrderEvent).where(OrderEvent.order_id == order_id))
        await session.execute(delete(AuditEvent).where(AuditEvent.object_id == order_id))
        await session.execute(delete(CustomerOrder).where(CustomerOrder.id == order_id))
        await session.execute(
            delete(StaffMember).where(StaffMember.id.in_({first_staff_id, second_staff_id}))
        )
        await session.execute(
            delete(User).where(User.id.in_({customer_id, first_user_id, second_user_id}))
        )
    await engine.dispose()
