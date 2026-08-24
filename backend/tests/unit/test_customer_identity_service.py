from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Table, UniqueConstraint
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.access import Session, User
from app.models.audit import AuditEvent
from app.models.cards import UserCard
from app.models.customers import CustomerIdentity
from app.models.enums import (
    CardStatus,
    IdentityProvider,
    PermissionCode,
    Role,
    UserStatus,
)
from app.models.loyalty import LoyaltySettings, UserLoyaltyState
from app.repositories.customers import CustomerCreationReceipt
from app.repositories.identity import CardViewRecord
from app.security.rbac import Actor, load_actor
from app.services.customers import CustomerRequestMetadata, CustomerService

NOW = datetime(2026, 8, 24, 12, tzinfo=UTC)


class FakeCustomerRepository:
    def __init__(self) -> None:
        self.identities: dict[tuple[IdentityProvider, str], CustomerIdentity] = {}
        self.users: dict[UUID, User] = {}
        self.cards: dict[UUID, UserCard] = {}
        self.card_views: dict[UUID, CardViewRecord] = {}
        self.receipts: dict[str, CustomerCreationReceipt] = {}
        self.locks: list[tuple[str, str]] = []
        self.initialize_calls: list[dict[str, Any]] = []
        self.audits: list[AuditEvent] = []
        self.create_calls = 0
        self.commits = 0
        self.rollbacks = 0

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        try:
            yield
        except BaseException:
            self.rollbacks += 1
            raise
        else:
            self.commits += 1

    async def acquire_namespace_lock(self, namespace: str, value: str) -> None:
        self.locks.append((namespace, value))

    async def get_identity(
        self,
        *,
        provider: IdentityProvider,
        subject: str,
        for_update: bool = False,
    ) -> CustomerIdentity | None:
        assert isinstance(for_update, bool)
        return self.identities.get((provider, subject))

    async def list_identities(self, user_id: UUID) -> list[CustomerIdentity]:
        return [value for value in self.identities.values() if value.user_id == user_id]

    async def get_user(self, user_id: UUID, *, for_update: bool) -> User | None:
        assert isinstance(for_update, bool)
        return self.users.get(user_id)

    async def get_card(self, card_id: UUID) -> UserCard | None:
        return self.cards.get(card_id)

    def add(self, value: object) -> None:
        if isinstance(value, CustomerIdentity):
            self.identities[(value.provider, value.subject)] = value
        elif isinstance(value, AuditEvent):
            self.audits.append(value)
        else:
            raise AssertionError(f"Unexpected staged value: {type(value)!r}")

    async def get_creation_receipt(self, key: str) -> CustomerCreationReceipt | None:
        return self.receipts.get(key)

    async def get_loyalty_settings(self) -> LoyaltySettings | None:
        return None

    def create_phone_profile(
        self,
        *,
        phone: str,
        display_name: str,
        actor_staff_id: UUID,
        now: datetime,
    ) -> User:
        self.create_calls += 1
        user = User(
            id=uuid4(),
            telegram_id=None,
            first_name=display_name,
            status=UserStatus.ACTIVE,
            created_at=now,
            updated_at=now,
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
            created_at=now,
            updated_at=now,
        )
        self.users[user.id] = user
        self.identities[(identity.provider, identity.subject)] = identity
        return user

    def initialize_customer(
        self,
        *,
        user_id: UUID,
        qr_token: str,
        short_code: str,
        welcome_bonus_points: int,
        now: datetime,
        ip_address: str | None,
        user_agent: str | None,
        actor_user_id: UUID | None = None,
        actor_staff_id: UUID | None = None,
        event_type: str = "user.registered",
        event_idempotency_key: str | None = None,
        event_metadata: dict[str, Any] | None = None,
        enqueue_telegram_notification: bool = True,
    ) -> None:
        call = {
            "user_id": user_id,
            "qr_token": qr_token,
            "short_code": short_code,
            "welcome_bonus_points": welcome_bonus_points,
            "now": now,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "actor_user_id": actor_user_id,
            "actor_staff_id": actor_staff_id,
            "event_type": event_type,
            "event_idempotency_key": event_idempotency_key,
            "event_metadata": event_metadata,
            "enqueue_telegram_notification": enqueue_telegram_notification,
        }
        self.initialize_calls.append(call)
        user = self.users[user_id]
        card = UserCard(
            id=uuid4(),
            user_id=user_id,
            qr_token=qr_token,
            short_code=short_code,
            status=CardStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        loyalty_state = UserLoyaltyState(
            id=uuid4(),
            user_id=user_id,
            points_balance=welcome_bonus_points,
            visit_streak=0,
            allowed_misses_used=0,
            stamp_count=0,
            version=1,
            created_at=now,
            updated_at=now,
        )
        self.card_views[user_id] = CardViewRecord(
            user=user,
            card=card,
            loyalty_state=loyalty_state,
            settings=None,
        )
        self.cards[card.id] = card
        assert event_idempotency_key is not None
        metadata = event_metadata or {}
        request_hash = metadata.get("request_hash")
        self.receipts[event_idempotency_key] = CustomerCreationReceipt(
            event_type=event_type,
            request_hash=request_hash if isinstance(request_hash, str) else None,
            user_id=user_id,
            card_id=card.id,
            display_name=_optional_string(metadata.get("display_name")),
            masked_phone=_optional_string(metadata.get("masked_phone")),
            points_balance=_optional_integer(metadata.get("points_balance")),
        )

    async def flush(self) -> None:
        return None

    async def get_card_view(self, user_id: UUID) -> CardViewRecord | None:
        return self.card_views.get(user_id)


def _staff_actor() -> Actor:
    return Actor(
        user_id=uuid4(),
        telegram_id=42,
        session_id=uuid4(),
        role=Role.STAFF,
        staff_member_id=uuid4(),
        permissions=frozenset({PermissionCode.CUSTOMERS_CREATE}),
    )


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


@pytest.mark.asyncio
async def test_customer_identity_phone_creation_replays_private_original_snapshot() -> None:
    repository = FakeCustomerRepository()
    service = CustomerService(repository)
    actor = _staff_actor()
    key = str(uuid4())
    raw_phone = "+7 (999) 123-45-67"

    first = await service.create_phone_customer(
        actor,
        phone=raw_phone,
        display_name="  Мария   Кофейная ",
        idempotency_key=key,
        metadata=CustomerRequestMetadata(
            ip_address="127.0.0.1" * 10,
            user_agent="test-agent" * 100,
        ),
        now=NOW,
    )
    original_view = repository.card_views[first.user_id]
    repository.users[first.user_id].first_name = "Changed later"
    replacement_card = UserCard(
        id=uuid4(),
        user_id=first.user_id,
        qr_token="replacement-qr",
        short_code="REPLACED",
        status=CardStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
    )
    original_view.loyalty_state.points_balance = 999
    repository.cards[replacement_card.id] = replacement_card
    repository.card_views[first.user_id] = CardViewRecord(
        user=repository.users[first.user_id],
        card=replacement_card,
        loyalty_state=original_view.loyalty_state,
        settings=None,
    )
    replay = await service.create_phone_customer(
        actor,
        phone="89991234567",
        display_name="Мария Кофейная",
        idempotency_key=key,
        now=NOW,
    )

    assert first.user_id == replay.user_id
    assert replay.card_id == first.card_id
    assert replay.card_id != replacement_card.id
    assert replay.short_code == first.short_code
    assert replay.display_name == first.display_name
    assert replay.points_balance == first.points_balance == 0
    assert first.idempotent_replay is False
    assert replay.idempotent_replay is True
    assert first.display_name == "Мария Кофейная"
    assert first.masked_phone == "+7******4567"
    assert "+79991234567" not in first.masked_phone
    assert repository.users[first.user_id].telegram_id is None
    assert repository.create_calls == 1
    assert repository.commits == 2
    assert repository.rollbacks == 0
    assert repository.locks == [
        ("customer.phone.create", key),
        ("customer.identity.phone", "+79991234567"),
        ("customer.phone.create", key),
    ]

    initialization = repository.initialize_calls[0]
    assert initialization["enqueue_telegram_notification"] is False
    assert initialization["actor_user_id"] == actor.user_id
    assert initialization["actor_staff_id"] == actor.staff_member_id
    assert len(initialization["ip_address"]) == 45
    assert len(initialization["user_agent"]) == 512
    event_metadata = initialization["event_metadata"]
    assert event_metadata["identity_provider"] == "phone"
    assert event_metadata["phone_last4"] == "4567"
    assert len(event_metadata["request_hash"]) == 64
    assert "+79991234567" not in str(event_metadata)


@pytest.mark.asyncio
async def test_customer_identity_idempotency_key_rejects_changed_payload() -> None:
    repository = FakeCustomerRepository()
    service = CustomerService(repository)
    actor = _staff_actor()
    key = str(uuid4())

    await service.create_phone_customer(
        actor,
        phone="+79991234567",
        display_name="Мария",
        idempotency_key=key,
        now=NOW,
    )

    with pytest.raises(AppError) as raised:
        await service.create_phone_customer(
            actor,
            phone="+79991234567",
            display_name="Другое имя",
            idempotency_key=key,
            now=NOW,
        )

    assert raised.value.code == "idempotency_conflict"
    assert raised.value.status_code == 409
    assert repository.create_calls == 1
    assert repository.commits == 1
    assert repository.rollbacks == 1


@pytest.mark.asyncio
async def test_customer_identity_unique_phone_rejects_a_second_request() -> None:
    repository = FakeCustomerRepository()
    service = CustomerService(repository)
    actor = _staff_actor()

    await service.create_phone_customer(
        actor,
        phone="+79991234567",
        display_name="Мария",
        idempotency_key=str(uuid4()),
        now=NOW,
    )

    with pytest.raises(AppError) as raised:
        await service.create_phone_customer(
            actor,
            phone="8 999 123 45 67",
            display_name="Второй клиент",
            idempotency_key=str(uuid4()),
            now=NOW,
        )

    assert raised.value.code == "phone_already_registered"
    assert raised.value.status_code == 409
    assert repository.create_calls == 1
    assert repository.commits == 1
    assert repository.rollbacks == 1


def test_customer_identity_model_matches_migration_contract() -> None:
    table = cast(Table, CustomerIdentity.__table__)
    unique_names = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert unique_names == {"uq_customer_identities_provider_subject"}
    assert User.__table__.c.telegram_id.nullable is True


@pytest.mark.asyncio
async def test_customer_identity_phone_only_session_cannot_become_an_actor() -> None:
    user = User(
        id=uuid4(),
        telegram_id=None,
        first_name="Phone only",
        status=UserStatus.ACTIVE,
    )
    stored_session = Session(
        id=uuid4(),
        user_id=user.id,
        token_hash="irrelevant-to-fake",
        expires_at=NOW + timedelta(hours=1),
        user=user,
    )

    class FakeSession:
        async def scalar(self, _statement: object) -> Session:
            return stored_session

    with pytest.raises(AppError) as raised:
        await load_actor(
            cast(AsyncSession, FakeSession()),
            raw_token="test-token",
            pepper="test-pepper",
            now=NOW,
        )

    assert raised.value.code == "invalid_session"
    assert raised.value.status_code == 401
