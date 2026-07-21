"""Current-user profile, card, immutable history, and reward reads."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.session import get_db_session
from app.models.enums import LoyaltyOperationType, RewardStatus
from app.repositories.identity import IdentityRepository
from app.schemas.identity import (
    CardResponse,
    HistoryListResponse,
    MeResponse,
    RewardListResponse,
    card_response,
    history_response,
    me_response,
    rewards_response,
)
from app.security.rbac import Actor, get_current_actor
from app.services.identity import IdentityService

router = APIRouter(prefix="/me", tags=["current-user"])


def _service(request: Request, session: AsyncSession) -> IdentityService:
    return IdentityService(
        settings=cast(Settings, request.app.state.settings),
        repository=IdentityRepository(session),
    )


@router.get("", response_model=MeResponse, status_code=status.HTTP_200_OK)
async def current_user(
    request: Request,
    actor: Annotated[Actor, Depends(get_current_actor)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MeResponse:
    identity = await _service(request, session).get_identity(actor.user_id)
    return me_response(identity)


@router.get("/card", response_model=CardResponse, status_code=status.HTTP_200_OK)
async def current_card(
    request: Request,
    actor: Annotated[Actor, Depends(get_current_actor)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CardResponse:
    card = await _service(request, session).get_card(actor.user_id)
    return card_response(card)


@router.get(
    "/history",
    response_model=HistoryListResponse,
    status_code=status.HTTP_200_OK,
)
async def current_history(
    request: Request,
    actor: Annotated[Actor, Depends(get_current_actor)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    operation_type: Annotated[
        LoyaltyOperationType | None,
        Query(alias="type"),
    ] = None,
) -> HistoryListResponse:
    result = await _service(request, session).list_history(
        user_id=actor.user_id,
        operation_type=operation_type,
        page=page,
        page_size=page_size,
    )
    return history_response(result, page=page, page_size=page_size)


@router.get(
    "/rewards",
    response_model=RewardListResponse,
    status_code=status.HTTP_200_OK,
)
async def current_rewards(
    request: Request,
    actor: Annotated[Actor, Depends(get_current_actor)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    reward_status: Annotated[
        RewardStatus | None,
        Query(alias="status"),
    ] = None,
) -> RewardListResponse:
    result = await _service(request, session).list_rewards(
        user_id=actor.user_id,
        reward_status=reward_status,
        page=page,
        page_size=page_size,
    )
    return rewards_response(result, page=page, page_size=page_size)
