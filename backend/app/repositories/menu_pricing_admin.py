"""Persistence adapter for modifier and promotion-rule administration."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import cast
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

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


class MenuPricingAdminRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        if not self._session.in_transaction():
            async with self._session.begin():
                yield
            return
        try:
            yield
            await self._session.commit()
        except BaseException:
            await self._session.rollback()
            raise

    def add(self, value: object) -> None:
        self._session.add(value)

    def add_all(self, values: Sequence[object]) -> None:
        self._session.add_all(values)

    async def flush(self) -> None:
        await self._session.flush()

    async def get_venue(self, venue_id: UUID) -> Venue | None:
        return await self._session.get(Venue, venue_id)

    async def list_groups(
        self, *, venue_id: UUID | None, include_archived: bool
    ) -> list[ModifierGroup]:
        filters = [] if venue_id is None else [ModifierGroup.venue_id == venue_id]
        if not include_archived:
            filters.append(ModifierGroup.archived_at.is_(None))
        return list(
            await self._session.scalars(
                select(ModifierGroup)
                .where(*filters)
                .order_by(ModifierGroup.venue_id, ModifierGroup.sort_order, ModifierGroup.id)
            )
        )

    async def get_group(self, group_id: UUID, *, for_update: bool) -> ModifierGroup | None:
        statement = select(ModifierGroup).where(ModifierGroup.id == group_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(ModifierGroup | None, await self._session.scalar(statement))

    async def list_options(self, group_ids: set[UUID]) -> list[ModifierOption]:
        if not group_ids:
            return []
        return list(
            await self._session.scalars(
                select(ModifierOption)
                .where(ModifierOption.group_id.in_(group_ids))
                .order_by(ModifierOption.group_id, ModifierOption.sort_order, ModifierOption.id)
            )
        )

    async def list_group_item_links(self, group_ids: set[UUID]) -> list[tuple[UUID, UUID]]:
        if not group_ids:
            return []
        rows = (
            await self._session.execute(
                select(
                    MenuItemModifierGroup.modifier_group_id,
                    MenuItemModifierGroup.menu_item_id,
                ).where(MenuItemModifierGroup.modifier_group_id.in_(group_ids))
            )
        ).all()
        return [(row[0], row[1]) for row in rows]

    async def get_items(self, item_ids: set[UUID]) -> list[MenuItem]:
        if not item_ids:
            return []
        return list(await self._session.scalars(select(MenuItem).where(MenuItem.id.in_(item_ids))))

    async def replace_group_links(self, group: ModifierGroup, item_ids: set[UUID]) -> None:
        await self._session.execute(
            delete(MenuItemModifierGroup).where(MenuItemModifierGroup.modifier_group_id == group.id)
        )
        self._session.add_all(
            [
                MenuItemModifierGroup(
                    menu_item_id=item_id,
                    modifier_group_id=group.id,
                    venue_id=group.venue_id,
                    sort_order=group.sort_order,
                )
                for item_id in sorted(item_ids, key=str)
            ]
        )

    async def delete_options_except(self, group_id: UUID, keep_ids: set[UUID]) -> None:
        statement = delete(ModifierOption).where(ModifierOption.group_id == group_id)
        if keep_ids:
            statement = statement.where(ModifierOption.id.not_in(keep_ids))
        await self._session.execute(statement)

    async def get_promotion(self, promotion_id: UUID, *, for_update: bool) -> Promotion | None:
        statement = select(Promotion).where(Promotion.id == promotion_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(Promotion | None, await self._session.scalar(statement))

    async def get_categories(self, category_ids: set[UUID]) -> list[MenuCategory]:
        if not category_ids:
            return []
        return list(
            await self._session.scalars(
                select(MenuCategory).where(MenuCategory.id.in_(category_ids))
            )
        )

    async def promotion_targets(self, promotion_id: UUID) -> tuple[set[UUID], set[UUID]]:
        categories = set(
            await self._session.scalars(
                select(PromotionMenuCategory.category_id).where(
                    PromotionMenuCategory.promotion_id == promotion_id
                )
            )
        )
        items = set(
            await self._session.scalars(
                select(PromotionMenuItem.menu_item_id).where(
                    PromotionMenuItem.promotion_id == promotion_id
                )
            )
        )
        return categories, items

    async def replace_promotion_targets(
        self,
        promotion_id: UUID,
        *,
        venue_id: UUID,
        category_ids: set[UUID],
        item_ids: set[UUID],
    ) -> None:
        await self._session.execute(
            delete(PromotionMenuCategory).where(PromotionMenuCategory.promotion_id == promotion_id)
        )
        await self._session.execute(
            delete(PromotionMenuItem).where(PromotionMenuItem.promotion_id == promotion_id)
        )
        self._session.add_all(
            [
                PromotionMenuCategory(
                    promotion_id=promotion_id,
                    category_id=category_id,
                    venue_id=venue_id,
                )
                for category_id in sorted(category_ids, key=str)
            ]
        )
        self._session.add_all(
            [
                PromotionMenuItem(
                    promotion_id=promotion_id,
                    menu_item_id=item_id,
                    venue_id=venue_id,
                )
                for item_id in sorted(item_ids, key=str)
            ]
        )
