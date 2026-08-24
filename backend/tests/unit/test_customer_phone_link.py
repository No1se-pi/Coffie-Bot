from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest

from app.core.errors import AppError
from app.models.access import User
from app.models.audit import AuditEvent
from app.models.customers import CustomerIdentity
from app.models.enums import IdentityProvider, UserStatus
from app.services.customers import CustomerRepositoryPort, CustomerService

NOW = datetime(2026, 8, 24, 12, tzinfo=UTC)


class FakePhoneLinkRepository:
    def __init__(self, telegram_user: User, phone_user: User | None = None) -> None:
        self.users = {telegram_user.id: telegram_user}
        self.identities: dict[tuple[IdentityProvider, str], CustomerIdentity] = {
            (IdentityProvider.TELEGRAM, str(telegram_user.telegram_id)): CustomerIdentity(
                id=uuid4(),
                user_id=telegram_user.id,
                provider=IdentityProvider.TELEGRAM,
                subject=str(telegram_user.telegram_id),
                is_verified=True,
                verified_at=NOW,
                provider_metadata={},
            )
        }
        if phone_user is not None:
            self.users[phone_user.id] = phone_user
            self.identities[(IdentityProvider.PHONE, "+79991234567")] = CustomerIdentity(
                id=uuid4(),
                user_id=phone_user.id,
                provider=IdentityProvider.PHONE,
                subject="+79991234567",
                is_verified=True,
                verified_at=NOW,
                provider_metadata={"verification_method": "staff"},
            )
        self.audit_events: list[AuditEvent] = []
        self.locks: list[tuple[str, str]] = []

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        yield

    async def acquire_namespace_lock(self, namespace: str, value: str) -> None:
        self.locks.append((namespace, value))

    async def get_identity(
        self,
        *,
        provider: IdentityProvider,
        subject: str,
        for_update: bool = False,
    ) -> CustomerIdentity | None:
        del for_update
        return self.identities.get((provider, subject))

    async def get_user(self, user_id: UUID, *, for_update: bool) -> User | None:
        del for_update
        return self.users.get(user_id)

    def add(self, value: object) -> None:
        if isinstance(value, CustomerIdentity):
            self.identities[(value.provider, value.subject)] = value
        elif isinstance(value, AuditEvent):
            self.audit_events.append(value)

    async def flush(self) -> None:
        return None


def _user(*, telegram_id: int | None) -> User:
    return User(
        id=uuid4(),
        telegram_id=telegram_id,
        first_name="Гость",
        status=UserStatus.ACTIVE,
    )


@pytest.mark.asyncio
async def test_verified_telegram_contact_attaches_phone_without_logging_full_number() -> None:
    telegram_user = _user(telegram_id=12345)
    repository = FakePhoneLinkRepository(telegram_user)
    service = CustomerService(cast(CustomerRepositoryPort, repository))

    result = await service.link_verified_telegram_contact(
        telegram_id=12345,
        contact_user_id=12345,
        phone="8 (999) 123-45-67",
        now=NOW,
    )

    identity = repository.identities[(IdentityProvider.PHONE, "+79991234567")]
    assert result.status == "linked"
    assert identity.user_id == telegram_user.id
    assert identity.provider_metadata == {"verification_method": "telegram_contact"}
    assert repository.locks == [("customer.identity.phone", "+79991234567")]
    assert repository.audit_events[0].event_metadata["phone_last4"] == "4567"
    assert "+79991234567" not in str(repository.audit_events[0].event_metadata)


@pytest.mark.asyncio
async def test_contact_owned_by_another_telegram_user_is_rejected() -> None:
    repository = FakePhoneLinkRepository(_user(telegram_id=12345))
    service = CustomerService(cast(CustomerRepositoryPort, repository))

    with pytest.raises(AppError) as captured:
        await service.link_verified_telegram_contact(
            telegram_id=12345,
            contact_user_id=54321,
            phone="+79991234567",
            now=NOW,
        )

    assert captured.value.status_code == 403
    assert (IdentityProvider.PHONE, "+79991234567") not in repository.identities


@pytest.mark.asyncio
async def test_existing_phone_profile_requires_audited_merge_instead_of_silent_move() -> None:
    telegram_user = _user(telegram_id=12345)
    phone_user = _user(telegram_id=None)
    repository = FakePhoneLinkRepository(telegram_user, phone_user)
    service = CustomerService(cast(CustomerRepositoryPort, repository))

    result = await service.link_verified_telegram_contact(
        telegram_id=12345,
        contact_user_id=12345,
        phone="+7 999 123-45-67",
        now=NOW,
    )

    assert result.status == "merge_required"
    assert repository.identities[(IdentityProvider.PHONE, "+79991234567")].user_id == phone_user.id
    assert repository.audit_events[0].event_type == "customer.phone_link.merge_required"
    assert repository.audit_events[0].event_metadata["merge_candidate_user_id"] == str(
        phone_user.id
    )
