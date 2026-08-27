"""Courier-only delivery endpoints and staff manual assignment."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models.enums import OrderStatus, PermissionCode
from app.repositories.orders import OrderRepository
from app.schemas.couriers import (
    CourierAssignRequest,
    CourierOptionListResponse,
    CourierOrderListResponse,
    CourierOrderResponse,
    courier_option_response,
    courier_order_response,
)
from app.security.rbac import Actor, require_permissions
from app.services.couriers import CourierService

router = APIRouter(tags=["courier-orders"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
CourierReader = Annotated[Actor, Depends(require_permissions(PermissionCode.COURIER_ORDERS_READ))]
CourierClaimer = Annotated[Actor, Depends(require_permissions(PermissionCode.COURIER_ORDERS_CLAIM))]
CourierUpdater = Annotated[
    Actor, Depends(require_permissions(PermissionCode.COURIER_ORDERS_UPDATE))
]
OrderManager = Annotated[Actor, Depends(require_permissions(PermissionCode.ORDERS_MANAGE))]


def _service(session: AsyncSession) -> CourierService:
    return CourierService(OrderRepository(session))


@router.get("/staff/couriers", response_model=CourierOptionListResponse)
async def courier_options(
    actor: OrderManager, session: DatabaseSession
) -> CourierOptionListResponse:
    values = await _service(session).options(actor)
    return CourierOptionListResponse(items=[courier_option_response(value) for value in values])


@router.get("/courier/orders/available", response_model=CourierOrderListResponse)
async def available_orders(
    actor: CourierReader,
    session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> CourierOrderListResponse:
    values = await _service(session).available(actor, limit=limit)
    return CourierOrderListResponse(items=[courier_order_response(value) for value in values])


@router.get("/courier/orders/mine", response_model=CourierOrderListResponse)
async def my_orders(
    actor: CourierReader,
    session: DatabaseSession,
    include_completed: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> CourierOrderListResponse:
    values = await _service(session).mine(actor, include_completed=include_completed, limit=limit)
    return CourierOrderListResponse(items=[courier_order_response(value) for value in values])


@router.get("/courier/orders/{order_id}", response_model=CourierOrderResponse)
async def order_detail(
    order_id: UUID, actor: CourierReader, session: DatabaseSession
) -> CourierOrderResponse:
    return courier_order_response(await _service(session).detail(actor, order_id))


@router.post("/courier/orders/{order_id}/claim", response_model=CourierOrderResponse)
async def claim_order(
    order_id: UUID,
    actor: CourierClaimer,
    session: DatabaseSession,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> CourierOrderResponse:
    return courier_order_response(
        await _service(session).claim(actor, order_id, idempotency_key=str(idempotency_key))
    )


@router.post("/courier/orders/{order_id}/decline", response_model=CourierOrderResponse)
async def decline_order(
    order_id: UUID,
    actor: CourierUpdater,
    session: DatabaseSession,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> CourierOrderResponse:
    return courier_order_response(
        await _service(session).decline(actor, order_id, idempotency_key=str(idempotency_key))
    )


async def _transition(
    order_id: UUID,
    target: OrderStatus,
    actor: Actor,
    session: AsyncSession,
    idempotency_key: UUID,
) -> CourierOrderResponse:
    return courier_order_response(
        await _service(session).transition(
            actor, order_id, target, idempotency_key=str(idempotency_key)
        )
    )


@router.post("/courier/orders/{order_id}/pickup", response_model=CourierOrderResponse)
async def pickup_order(
    order_id: UUID,
    actor: CourierUpdater,
    session: DatabaseSession,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> CourierOrderResponse:
    return await _transition(order_id, OrderStatus.PICKED_UP, actor, session, idempotency_key)


@router.post("/courier/orders/{order_id}/in-transit", response_model=CourierOrderResponse)
async def start_delivery(
    order_id: UUID,
    actor: CourierUpdater,
    session: DatabaseSession,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> CourierOrderResponse:
    return await _transition(order_id, OrderStatus.IN_TRANSIT, actor, session, idempotency_key)


@router.post("/courier/orders/{order_id}/delivered", response_model=CourierOrderResponse)
async def complete_delivery(
    order_id: UUID,
    actor: CourierUpdater,
    session: DatabaseSession,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> CourierOrderResponse:
    return await _transition(order_id, OrderStatus.DELIVERED, actor, session, idempotency_key)


@router.post("/staff/orders/{order_id}/courier", response_model=CourierOrderResponse)
async def assign_courier(
    order_id: UUID,
    payload: CourierAssignRequest,
    actor: OrderManager,
    session: DatabaseSession,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> CourierOrderResponse:
    return courier_order_response(
        await _service(session).assign(
            actor,
            order_id,
            payload.courier_staff_id,
            idempotency_key=str(idempotency_key),
        )
    )
