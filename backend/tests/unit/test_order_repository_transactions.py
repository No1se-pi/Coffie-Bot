"""Regression tests for request-scoped order transaction ownership."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.orders import OrderRepository


class FakeSession:
    def __init__(self, *, active: bool) -> None:
        self.active = active
        self.begin_calls = 0
        self.commit_calls = 0
        self.rollback_calls = 0

    def in_transaction(self) -> bool:
        return self.active

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        self.begin_calls += 1
        yield

    async def commit(self) -> None:
        self.commit_calls += 1

    async def rollback(self) -> None:
        self.rollback_calls += 1


@pytest.mark.asyncio
async def test_transaction_commits_existing_auth_read_transaction() -> None:
    session = FakeSession(active=True)
    repository = OrderRepository(cast(AsyncSession, session))

    async with repository.transaction():
        pass

    assert session.begin_calls == 0
    assert session.commit_calls == 1
    assert session.rollback_calls == 0


@pytest.mark.asyncio
async def test_transaction_rolls_back_existing_transaction_on_error() -> None:
    session = FakeSession(active=True)
    repository = OrderRepository(cast(AsyncSession, session))

    with pytest.raises(RuntimeError, match="boom"):
        async with repository.transaction():
            raise RuntimeError("boom")

    assert session.begin_calls == 0
    assert session.commit_calls == 0
    assert session.rollback_calls == 1
