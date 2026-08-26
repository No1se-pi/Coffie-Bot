"""Real PostgreSQL coverage for venue-safe authoritative cart pricing."""

from __future__ import annotations

import os
from datetime import UTC, datetime, time
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.errors import AppError
from app.models.access import StaffMember, User
from app.models.content import (
    MenuCategory,
    MenuItem,
    MenuItemModifierGroup,
    ModifierGroup,
    ModifierOption,
    Promotion,
    PromotionMenuCategory,
    Venue,
)
from app.models.enums import (
    PromotionActionType,
    PromotionStatus,
    Role,
    UserStatus,
)
from app.repositories.pricing import PricingRepository
from app.services.pricing import CartPricingService, RequestedModifier


def _database_url() -> str:
    value = os.getenv("DATABASE_URL")
    if not value or not value.startswith("postgresql+asyncpg://"):
        pytest.skip("An async PostgreSQL DATABASE_URL is required")
    return value


@pytest.mark.asyncio
async def test_pricing_loads_trusted_menu_modifiers_and_venue_promotion() -> None:
    engine = create_async_engine(_database_url())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    customer_id = uuid4()
    staff_user_id = uuid4()
    staff_id = uuid4()
    venue_id = uuid4()
    category_id = uuid4()
    other_venue_id = uuid4()
    other_category_id = uuid4()
    item_id = uuid4()
    group_id = uuid4()
    option_id = uuid4()
    promotion_id = uuid4()
    line_id = uuid4()
    async with sessions() as session, session.begin():
        session.add_all(
            [
                User(
                    id=customer_id,
                    telegram_id=None,
                    first_name="Pricing customer",
                    status=UserStatus.ACTIVE,
                ),
                User(
                    id=staff_user_id,
                    telegram_id=None,
                    first_name="Pricing admin",
                    status=UserStatus.ACTIVE,
                ),
                Venue(
                    id=venue_id,
                    slug=f"pricing-{venue_id.hex}",
                    name="Pricing venue",
                    is_active=True,
                    sort_order=0,
                ),
                Venue(
                    id=other_venue_id,
                    slug=f"pricing-other-{other_venue_id.hex}",
                    name="Other pricing venue",
                    is_active=True,
                    sort_order=1,
                ),
            ]
        )
        await session.flush()
        session.add(
            StaffMember(
                id=staff_id,
                user_id=staff_user_id,
                role=Role.ADMIN,
                is_active=True,
            )
        )
        session.add(
            MenuCategory(
                id=category_id,
                venue_id=venue_id,
                name="Desserts",
                sort_order=0,
                is_visible=True,
            )
        )
        session.add(
            MenuCategory(
                id=other_category_id,
                venue_id=other_venue_id,
                name="Foreign category",
                sort_order=0,
                is_visible=True,
            )
        )
        await session.flush()
        session.add(
            MenuItem(
                id=item_id,
                venue_id=venue_id,
                category_id=category_id,
                name="Synthetic cake",
                price_minor=20_000,
                labels=[],
                is_available=True,
                is_visible=True,
                sort_order=0,
            )
        )
        session.add(
            ModifierGroup(
                id=group_id,
                venue_id=venue_id,
                name="Serving",
                min_selections=1,
                max_selections=1,
                is_required=True,
                is_enabled=True,
                sort_order=0,
            )
        )
        session.add(
            Promotion(
                id=promotion_id,
                venue_id=venue_id,
                title="Desserts after 19",
                body="Synthetic 15 percent pricing rule",
                status=PromotionStatus.PUBLISHED,
                published_at=datetime(2026, 8, 26, 10, tzinfo=UTC),
                created_by_staff_id=staff_id,
                pricing_enabled=True,
                action_type=PromotionActionType.PERCENT_DISCOUNT,
                discount_value=1_500,
                priority=10,
                stackable=False,
                active_weekdays=[],
                active_time_from=time(19),
                fulfillment_modes=["pickup"],
                minimum_order_minor=0,
            )
        )
        await session.flush()
        session.add_all(
            [
                ModifierOption(
                    id=option_id,
                    group_id=group_id,
                    name="Gift box",
                    price_delta_minor=6_000,
                    allows_quantity=False,
                    max_quantity=1,
                    is_enabled=True,
                    sort_order=0,
                ),
                MenuItemModifierGroup(
                    menu_item_id=item_id,
                    modifier_group_id=group_id,
                    venue_id=venue_id,
                    sort_order=0,
                ),
                PromotionMenuCategory(
                    promotion_id=promotion_id,
                    category_id=category_id,
                    venue_id=venue_id,
                ),
            ]
        )

    try:
        async with sessions() as session:
            result = await CartPricingService(PricingRepository(session)).preview(
                user_id=customer_id,
                lines=(
                    (
                        line_id,
                        item_id,
                        2,
                        (RequestedModifier(option_id=option_id),),
                    ),
                ),
                fulfillment_mode="pickup",
                # 16:15 UTC is 19:15 in the configured Europe/Moscow timezone.
                now=datetime(2026, 8, 26, 16, 15, tzinfo=UTC),
            )
        assert (result.subtotal_minor, result.discount_minor, result.total_minor) == (
            52_000,
            7_800,
            44_200,
        )
        assert result.venues[0].lines[0].modifiers[0].option_id == option_id

        async with sessions() as session:
            with pytest.raises(AppError) as raised:
                await CartPricingService(PricingRepository(session)).preview(
                    user_id=customer_id,
                    lines=((uuid4(), item_id, 1, (RequestedModifier(option_id=uuid4()),)),),
                    fulfillment_mode="pickup",
                    now=datetime(2026, 8, 26, 16, 15, tzinfo=UTC),
                )
        assert raised.value.code == "modifier_not_applicable"

        # Service validation is backed by a composite database FK, so a direct
        # cross-venue promotion target cannot bypass the invariant.
        async with sessions() as session:
            session.add(
                PromotionMenuCategory(
                    promotion_id=promotion_id,
                    category_id=other_category_id,
                    venue_id=venue_id,
                )
            )
            with pytest.raises(IntegrityError):
                await session.flush()
            await session.rollback()
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                delete(PromotionMenuCategory).where(
                    PromotionMenuCategory.promotion_id == promotion_id
                )
            )
            await connection.execute(
                delete(MenuItemModifierGroup).where(
                    MenuItemModifierGroup.modifier_group_id == group_id
                )
            )
            await connection.execute(delete(ModifierOption).where(ModifierOption.id == option_id))
            await connection.execute(delete(Promotion).where(Promotion.id == promotion_id))
            await connection.execute(delete(ModifierGroup).where(ModifierGroup.id == group_id))
            await connection.execute(delete(MenuItem).where(MenuItem.id == item_id))
            await connection.execute(delete(MenuCategory).where(MenuCategory.id == category_id))
            await connection.execute(
                delete(MenuCategory).where(MenuCategory.id == other_category_id)
            )
            await connection.execute(delete(StaffMember).where(StaffMember.id == staff_id))
            await connection.execute(delete(Venue).where(Venue.id == venue_id))
            await connection.execute(delete(Venue).where(Venue.id == other_venue_id))
            await connection.execute(delete(User).where(User.id.in_({customer_id, staff_user_id})))
        await engine.dispose()
