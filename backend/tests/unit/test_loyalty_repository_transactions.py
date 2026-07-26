from __future__ import annotations

from types import TracebackType
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.loyalty import LoyaltyRepository


class RecordingBegin:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def __aenter__(self) -> None:
        self._events.append("begin")

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._events.append("end")


class RecordingSession:
    def __init__(self, *, in_transaction: bool) -> None:
        self._in_transaction = in_transaction
        self.events: list[str] = []

    def in_transaction(self) -> bool:
        return self._in_transaction

    def begin(self) -> RecordingBegin:
        return RecordingBegin(self.events)

    async def commit(self) -> None:
        self.events.append("commit")

    async def rollback(self) -> None:
        self.events.append("rollback")


def _repository(session: RecordingSession) -> LoyaltyRepository:
    return LoyaltyRepository(cast(AsyncSession, session))


@pytest.mark.asyncio
async def test_transaction_starts_new_database_transaction_when_session_is_idle() -> None:
    session = RecordingSession(in_transaction=False)

    async with _repository(session).transaction():
        session.events.append("body")

    assert session.events == ["begin", "body", "end"]


@pytest.mark.asyncio
async def test_transaction_commits_existing_request_transaction() -> None:
    session = RecordingSession(in_transaction=True)

    async with _repository(session).transaction():
        session.events.append("body")

    assert session.events == ["body", "commit"]


@pytest.mark.asyncio
async def test_transaction_rolls_back_existing_request_transaction_on_error() -> None:
    session = RecordingSession(in_transaction=True)

    with pytest.raises(RuntimeError, match="failure"):
        async with _repository(session).transaction():
            raise RuntimeError("failure")

    assert session.events == ["rollback"]
