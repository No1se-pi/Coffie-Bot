"""Authenticated customer-facing Venue catalogue."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.repositories.venues import VenueRepository
from app.schemas.venues import VenuePublicListResponse, venue_public_list_response
from app.security.rbac import Actor, get_current_actor
from app.services.venues import VenueService

router = APIRouter(tags=["venues"])


@router.get("/venues", response_model=VenuePublicListResponse, status_code=status.HTTP_200_OK)
async def list_venues(
    _actor: Annotated[Actor, Depends(get_current_actor)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> VenuePublicListResponse:
    items = await VenueService(VenueRepository(session)).list_public()
    return venue_public_list_response(items)
