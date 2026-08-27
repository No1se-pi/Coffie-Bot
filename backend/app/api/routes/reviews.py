"""Customer review submission, approved feed, and admin moderation."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models.enums import PermissionCode, ReviewStatus
from app.repositories.reviews import ReviewRepository
from app.schemas.reviews import (
    ReviewCreateRequest,
    ReviewListResponse,
    ReviewModerateRequest,
    ReviewResponse,
    review_response,
)
from app.security.rbac import Actor, get_current_actor, require_permissions
from app.services.reviews import ReviewCreateCommand, ReviewService

router = APIRouter(tags=["reviews"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
CurrentActor = Annotated[Actor, Depends(get_current_actor)]
ReviewAdmin = Annotated[Actor, Depends(require_permissions(PermissionCode.ADMIN_REVIEWS_MANAGE))]


def _service(session: AsyncSession) -> ReviewService:
    return ReviewService(ReviewRepository(session))


@router.get("/reviews", response_model=ReviewListResponse)
async def approved_reviews(
    _actor: CurrentActor,
    session: DatabaseSession,
    venue_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> ReviewListResponse:
    values = await _service(session).list_public(venue_id=venue_id, limit=limit)
    return ReviewListResponse(
        items=[review_response(value, include_moderation=False) for value in values]
    )


@router.post("/reviews", response_model=ReviewResponse, status_code=status.HTTP_201_CREATED)
async def create_review(
    payload: ReviewCreateRequest, actor: CurrentActor, session: DatabaseSession
) -> ReviewResponse:
    value = await _service(session).create(
        actor,
        ReviewCreateCommand(
            venue_id=payload.venue_id,
            order_id=payload.order_id,
            employee_staff_id=payload.employee_staff_id,
            rating=payload.rating,
            text=payload.text,
            author_display_name=payload.author_display_name,
        ),
    )
    return review_response(value, include_moderation=True)


@router.get("/me/reviews", response_model=ReviewListResponse)
async def my_reviews(
    actor: CurrentActor,
    session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> ReviewListResponse:
    values = await _service(session).list_mine(actor, limit=limit)
    return ReviewListResponse(
        items=[review_response(value, include_moderation=True) for value in values]
    )


@router.get("/admin/reviews", response_model=ReviewListResponse)
async def moderation_queue(
    actor: ReviewAdmin,
    session: DatabaseSession,
    review_status: Annotated[ReviewStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> ReviewListResponse:
    values = await _service(session).list_moderation(
        actor, review_status=review_status, limit=limit
    )
    return ReviewListResponse(
        items=[review_response(value, include_moderation=True) for value in values]
    )


@router.post("/admin/reviews/{review_id}/moderate", response_model=ReviewResponse)
async def moderate_review(
    review_id: UUID,
    payload: ReviewModerateRequest,
    actor: ReviewAdmin,
    session: DatabaseSession,
) -> ReviewResponse:
    value = await _service(session).moderate(
        actor, review_id, target_status=payload.status, note=payload.moderation_note
    )
    return review_response(value, include_moderation=True)
