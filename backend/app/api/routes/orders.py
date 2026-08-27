"""Customer and staff order HTTP endpoints backed by one transactional service."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models.enums import OrderStatus, PermissionCode
from app.repositories.loyalty_v2 import PointLedgerRepository
from app.repositories.orders import OrderRepository
from app.repositories.pricing import PricingRepository
from app.schemas.orders import (
    OrderCancelRequest,
    OrderCreateRequest,
    OrderListResponse,
    OrderOptionsResponse,
    OrderResponse,
    OrderTransitionRequest,
    order_options_response,
    order_response,
)
from app.security.rbac import Actor, get_current_actor, require_permissions
from app.services.orders import (
    OrderCreateCommand,
    OrderLineCommand,
    OrderService,
    PointRedemptionCommand,
)
from app.services.pricing import CartPricingService, RequestedModifier

router = APIRouter(tags=["orders"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
CurrentActor = Annotated[Actor, Depends(get_current_actor)]
OrderReader = Annotated[Actor, Depends(require_permissions(PermissionCode.ORDERS_READ))]
OrderManager = Annotated[Actor, Depends(require_permissions(PermissionCode.ORDERS_MANAGE))]


def _service(session: AsyncSession) -> OrderService:
    """Build the modular-monolith service from request-scoped repositories."""

    return OrderService(
        OrderRepository(session),
        CartPricingService(PricingRepository(session)),
        PointLedgerRepository(session),
    )


@router.get("/order-options", response_model=OrderOptionsResponse)
async def get_order_options(
    _actor: CurrentActor,
    session: DatabaseSession,
) -> OrderOptionsResponse:
    return order_options_response(await _service(session).get_options())


@router.post("/orders", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: OrderCreateRequest,
    actor: CurrentActor,
    session: DatabaseSession,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> OrderResponse:
    command = OrderCreateCommand(
        fulfillment_mode=payload.fulfillment_mode,
        lines=tuple(
            OrderLineCommand(
                line_id=line.line_id,
                menu_item_id=line.menu_item_id,
                quantity=line.quantity,
                modifiers=tuple(
                    RequestedModifier(
                        option_id=modifier.option_id,
                        quantity=modifier.quantity,
                    )
                    for modifier in line.modifiers
                ),
            )
            for line in payload.lines
        ),
        point_redemptions=tuple(
            PointRedemptionCommand(venue_id=value.venue_id, points=value.points)
            for value in payload.point_redemptions
        ),
        pickup_location_id=payload.pickup_location_id,
        delivery_zone_id=payload.delivery_zone_id,
        contact_phone=payload.contact_phone,
        delivery_address=payload.delivery_address,
        entrance=payload.entrance,
        apartment=payload.apartment,
        floor=payload.floor,
        customer_comment=payload.customer_comment,
        desired_delivery_at=payload.desired_delivery_at,
        payment_method=payload.payment_method,
    )
    outcome = await _service(session).create(
        actor,
        command,
        idempotency_key=str(idempotency_key),
    )
    return order_response(
        outcome.aggregate,
        idempotent_replay=outcome.idempotent_replay,
    )


@router.get("/orders", response_model=OrderListResponse)
async def list_my_orders(
    actor: CurrentActor,
    session: DatabaseSession,
    active: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> OrderListResponse:
    values = await _service(session).list_customer_orders(actor, active=active, limit=limit)
    return OrderListResponse(items=[order_response(value) for value in values])


@router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_my_order(
    order_id: UUID,
    actor: CurrentActor,
    session: DatabaseSession,
) -> OrderResponse:
    return order_response(await _service(session).get_customer_order(actor, order_id))


@router.post("/orders/{order_id}/cancel", response_model=OrderResponse)
async def cancel_my_order(
    order_id: UUID,
    payload: OrderCancelRequest,
    actor: CurrentActor,
    session: DatabaseSession,
) -> OrderResponse:
    value = await _service(session).cancel_customer_order(actor, order_id, reason=payload.reason)
    return order_response(value)


@router.get("/staff/orders", response_model=OrderListResponse, tags=["staff-orders"])
async def list_staff_orders(
    actor: OrderReader,
    session: DatabaseSession,
    venue_id: Annotated[UUID | None, Query()] = None,
    statuses: Annotated[list[OrderStatus] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> OrderListResponse:
    values = await _service(session).list_staff_orders(
        actor,
        venue_id=venue_id,
        statuses=set(statuses or []),
        limit=limit,
    )
    return OrderListResponse(items=[order_response(value) for value in values])


@router.get("/staff/orders/{order_id}", response_model=OrderResponse, tags=["staff-orders"])
async def get_staff_order(
    order_id: UUID,
    actor: OrderReader,
    session: DatabaseSession,
) -> OrderResponse:
    return order_response(await _service(session).get_staff_order(actor, order_id))


@router.post(
    "/staff/orders/{order_id}/transition",
    response_model=OrderResponse,
    tags=["staff-orders"],
)
async def transition_order(
    order_id: UUID,
    payload: OrderTransitionRequest,
    actor: OrderManager,
    session: DatabaseSession,
) -> OrderResponse:
    value = await _service(session).transition_order(
        actor,
        order_id,
        payload.status,
        reason=payload.reason,
        comment=payload.comment,
    )
    return order_response(value)


@router.post(
    "/staff/suborders/{suborder_id}/transition",
    response_model=OrderResponse,
    tags=["staff-orders"],
)
async def transition_suborder(
    suborder_id: UUID,
    payload: OrderTransitionRequest,
    actor: OrderManager,
    session: DatabaseSession,
) -> OrderResponse:
    value = await _service(session).transition_suborder(
        actor,
        suborder_id,
        payload.status,
        reason=payload.reason,
        comment=payload.comment,
    )
    return order_response(value)
