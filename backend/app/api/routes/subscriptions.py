"""Customer/staff/admin endpoints for reusable non-payment passes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models.enums import PermissionCode, Role
from app.repositories.subscriptions import SubscriptionRepository
from app.schemas.subscriptions import (
    CustomerPassListResponse,
    CustomerPassResponse,
    PassCancelRequest,
    PassIssueRequest,
    PassPurchaseCreateRequest,
    PassPurchaseListResponse,
    PassPurchaseResponse,
    PassTemplateCreateRequest,
    PassTemplateListResponse,
    PassTemplateResponse,
    PassUsageResponse,
    PassUseRequest,
    pass_response,
    purchase_response,
    template_response,
    usage_response,
)
from app.security.rbac import Actor, get_current_actor, require_permissions, require_roles
from app.services.subscriptions import SubscriptionService, TemplateCreateCommand

router = APIRouter(tags=["subscriptions"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]
CurrentActor = Annotated[Actor, Depends(get_current_actor)]
PassReader = Annotated[Actor, Depends(require_permissions(PermissionCode.SUBSCRIPTIONS_READ))]
PassManager = Annotated[Actor, Depends(require_permissions(PermissionCode.SUBSCRIPTIONS_MANAGE))]
PassAdmin = Annotated[Actor, Depends(require_roles(Role.ADMIN, Role.OWNER))]


def _service(session: AsyncSession) -> SubscriptionService:
    return SubscriptionService(SubscriptionRepository(session))


@router.get("/me/subscriptions", response_model=CustomerPassListResponse)
async def my_passes(actor: CurrentActor, session: DatabaseSession) -> CustomerPassListResponse:
    values = await _service(session).list_mine(actor)
    return CustomerPassListResponse(items=[pass_response(value) for value in values])


@router.get("/subscription-products", response_model=PassTemplateListResponse)
async def subscription_products(
    actor: CurrentActor, session: DatabaseSession
) -> PassTemplateListResponse:
    values = await _service(session).list_storefront(actor)
    return PassTemplateListResponse(items=[template_response(value) for value in values])


@router.post(
    "/subscription-purchases",
    response_model=PassPurchaseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def purchase_subscription(
    payload: PassPurchaseCreateRequest,
    actor: CurrentActor,
    session: DatabaseSession,
    idempotency_key: IdempotencyKey,
) -> PassPurchaseResponse:
    return purchase_response(
        await _service(session).purchase(
            actor,
            template_id=payload.template_id,
            payment_method=payload.payment_method,
            idempotency_key=str(idempotency_key),
        )
    )


@router.get("/me/subscription-purchases", response_model=PassPurchaseListResponse)
async def my_subscription_purchases(
    actor: CurrentActor, session: DatabaseSession
) -> PassPurchaseListResponse:
    values = await _service(session).list_my_purchases(actor)
    return PassPurchaseListResponse(items=[purchase_response(value) for value in values])


@router.get("/staff/subscription-purchases", response_model=PassPurchaseListResponse)
async def pending_subscription_purchases(
    actor: PassManager, session: DatabaseSession
) -> PassPurchaseListResponse:
    values = await _service(session).list_pending_purchases(actor)
    return PassPurchaseListResponse(items=[purchase_response(value) for value in values])


@router.post(
    "/staff/subscription-purchases/{purchase_id}/confirm",
    response_model=PassPurchaseResponse,
)
async def confirm_subscription_purchase(
    purchase_id: UUID, actor: PassManager, session: DatabaseSession
) -> PassPurchaseResponse:
    return purchase_response(await _service(session).confirm_purchase(actor, purchase_id))


@router.get("/staff/customers/{user_id}/subscriptions", response_model=CustomerPassListResponse)
async def customer_passes(
    user_id: UUID, actor: PassReader, session: DatabaseSession
) -> CustomerPassListResponse:
    values = await _service(session).list_customer(actor, user_id)
    return CustomerPassListResponse(items=[pass_response(value) for value in values])


@router.post("/staff/subscriptions/{pass_id}/use", response_model=PassUsageResponse)
async def use_pass(
    pass_id: UUID,
    payload: PassUseRequest,
    actor: PassManager,
    session: DatabaseSession,
    idempotency_key: IdempotencyKey,
) -> PassUsageResponse:
    return usage_response(
        await _service(session).use(
            actor,
            pass_id=pass_id,
            venue_id=payload.venue_id,
            item_id=payload.item_id,
            idempotency_key=str(idempotency_key),
        )
    )


@router.get("/admin/subscriptions/templates", response_model=PassTemplateListResponse)
async def templates(
    actor: PassAdmin,
    session: DatabaseSession,
    active_only: Annotated[bool, Query()] = False,
) -> PassTemplateListResponse:
    values = await _service(session).list_templates(actor, active_only=active_only)
    return PassTemplateListResponse(items=[template_response(value) for value in values])


@router.post(
    "/admin/subscriptions/templates",
    response_model=PassTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_template(
    payload: PassTemplateCreateRequest, actor: PassAdmin, session: DatabaseSession
) -> PassTemplateResponse:
    value = await _service(session).create_template(
        actor,
        TemplateCreateCommand(
            name=payload.name,
            description=payload.description,
            image_media_id=payload.image_media_id,
            total_uses=payload.total_uses,
            validity_days=payload.validity_days,
            price_minor=payload.price_minor,
            purchase_enabled=payload.purchase_enabled,
            venue_ids=frozenset(payload.venue_ids),
            category_ids=frozenset(payload.category_ids),
            item_ids=frozenset(payload.item_ids),
        ),
    )
    return template_response(value)


@router.post(
    "/admin/subscriptions/templates/{template_id}/archive", response_model=PassTemplateResponse
)
async def archive_template(
    template_id: UUID, actor: PassAdmin, session: DatabaseSession
) -> PassTemplateResponse:
    return template_response(await _service(session).archive_template(actor, template_id))


@router.post("/admin/subscriptions/issue", response_model=CustomerPassResponse, status_code=201)
async def issue_pass(
    payload: PassIssueRequest,
    actor: PassAdmin,
    session: DatabaseSession,
    idempotency_key: IdempotencyKey,
) -> CustomerPassResponse:
    return pass_response(
        await _service(session).issue(
            actor,
            user_id=payload.user_id,
            template_id=payload.template_id,
            idempotency_key=str(idempotency_key),
        )
    )


@router.post("/admin/subscriptions/{pass_id}/cancel", response_model=CustomerPassResponse)
async def cancel_pass(
    pass_id: UUID,
    payload: PassCancelRequest,
    actor: PassAdmin,
    session: DatabaseSession,
    idempotency_key: IdempotencyKey,
) -> CustomerPassResponse:
    return pass_response(
        await _service(session).cancel(
            actor,
            pass_id,
            reason=payload.reason,
            idempotency_key=str(idempotency_key),
        )
    )
