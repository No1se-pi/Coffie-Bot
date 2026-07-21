"""Initial owner bootstrap use case."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


class OwnerRepositoryPort(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[None]: ...

    async def upsert_owner(
        self,
        *,
        telegram_id: int,
        display_name: str | None,
    ) -> tuple[UUID, UUID, bool]: ...


@dataclass(frozen=True, slots=True)
class OwnerResult:
    user_id: UUID
    staff_member_id: UUID
    changed: bool


class OwnerService:
    def __init__(self, repository: OwnerRepositoryPort) -> None:
        self._repository = repository

    async def create_or_promote(
        self,
        *,
        telegram_id: int,
        display_name: str | None,
    ) -> OwnerResult:
        if telegram_id <= 0:
            raise ValueError("telegram_id must be positive")
        normalized_name = " ".join(display_name.split()) if display_name else None
        if normalized_name == "":
            normalized_name = None
        if normalized_name is not None and len(normalized_name) > 128:
            raise ValueError("display_name must not exceed 128 characters")
        async with self._repository.transaction():
            user_id, staff_member_id, changed = await self._repository.upsert_owner(
                telegram_id=telegram_id,
                display_name=normalized_name,
            )
        return OwnerResult(
            user_id=user_id,
            staff_member_id=staff_member_id,
            changed=changed,
        )
