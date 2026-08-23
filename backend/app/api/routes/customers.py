"""Phone-only customer creation and identity inspection routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models.enums import PermissionCode
from app.repositories.customers import CustomerRepository
from app.schemas.customers import (
    CustomerIdentityListResponse,
    PhoneCustomerCreate,
    PhoneCustomerResponse,
    customer_identity_list_response,
    phone_customer_response,
)
from app.security.rbac import Actor, get_current_actor, require_permissions
from app.services.customers import CustomerRequestMetadata, CustomerService

router = APIRouter(tags=["customer-identities"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]


def _service(session: AsyncSession) -> CustomerService:
    return CustomerService(CustomerRepository(session))


@router.post(
    "/staff/customers",
    response_model=PhoneCustomerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_phone_customer(
    payload: PhoneCustomerCreate,
    request: Request,
    session: DatabaseSession,
    idempotency_key: IdempotencyKey,
    actor: Annotated[
        Actor,
        Depends(require_permissions(PermissionCode.CUSTOMERS_CREATE)),
    ],
) -> PhoneCustomerResponse:
    value = await _service(session).create_phone_customer(
        actor,
        phone=payload.phone,
        display_name=payload.display_name,
        idempotency_key=str(idempotency_key),
        metadata=CustomerRequestMetadata(
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        ),
    )
    return phone_customer_response(value)


@router.get("/me/identities", response_model=CustomerIdentityListResponse)
async def current_customer_identities(
    session: DatabaseSession,
    actor: Annotated[Actor, Depends(get_current_actor)],
) -> CustomerIdentityListResponse:
    values = await _service(session).list_identities(actor.user_id)
    return customer_identity_list_response(values)


@router.get(
    "/admin/users/{user_id}/identities",
    response_model=CustomerIdentityListResponse,
)
async def admin_customer_identities(
    user_id: UUID,
    session: DatabaseSession,
    _actor: Annotated[
        Actor,
        Depends(require_permissions(PermissionCode.ADMIN_USERS_READ)),
    ],
) -> CustomerIdentityListResponse:
    values = await _service(session).list_identities(user_id)
    return customer_identity_list_response(values)
