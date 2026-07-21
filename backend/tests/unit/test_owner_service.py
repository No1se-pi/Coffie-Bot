from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest

from app.services.owner import OwnerService


class FakeOwnerRepository:
    def __init__(self) -> None:
        self.user_id = uuid4()
        self.staff_id = uuid4()
        self.calls: list[tuple[int, str | None]] = []
        self.commits = 0

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        yield
        self.commits += 1

    async def upsert_owner(
        self,
        *,
        telegram_id: int,
        display_name: str | None,
    ) -> tuple[UUID, UUID, bool]:
        self.calls.append((telegram_id, display_name))
        return self.user_id, self.staff_id, True


async def test_owner_service_normalizes_name_and_commits_once() -> None:
    repository = FakeOwnerRepository()

    result = await OwnerService(repository).create_or_promote(
        telegram_id=123,
        display_name="  Имя   Владельца  ",
    )

    assert repository.calls == [(123, "Имя Владельца")]
    assert repository.commits == 1
    assert result.staff_member_id == repository.staff_id
    assert result.changed is True


async def test_owner_service_rejects_invalid_telegram_id_before_transaction() -> None:
    repository = FakeOwnerRepository()

    with pytest.raises(ValueError, match="positive"):
        await OwnerService(repository).create_or_promote(
            telegram_id=0,
            display_name=None,
        )

    assert repository.calls == []
    assert repository.commits == 0
