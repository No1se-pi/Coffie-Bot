"""Telegram Mini App authentication and opaque-session logout routes."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.session import get_db_session
from app.repositories.identity import IdentityRepository
from app.schemas.identity import (
    AuthResponse,
    PasswordLoginRequest,
    TelegramAuthRequest,
    TelegramWebLoginRequest,
    auth_response,
)
from app.security.rbac import Actor, get_current_actor
from app.services.identity import IdentityService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/telegram",
    response_model=AuthResponse,
    status_code=status.HTTP_200_OK,
)
async def telegram_auth(
    payload: TelegramAuthRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuthResponse:
    settings = cast(Settings, request.app.state.settings)
    service = IdentityService(
        settings=settings,
        repository=IdentityRepository(session),
    )
    result = await service.authenticate(
        payload.init_data,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("User-Agent"),
    )
    return auth_response(result)


@router.post(
    "/telegram/web",
    response_model=AuthResponse,
    status_code=status.HTTP_200_OK,
)
async def telegram_web_auth(
    payload: TelegramWebLoginRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuthResponse:
    settings = cast(Settings, request.app.state.settings)
    result = await IdentityService(
        settings=settings,
        repository=IdentityRepository(session),
    ).authenticate_web_login(
        payload.model_dump(),
        ip_address=_client_ip(request),
        user_agent=request.headers.get("User-Agent"),
    )
    return auth_response(result)


@router.post("/password", response_model=AuthResponse, status_code=status.HTTP_200_OK)
async def password_auth(
    payload: PasswordLoginRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuthResponse:
    """Authenticate the single configured admin without trusting browser roles."""

    settings = cast(Settings, request.app.state.settings)
    result = await IdentityService(
        settings=settings,
        repository=IdentityRepository(session),
    ).authenticate_password(
        payload.username,
        payload.password,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("User-Agent"),
    )
    return auth_response(result)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    actor: Annotated[Actor, Depends(get_current_actor)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    settings = cast(Settings, request.app.state.settings)
    service = IdentityService(
        settings=settings,
        repository=IdentityRepository(session),
    )
    await service.logout(session_id=actor.session_id, user_id=actor.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _client_ip(request: Request) -> str | None:
    """Use the socket peer; proxy-header trust must be configured centrally."""

    return request.client.host if request.client is not None else None
