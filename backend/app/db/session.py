"""Async PostgreSQL engine and request-scoped sessions."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings


@dataclass(frozen=True, slots=True)
class Database:
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]


def create_database(settings: Settings) -> Database:
    engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout_seconds,
    )
    return Database(
        engine=engine,
        session_factory=async_sessionmaker(engine, expire_on_commit=False, autoflush=False),
    )


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a request session; application services own commit boundaries."""

    database: Database = request.app.state.database
    async with database.session_factory() as session:
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise
