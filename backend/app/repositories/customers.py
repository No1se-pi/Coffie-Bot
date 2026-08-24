"""Persistence adapter for provider-neutral customer identity workflows."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import func, select

from app.models.access import User
from app.models.audit import AuditEvent
from app.models.cards import UserCard
from app.models.customers import CustomerIdentity
from app.models.enums import IdentityProvider, UserStatus
from app.repositories.identity import IdentityRepository


@dataclass(frozen=True, slots=True)
class CustomerCreationReceipt:
    event_type: str
    request_hash: str | None
    user_id: UUID | None
    card_id: UUID | None = None
    display_name: str | None = None
    masked_phone: str | None = None
    points_balance: int | None = None


class CustomerRepository(IdentityRepository):
    """Extends the existing registration aggregate without duplicating its journal writes."""

    async def acquire_namespace_lock(self, namespace: str, value: str) -> None:
        """Serialize create-before-unique-row workflows with a transaction advisory lock."""

        digest = hashlib.sha256(f"{namespace}:{value}".encode()).digest()
        lock_id = int.from_bytes(digest[:8], byteorder="big", signed=True)
        await self._session.execute(select(func.pg_advisory_xact_lock(lock_id)))

    async def get_identity(
        self,
        *,
        provider: IdentityProvider,
        subject: str,
        for_update: bool = False,
    ) -> CustomerIdentity | None:
        statement = select(CustomerIdentity).where(
            CustomerIdentity.provider == provider,
            CustomerIdentity.subject == subject,
        )
        if for_update:
            statement = statement.with_for_update()
        return cast(CustomerIdentity | None, await self._session.scalar(statement))

    async def list_identities(self, user_id: UUID) -> list[CustomerIdentity]:
        return list(
            await self._session.scalars(
                select(CustomerIdentity)
                .where(CustomerIdentity.user_id == user_id)
                .order_by(CustomerIdentity.provider, CustomerIdentity.created_at)
            )
        )

    async def get_user(self, user_id: UUID, *, for_update: bool) -> User | None:
        statement = select(User).where(User.id == user_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(User | None, await self._session.scalar(statement))

    async def get_card(self, card_id: UUID) -> UserCard | None:
        return cast(UserCard | None, await self._session.get(UserCard, card_id))

    def add(self, value: object) -> None:
        self._session.add(value)

    def create_phone_profile(
        self,
        *,
        phone: str,
        display_name: str,
        actor_staff_id: UUID,
        now: datetime,
    ) -> User:
        user = User(
            id=uuid4(),
            telegram_id=None,
            first_name=display_name,
            status=UserStatus.ACTIVE,
        )
        identity = CustomerIdentity(
            id=uuid4(),
            user_id=user.id,
            provider=IdentityProvider.PHONE,
            subject=phone,
            is_verified=True,
            verified_at=now,
            verified_by_staff_id=actor_staff_id,
            last_used_at=now,
            provider_metadata={"verification_method": "staff"},
        )
        self._session.add_all([user, identity])
        return user

    async def get_creation_receipt(self, key: str) -> CustomerCreationReceipt | None:
        event = await self._session.scalar(
            select(AuditEvent).where(AuditEvent.idempotency_key == key)
        )
        if event is None:
            return None
        request_hash = event.event_metadata.get("request_hash")
        display_name = event.event_metadata.get("display_name")
        masked_phone = event.event_metadata.get("masked_phone")
        points_balance = event.event_metadata.get("points_balance")
        return CustomerCreationReceipt(
            event_type=event.event_type,
            request_hash=request_hash if isinstance(request_hash, str) else None,
            user_id=event.subject_user_id,
            card_id=event.object_id,
            display_name=display_name if isinstance(display_name, str) else None,
            masked_phone=masked_phone if isinstance(masked_phone, str) else None,
            points_balance=(
                points_balance
                if isinstance(points_balance, int) and not isinstance(points_balance, bool)
                else None
            ),
        )
