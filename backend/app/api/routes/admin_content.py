"""Admin loyalty settings, menu, promotions, and feedback routes."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models.enums import FeedbackStatus, PermissionCode, PromotionStatus
from app.repositories.admin import AdminRepository
from app.schemas.admin import (
    FeedbackAdminResponse,
    FeedbackListResponse,
    FeedbackUpdate,
    LoyaltySettingsResponse,
    LoyaltySettingsUpdate,
    MenuCategoryCreate,
    MenuCategoryListResponse,
    MenuCategoryResponse,
    MenuCategoryUpdate,
    MenuItemCreate,
    MenuItemListResponse,
    MenuItemResponse,
    MenuItemUpdate,
    PromotionCreate,
    PromotionListResponse,
    PromotionResponse,
    PromotionUpdate,
    boundary_minutes,
    feedback_list_response,
    feedback_response,
    loyalty_settings_response,
    menu_category_list_response,
    menu_category_response,
    menu_item_list_response,
    menu_item_response,
    promotion_list_response,
    promotion_response,
)
from app.security.rbac import Actor, require_permissions
from app.services.admin import AdminService, RequestMetadata

router = APIRouter(prefix="/admin", tags=["admin-content"])


def _service(session: AsyncSession) -> AdminService:
    return AdminService(repository=AdminRepository(session))


def _metadata(request: Request) -> RequestMetadata:
    return RequestMetadata(
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )


SettingsActor = Annotated[
    Actor,
    Depends(require_permissions(PermissionCode.ADMIN_SETTINGS_MANAGE)),
]
ContentActor = Annotated[
    Actor,
    Depends(require_permissions(PermissionCode.ADMIN_CONTENT_MANAGE)),
]
FeedbackActor = Annotated[
    Actor,
    Depends(require_permissions(PermissionCode.ADMIN_FEEDBACK_MANAGE)),
]


@router.get("/loyalty-settings", response_model=LoyaltySettingsResponse)
async def get_loyalty_settings(
    _actor: SettingsActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> LoyaltySettingsResponse:
    return loyalty_settings_response(await _service(session).get_loyalty_settings())


@router.put("/loyalty-settings", response_model=LoyaltySettingsResponse)
async def put_loyalty_settings(
    payload: LoyaltySettingsUpdate,
    request: Request,
    actor: SettingsActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> LoyaltySettingsResponse:
    settings = await _service(session).update_loyalty_settings(
        actor=actor,
        points_enabled=payload.points_enabled,
        currency_name=payload.currency_name,
        rubles_per_point=payload.rubles_per_point,
        redemption_rubles_per_point=payload.redemption_rubles_per_point,
        minimum_purchase_minor=payload.minimum_purchase_minor,
        maximum_purchase_minor=payload.maximum_purchase_minor,
        rounding=payload.rounding.value,
        max_redemption_percent=payload.max_redemption_percent,
        minimum_redemption_points=payload.minimum_redemption_points,
        welcome_bonus_points=payload.welcome_bonus_points,
        points_validity_days=payload.points_validity_days,
        daily_accrual_limit_points=payload.daily_accrual_limit_points,
        operation_accrual_limit_points=payload.operation_accrual_limit_points,
        large_operation_threshold_minor=payload.large_operation_threshold_minor,
        large_operation_requires_approval=payload.large_operation_requires_approval,
        visit_enabled=payload.visit_enabled,
        visit_goal=payload.visit_goal,
        visits_must_be_consecutive=payload.visits_must_be_consecutive,
        visit_daily_limit=payload.visit_daily_limit,
        timezone=payload.timezone,
        business_day_boundary_minutes=boundary_minutes(payload.business_day_boundary),
        visit_allowed_misses=payload.visit_allowed_misses,
        visit_reset_on_miss=payload.visit_reset_on_miss,
        visit_reward_validity_days=payload.visit_reward_validity_days,
        visit_restart_cycle=payload.visit_restart_cycle,
        stamps_enabled=payload.stamps_enabled,
        stamp_goal=payload.stamp_goal,
        stamps_per_purchase=payload.stamps_per_purchase,
        stamp_operation_limit=payload.stamp_operation_limit,
        stamp_reward_validity_days=payload.stamp_reward_validity_days,
        reset_stamps_after_reward=payload.reset_stamps_after_reward,
        metadata=_metadata(request),
    )
    return loyalty_settings_response(settings)


@router.get("/menu/categories", response_model=MenuCategoryListResponse)
async def list_menu_categories(
    _actor: ContentActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    include_archived: bool = False,
) -> MenuCategoryListResponse:
    result = await _service(session).list_menu_categories(
        page=page, page_size=page_size, include_archived=include_archived
    )
    return menu_category_list_response(result, page=page, page_size=page_size)


@router.post(
    "/menu/categories",
    response_model=MenuCategoryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_menu_category(
    payload: MenuCategoryCreate,
    request: Request,
    actor: ContentActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MenuCategoryResponse:
    item = await _service(session).create_menu_category(
        actor=actor, metadata=_metadata(request), **payload.model_dump()
    )
    return menu_category_response(item)


@router.patch("/menu/categories/{category_id}", response_model=MenuCategoryResponse)
async def update_menu_category(
    category_id: UUID,
    payload: MenuCategoryUpdate,
    request: Request,
    actor: ContentActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MenuCategoryResponse:
    item = await _service(session).update_menu_category(
        actor=actor,
        category_id=category_id,
        updates=payload.model_dump(exclude_unset=True),
        metadata=_metadata(request),
    )
    return menu_category_response(item)


@router.post("/menu/categories/{category_id}/hide", response_model=MenuCategoryResponse)
async def hide_menu_category(
    category_id: UUID,
    request: Request,
    actor: ContentActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MenuCategoryResponse:
    item = await _service(session).hide_menu_category(
        actor=actor, category_id=category_id, metadata=_metadata(request)
    )
    return menu_category_response(item)


@router.get("/menu/items", response_model=MenuItemListResponse)
async def list_menu_items(
    _actor: ContentActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    category_id: UUID | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    include_archived: bool = False,
) -> MenuItemListResponse:
    result = await _service(session).list_menu_items(
        category_id=category_id,
        page=page,
        page_size=page_size,
        include_archived=include_archived,
    )
    return menu_item_list_response(result, page=page, page_size=page_size)


@router.post("/menu/items", response_model=MenuItemResponse, status_code=status.HTTP_201_CREATED)
async def create_menu_item(
    payload: MenuItemCreate,
    request: Request,
    actor: ContentActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MenuItemResponse:
    item = await _service(session).create_menu_item(
        actor=actor, metadata=_metadata(request), **payload.model_dump()
    )
    return menu_item_response(item)


@router.patch("/menu/items/{item_id}", response_model=MenuItemResponse)
async def update_menu_item(
    item_id: UUID,
    payload: MenuItemUpdate,
    request: Request,
    actor: ContentActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MenuItemResponse:
    item = await _service(session).update_menu_item(
        actor=actor,
        item_id=item_id,
        updates=payload.model_dump(exclude_unset=True),
        metadata=_metadata(request),
    )
    return menu_item_response(item)


@router.post("/menu/items/{item_id}/hide", response_model=MenuItemResponse)
async def hide_menu_item(
    item_id: UUID,
    request: Request,
    actor: ContentActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MenuItemResponse:
    item = await _service(session).hide_menu_item(
        actor=actor, item_id=item_id, metadata=_metadata(request)
    )
    return menu_item_response(item)


@router.get("/promotions", response_model=PromotionListResponse)
async def list_promotions(
    _actor: ContentActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    promotion_status: Annotated[PromotionStatus | None, Query(alias="status")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PromotionListResponse:
    result = await _service(session).list_promotions(
        promotion_status=promotion_status, page=page, page_size=page_size
    )
    return promotion_list_response(result, page=page, page_size=page_size)


@router.post("/promotions", response_model=PromotionResponse, status_code=status.HTTP_201_CREATED)
async def create_promotion(
    payload: PromotionCreate,
    request: Request,
    actor: ContentActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PromotionResponse:
    values = payload.model_dump()
    values["body"] = values.pop("text")
    item = await _service(session).create_promotion(
        actor=actor, metadata=_metadata(request), **values
    )
    return promotion_response(item)


@router.patch("/promotions/{promotion_id}", response_model=PromotionResponse)
async def update_promotion(
    promotion_id: UUID,
    payload: PromotionUpdate,
    request: Request,
    actor: ContentActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PromotionResponse:
    values: dict[str, Any] = payload.model_dump(exclude_unset=True)
    if "text" in values:
        values["body"] = values.pop("text")
    item = await _service(session).update_promotion(
        actor=actor,
        promotion_id=promotion_id,
        updates=values,
        metadata=_metadata(request),
    )
    return promotion_response(item)


@router.post("/promotions/{promotion_id}/publish", response_model=PromotionResponse)
async def publish_promotion(
    promotion_id: UUID,
    request: Request,
    actor: ContentActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PromotionResponse:
    item = await _service(session).publish_promotion(
        actor=actor, promotion_id=promotion_id, metadata=_metadata(request)
    )
    return promotion_response(item)


@router.post("/promotions/{promotion_id}/archive", response_model=PromotionResponse)
async def archive_promotion(
    promotion_id: UUID,
    request: Request,
    actor: ContentActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PromotionResponse:
    item = await _service(session).archive_promotion(
        actor=actor, promotion_id=promotion_id, metadata=_metadata(request)
    )
    return promotion_response(item)


@router.get("/feedback", response_model=FeedbackListResponse)
async def list_feedback(
    _actor: FeedbackActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    feedback_status: Annotated[FeedbackStatus | None, Query(alias="status")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> FeedbackListResponse:
    result = await _service(session).list_feedback(
        feedback_status=feedback_status, page=page, page_size=page_size
    )
    return feedback_list_response(result, page=page, page_size=page_size)


@router.patch("/feedback/{feedback_id}", response_model=FeedbackAdminResponse)
async def update_feedback(
    feedback_id: UUID,
    payload: FeedbackUpdate,
    request: Request,
    actor: FeedbackActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> FeedbackAdminResponse:
    record = await _service(session).update_feedback(
        actor=actor,
        feedback_id=feedback_id,
        feedback_status=payload.status,
        internal_note=payload.internal_note,
        assigned_to_staff_id=payload.assigned_to_staff_id,
        metadata=_metadata(request),
    )
    return feedback_response(record)


@router.delete("/feedback/{feedback_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_feedback(
    feedback_id: UUID,
    request: Request,
    actor: FeedbackActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    await _service(session).delete_feedback(
        actor=actor,
        feedback_id=feedback_id,
        metadata=_metadata(request),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
