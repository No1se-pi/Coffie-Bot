from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.models.access import User
from app.models.customers import CustomerIdentity
from app.models.enums import IdentityProvider, UserStatus
from app.repositories.identity import IdentityRepository
from app.security.telegram import TelegramUserData


def _database_url() -> str:
    value = os.getenv("DATABASE_URL")
    if not value:
        pytest.skip("DATABASE_URL is required for PostgreSQL integration tests")
    if not value.startswith("postgresql+asyncpg://"):
        pytest.skip("customer identity concurrency test requires async PostgreSQL")
    return value


def _telegram_id() -> int:
    # Keep generated IDs positive and safely below PostgreSQL BIGINT_MAX.
    return 8_000_000_000_000_000 + uuid4().int % 100_000_000_000_000


@pytest.mark.asyncio
async def test_concurrent_telegram_upsert_has_one_profile_and_one_identity() -> None:
    engine = create_async_engine(_database_url())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    telegram_id = _telegram_id()
    data = TelegramUserData(id=telegram_id, first_name="Concurrent identity")

    async def upsert() -> tuple[object, bool]:
        async with sessions() as session, session.begin():
            user, created = await IdentityRepository(session).upsert_telegram_user(
                data,
                now=_now(),
            )
            return user.id, created

    try:
        first, second = await asyncio.gather(upsert(), upsert())

        assert first[0] == second[0]
        assert sorted((first[1], second[1])) == [False, True]
        async with sessions() as session:
            user_count = len(
                list(await session.scalars(select(User.id).where(User.telegram_id == telegram_id)))
            )
            identity_count = len(
                list(
                    await session.scalars(
                        select(CustomerIdentity.id).where(
                            CustomerIdentity.provider == IdentityProvider.TELEGRAM,
                            CustomerIdentity.subject == str(telegram_id),
                        )
                    )
                )
            )
        assert (user_count, identity_count) == (1, 1)
    finally:
        await _cleanup(engine, telegram_id)
        await engine.dispose()


@pytest.mark.asyncio
async def test_telegram_upsert_repairs_profile_written_without_identity() -> None:
    engine = create_async_engine(_database_url())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    telegram_id = _telegram_id()
    legacy_user = User(
        id=uuid4(),
        telegram_id=telegram_id,
        first_name="Legacy writer",
        status=UserStatus.ACTIVE,
    )
    try:
        async with sessions() as session, session.begin():
            session.add(legacy_user)

        async with sessions() as session, session.begin():
            repaired, created = await IdentityRepository(session).upsert_telegram_user(
                TelegramUserData(id=telegram_id, first_name="Repaired"),
                now=_now(),
            )

        assert repaired.id == legacy_user.id
        assert created is False
        async with sessions() as session:
            owner_id = await session.scalar(
                select(CustomerIdentity.user_id).where(
                    CustomerIdentity.provider == IdentityProvider.TELEGRAM,
                    CustomerIdentity.subject == str(telegram_id),
                )
            )
        assert owner_id == legacy_user.id
    finally:
        await _cleanup(engine, telegram_id)
        await engine.dispose()


@pytest.mark.asyncio
async def test_identity_first_upsert_repairs_nullable_legacy_projection() -> None:
    engine = create_async_engine(_database_url())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    telegram_id = _telegram_id()
    user_id = uuid4()
    try:
        async with sessions() as session, session.begin():
            session.add_all(
                [
                    User(
                        id=user_id,
                        telegram_id=None,
                        first_name="Identity first",
                        status=UserStatus.ACTIVE,
                    ),
                    CustomerIdentity(
                        id=uuid4(),
                        user_id=user_id,
                        provider=IdentityProvider.TELEGRAM,
                        subject=str(telegram_id),
                        is_verified=True,
                        verified_at=_now(),
                        provider_metadata={},
                    ),
                ]
            )

        async with sessions() as session, session.begin():
            repaired, created = await IdentityRepository(session).upsert_telegram_user(
                TelegramUserData(id=telegram_id, first_name="Projection repaired"),
                now=_now(),
            )

        assert (repaired.id, repaired.telegram_id, created) == (user_id, telegram_id, False)
    finally:
        # This fixture starts with a NULL legacy projection, so identity subject
        # is the stable cleanup key even if the tested repair fails midway.
        async with engine.begin() as connection:
            await connection.execute(
                delete(CustomerIdentity).where(
                    CustomerIdentity.provider == IdentityProvider.TELEGRAM,
                    CustomerIdentity.subject == str(telegram_id),
                )
            )
            await connection.execute(delete(User).where(User.id == user_id))
        await engine.dispose()


async def _cleanup(engine: AsyncEngine, telegram_id: int) -> None:
    # The test creates only User + CustomerIdentity rows, so cleanup remains
    # narrowly scoped to a random Telegram subject and preserves all other data.
    async with engine.begin() as connection:
        await connection.execute(
            delete(CustomerIdentity).where(
                CustomerIdentity.provider == IdentityProvider.TELEGRAM,
                CustomerIdentity.subject == str(telegram_id),
            )
        )
        await connection.execute(delete(User).where(User.telegram_id == telegram_id))


def _now() -> datetime:
    return datetime.now(UTC)
