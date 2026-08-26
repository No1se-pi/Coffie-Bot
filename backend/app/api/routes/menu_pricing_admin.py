"""Privileged modifier catalogue and promotion pricing endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models.enums import PermissionCode
from app.repositories.menu_pricing_admin import MenuPricingAdminRepository
from app.schemas.menu_pricing_admin import (
    ModifierGroupInput,
    ModifierGroupListResponse,
    ModifierGroupResponse,
    PromotionRulesInput,
    PromotionRulesResponse,
    modifier_group_response,
    promotion_rules_response,
)
from app.security.rbac import Actor, require_permissions
from app.services.menu_pricing_admin import (
    MenuPricingAdminService,
    ModifierGroupCommand,
    ModifierOptionCommand,
    PromotionRulesCommand,
    RequestMetadata,
)

router = APIRouter(prefix="/admin/pricing", tags=["admin-pricing"])
ContentActor = Annotated[
    Actor,
    Depends(require_permissions(PermissionCode.ADMIN_CONTENT_MANAGE)),
]


def _service(session: AsyncSession) -> MenuPricingAdminService:
    return MenuPricingAdminService(MenuPricingAdminRepository(session))


def _metadata(request: Request) -> RequestMetadata:
    return RequestMetadata(
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )


def _group_command(payload: ModifierGroupInput) -> ModifierGroupCommand:
    return ModifierGroupCommand(
        venue_id=payload.venue_id,
        name=payload.name,
        description=payload.description,
        min_selections=payload.min_selections,
        max_selections=payload.max_selections,
        is_required=payload.required,
        is_enabled=payload.enabled,
        sort_order=payload.sort_order,
        item_ids=frozenset(payload.item_ids),
        options=tuple(
            ModifierOptionCommand(
                id=option.id,
                name=option.name,
                price_delta_minor=option.price_delta_minor,
                allows_quantity=option.allows_quantity,
                max_quantity=option.max_quantity,
                is_enabled=option.enabled,
                sort_order=option.sort_order,
            )
            for option in payload.options
        ),
    )


def _promotion_command(payload: PromotionRulesInput) -> PromotionRulesCommand:
    return PromotionRulesCommand(
        pricing_enabled=payload.pricing_enabled,
        action_type=payload.action_type,
        discount_value=payload.discount_value,
        priority=payload.priority,
        stackable=payload.stackable,
        active_from_date=payload.active_from_date,
        active_to_date=payload.active_to_date,
        active_weekdays=frozenset(payload.active_weekdays),
        active_time_from=payload.active_time_from,
        active_time_to=payload.active_time_to,
        fulfillment_modes=frozenset(payload.fulfillment_modes),
        customer_birthday_only=payload.customer_birthday_only,
        minimum_order_minor=payload.minimum_order_minor,
        category_ids=frozenset(payload.category_ids),
        menu_item_ids=frozenset(payload.menu_item_ids),
    )


@router.get("/modifier-groups", response_model=ModifierGroupListResponse)
async def list_modifier_groups(
    _actor: ContentActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    venue_id: Annotated[UUID | None, Query()] = None,
    include_archived: bool = False,
) -> ModifierGroupListResponse:
    values = await _service(session).list_modifier_groups(
        venue_id=venue_id, include_archived=include_archived
    )
    return ModifierGroupListResponse(items=[modifier_group_response(value) for value in values])


@router.post(
    "/modifier-groups",
    response_model=ModifierGroupResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_modifier_group(
    payload: ModifierGroupInput,
    request: Request,
    actor: ContentActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ModifierGroupResponse:
    value = await _service(session).create_modifier_group(
        actor, _group_command(payload), metadata=_metadata(request)
    )
    return modifier_group_response(value)


@router.put("/modifier-groups/{group_id}", response_model=ModifierGroupResponse)
async def update_modifier_group(
    group_id: UUID,
    payload: ModifierGroupInput,
    request: Request,
    actor: ContentActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ModifierGroupResponse:
    value = await _service(session).update_modifier_group(
        actor, group_id, _group_command(payload), metadata=_metadata(request)
    )
    return modifier_group_response(value)


@router.post("/modifier-groups/{group_id}/archive", response_model=ModifierGroupResponse)
async def archive_modifier_group(
    group_id: UUID,
    request: Request,
    actor: ContentActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ModifierGroupResponse:
    value = await _service(session).set_modifier_group_archived(
        actor, group_id, archived=True, metadata=_metadata(request)
    )
    return modifier_group_response(value)


@router.post("/modifier-groups/{group_id}/restore", response_model=ModifierGroupResponse)
async def restore_modifier_group(
    group_id: UUID,
    request: Request,
    actor: ContentActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ModifierGroupResponse:
    value = await _service(session).set_modifier_group_archived(
        actor, group_id, archived=False, metadata=_metadata(request)
    )
    return modifier_group_response(value)


@router.get("/promotions/{promotion_id}", response_model=PromotionRulesResponse)
async def get_promotion_rules(
    promotion_id: UUID,
    _actor: ContentActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PromotionRulesResponse:
    return promotion_rules_response(await _service(session).get_promotion_rules(promotion_id))


@router.put("/promotions/{promotion_id}", response_model=PromotionRulesResponse)
async def update_promotion_rules(
    promotion_id: UUID,
    payload: PromotionRulesInput,
    request: Request,
    actor: ContentActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PromotionRulesResponse:
    value = await _service(session).update_promotion_rules(
        actor,
        promotion_id,
        _promotion_command(payload),
        metadata=_metadata(request),
    )
    return promotion_rules_response(value)
