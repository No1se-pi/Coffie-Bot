"""Persistence queries for the Venue foundation slice."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import Venue
from app.models.enums import MediaStatus
from app.models.media import MediaFile


@dataclass(frozen=True, slots=True)
class VenuePage:
    items: list[Venue]
    total: int


class VenueRepository:
    """SQLAlchemy adapter; VenueService owns all transaction boundaries."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def transaction(self) -> AbstractAsyncContextManager[None]:
        return self._transaction()

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[None]:
        # FastAPI dependencies may already have opened a read transaction.  The
        # service still needs one commit/rollback boundary for mutation + audit.
        if not self._session.in_transaction():
            async with self._session.begin():
                yield
            return
        try:
            yield
        except BaseException:
            await self._session.rollback()
            raise
        else:
            await self._session.commit()

    def add(self, value: object) -> None:
        self._session.add(value)

    async def flush(self) -> None:
        await self._session.flush()

    async def list_public(self) -> list[Venue]:
        return list(
            (
                await self._session.scalars(
                    select(Venue)
                    .where(
                        Venue.is_active.is_(True),
                        Venue.archived_at.is_(None),
                    )
                    .order_by(Venue.sort_order, Venue.name, Venue.id)
                )
            ).all()
        )

    async def list_admin(
        self,
        *,
        page: int,
        page_size: int,
        include_archived: bool,
    ) -> VenuePage:
        filters = [] if include_archived else [Venue.archived_at.is_(None)]
        total = int(
            await self._session.scalar(select(func.count()).select_from(Venue).where(*filters)) or 0
        )
        items = list(
            (
                await self._session.scalars(
                    select(Venue)
                    .where(*filters)
                    .order_by(Venue.sort_order, Venue.name, Venue.id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return VenuePage(items=items, total=total)

    async def get(self, venue_id: UUID, *, for_update: bool) -> Venue | None:
        statement = select(Venue).where(Venue.id == venue_id)
        if for_update:
            statement = statement.with_for_update()
        value: Venue | None = await self._session.scalar(statement)
        return value

    async def get_by_slug(self, slug: str, *, for_update: bool) -> Venue | None:
        statement = select(Venue).where(Venue.slug == slug)
        if for_update:
            statement = statement.with_for_update()
        value: Venue | None = await self._session.scalar(statement)
        return value

    async def has_active_media(self, media_id: UUID) -> bool:
        value = await self._session.scalar(
            select(MediaFile.id).where(
                MediaFile.id == media_id,
                MediaFile.status == MediaStatus.ACTIVE,
            )
        )
        return value is not None
