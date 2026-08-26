"""Authenticated authoritative cart pricing preview."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.repositories.pricing import PricingRepository
from app.schemas.pricing import CartPriceRequest, CartPriceResponse, cart_price_response
from app.security.rbac import Actor, get_current_actor
from app.services.pricing import CartPricingService, RequestedModifier

router = APIRouter(tags=["pricing"])


@router.post("/cart/price", response_model=CartPriceResponse)
async def preview_cart_price(
    payload: CartPriceRequest,
    actor: Annotated[Actor, Depends(get_current_actor)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CartPriceResponse:
    result = await CartPricingService(PricingRepository(session)).preview(
        user_id=actor.user_id,
        lines=tuple(
            (
                line.line_id,
                line.menu_item_id,
                line.quantity,
                tuple(
                    RequestedModifier(
                        option_id=modifier.option_id,
                        quantity=modifier.quantity,
                    )
                    for modifier in line.modifiers
                ),
            )
            for line in payload.lines
        ),
        fulfillment_mode=payload.fulfillment_mode,
        now=datetime.now(UTC),
    )
    return cart_price_response(result)
