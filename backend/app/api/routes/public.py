"""Authenticated public content and private feedback routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.repositories.pricing import PricingRepository
from app.repositories.public import PublicRepository
from app.schemas.public import (
    ContactsResponse,
    FeedbackRequest,
    FeedbackResponse,
    MenuCategoryListResponse,
    MenuItemListResponse,
    PromotionListResponse,
    StaffProfileListResponse,
    contacts_response,
    feedback_response,
    menu_categories_response,
    menu_items_response,
    promotions_response,
    staff_profiles_response,
)
from app.security.rbac import Actor, get_current_actor

router = APIRouter(tags=["public-content"])


@router.get(
    "/menu/categories",
    response_model=MenuCategoryListResponse,
    status_code=status.HTTP_200_OK,
)
async def menu_categories(
    _actor: Annotated[Actor, Depends(get_current_actor)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    venue_id: Annotated[UUID | None, Query()] = None,
) -> MenuCategoryListResponse:
    return menu_categories_response(
        await PublicRepository(session).list_menu_categories(venue_id=venue_id)
    )


@router.get(
    "/menu/items",
    response_model=MenuItemListResponse,
    status_code=status.HTTP_200_OK,
)
async def menu_items(
    _actor: Annotated[Actor, Depends(get_current_actor)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    category_id: Annotated[UUID | None, Query()] = None,
    available: Annotated[bool | None, Query()] = None,
    venue_id: Annotated[UUID | None, Query()] = None,
) -> MenuItemListResponse:
    items = await PublicRepository(session).list_menu_items(
        category_id=category_id,
        available=available,
        venue_id=venue_id,
    )
    modifier_rows = await PricingRepository(session).list_modifier_rows({item.id for item in items})
    return menu_items_response(items, modifier_rows)


@router.get(
    "/promotions",
    response_model=PromotionListResponse,
    status_code=status.HTTP_200_OK,
)
async def promotions(
    _actor: Annotated[Actor, Depends(get_current_actor)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    active: Annotated[bool, Query()] = True,
    venue_id: Annotated[UUID | None, Query()] = None,
) -> PromotionListResponse:
    items = await PublicRepository(session).list_promotions(active=active, venue_id=venue_id)
    return promotions_response(items)


@router.get(
    "/contacts",
    response_model=ContactsResponse,
    status_code=status.HTTP_200_OK,
)
async def contacts(
    _actor: Annotated[Actor, Depends(get_current_actor)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ContactsResponse:
    repository = PublicRepository(session)
    settings = await repository.get_public_settings()
    locations = await repository.list_locations()
    return contacts_response(settings, locations)


@router.get(
    "/staff-profiles",
    response_model=StaffProfileListResponse,
    status_code=status.HTTP_200_OK,
)
async def staff_profiles(
    _actor: Annotated[Actor, Depends(get_current_actor)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> StaffProfileListResponse:
    return staff_profiles_response(await PublicRepository(session).list_staff_profiles())


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_feedback(
    payload: FeedbackRequest,
    request: Request,
    actor: Annotated[Actor, Depends(get_current_actor)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> FeedbackResponse:
    feedback = await PublicRepository(session).create_feedback(
        user_id=actor.user_id,
        rating=payload.rating,
        category=payload.category,
        message=payload.message,
        may_contact=payload.may_contact,
        ip_address=request.client.host if request.client is not None else None,
        user_agent=request.headers.get("User-Agent", "")[:512] or None,
    )
    return feedback_response(feedback)
