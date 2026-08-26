"""Read-only catalogue queries used by authoritative cart pricing."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.access import User
from app.models.content import (
    MenuCategory,
    MenuItem,
    MenuItemModifierGroup,
    ModifierGroup,
    ModifierOption,
    Promotion,
    PromotionMenuCategory,
    PromotionMenuItem,
    Venue,
)
from app.models.enums import PromotionStatus
from app.models.loyalty import LoyaltySettings
from app.models.loyalty_v2 import BirthdayPromotionVenue


class PricingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_available_items(self, item_ids: set[UUID]) -> list[MenuItem]:
        if not item_ids:
            return []
        return list(
            await self._session.scalars(
                select(MenuItem)
                .join(MenuCategory, MenuCategory.id == MenuItem.category_id)
                .join(Venue, Venue.id == MenuItem.venue_id)
                .where(
                    MenuItem.id.in_(item_ids),
                    MenuItem.is_visible.is_(True),
                    MenuItem.is_available.is_(True),
                    MenuItem.archived_at.is_(None),
                    MenuCategory.is_visible.is_(True),
                    MenuCategory.archived_at.is_(None),
                    Venue.is_active.is_(True),
                    Venue.archived_at.is_(None),
                )
            )
        )

    async def list_modifier_rows(
        self, item_ids: set[UUID]
    ) -> list[tuple[UUID, ModifierGroup, ModifierOption]]:
        if not item_ids:
            return []
        statement = (
            select(
                MenuItemModifierGroup.menu_item_id,
                ModifierGroup,
                ModifierOption,
            )
            .join(
                ModifierGroup,
                ModifierGroup.id == MenuItemModifierGroup.modifier_group_id,
            )
            .join(ModifierOption, ModifierOption.group_id == ModifierGroup.id)
            .where(
                MenuItemModifierGroup.menu_item_id.in_(item_ids),
                ModifierGroup.is_enabled.is_(True),
                ModifierGroup.archived_at.is_(None),
                ModifierOption.is_enabled.is_(True),
            )
            .order_by(
                MenuItemModifierGroup.sort_order,
                ModifierGroup.sort_order,
                ModifierGroup.id,
                ModifierOption.sort_order,
                ModifierOption.id,
            )
        )
        return [(row[0], row[1], row[2]) for row in (await self._session.execute(statement)).all()]

    async def list_active_promotions(
        self,
        venue_ids: set[UUID],
        *,
        now: datetime,
    ) -> list[Promotion]:
        if not venue_ids:
            return []
        return list(
            await self._session.scalars(
                select(Promotion)
                .where(
                    Promotion.venue_id.in_(venue_ids),
                    Promotion.pricing_enabled.is_(True),
                    Promotion.status == PromotionStatus.PUBLISHED,
                    or_(Promotion.starts_at.is_(None), Promotion.starts_at <= now),
                    or_(Promotion.ends_at.is_(None), Promotion.ends_at > now),
                )
                .order_by(Promotion.priority.desc(), Promotion.id)
            )
        )

    async def list_promotion_category_targets(
        self, promotion_ids: set[UUID]
    ) -> list[tuple[UUID, UUID]]:
        if not promotion_ids:
            return []
        rows = (
            await self._session.execute(
                select(
                    PromotionMenuCategory.promotion_id,
                    PromotionMenuCategory.category_id,
                ).where(PromotionMenuCategory.promotion_id.in_(promotion_ids))
            )
        ).all()
        return [(row[0], row[1]) for row in rows]

    async def list_promotion_item_targets(
        self, promotion_ids: set[UUID]
    ) -> list[tuple[UUID, UUID]]:
        if not promotion_ids:
            return []
        rows = (
            await self._session.execute(
                select(
                    PromotionMenuItem.promotion_id,
                    PromotionMenuItem.menu_item_id,
                ).where(PromotionMenuItem.promotion_id.in_(promotion_ids))
            )
        ).all()
        return [(row[0], row[1]) for row in rows]

    async def get_customer_pricing_context(
        self, user_id: UUID
    ) -> tuple[User, LoyaltySettings] | None:
        row = (
            await self._session.execute(
                select(User, LoyaltySettings)
                .join(LoyaltySettings, LoyaltySettings.singleton_key == "default")
                .where(User.id == user_id)
            )
        ).one_or_none()
        return None if row is None else (row[0], row[1])

    async def list_birthday_venue_ids(self, settings_id: UUID) -> set[UUID]:
        return set(
            await self._session.scalars(
                select(BirthdayPromotionVenue.venue_id).where(
                    BirthdayPromotionVenue.settings_id == settings_id
                )
            )
        )
