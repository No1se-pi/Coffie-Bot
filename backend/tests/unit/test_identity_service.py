from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.config import AppEnvironment, Settings
from app.models.access import User
from app.models.cards import UserCard
from app.models.enums import CardStatus, LoyaltyOperationType, RewardStatus, Role, UserStatus
from app.models.loyalty import LoyaltySettings, UserLoyaltyState
from app.repositories.identity import (
    CardViewRecord,
    HistoryPageRecord,
    IdentityAccessRecord,
    RewardPageRecord,
)
from app.security.sessions import IssuedSessionToken
from app.security.telegram import TelegramUserData, VerifiedTelegramInitData
from app.services.identity import IdentityService

NOW = datetime(2026, 7, 21, 12, tzinfo=UTC)


class FakeVerifier:
    def __init__(self, user: TelegramUserData) -> None:
        self.user = user
        self.calls: list[tuple[str, datetime | None]] = []

    def verify(
        self,
        init_data: str,
        *,
        now: datetime | None = None,
    ) -> VerifiedTelegramInitData:
        self.calls.append((init_data, now))
        return VerifiedTelegramInitData(user=self.user, auth_date=now or NOW)


class FakeIdentityRepository:
    def __init__(self, *, welcome_bonus: int = 10) -> None:
        self.user: User | None = None
        self.card_view: CardViewRecord | None = None
        self.settings = _loyalty_settings(welcome_bonus)
        self.initialize_calls: list[dict[str, Any]] = []
        self.issued_sessions: list[IssuedSessionToken] = []
        self.commits = 0
        self.rollbacks = 0
        self.revoked: list[tuple[UUID, UUID]] = []

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        try:
            yield
        except BaseException:
            self.rollbacks += 1
            raise
        else:
            self.commits += 1

    async def upsert_telegram_user(
        self,
        telegram_user: TelegramUserData,
        *,
        now: datetime,
    ) -> tuple[User, bool]:
        created = self.user is None
        if self.user is None:
            self.user = User(
                id=uuid4(),
                telegram_id=telegram_user.id,
                first_name=telegram_user.first_name,
                last_name=telegram_user.last_name,
                username=telegram_user.username,
                language_code=telegram_user.language_code,
                photo_url=telegram_user.photo_url,
                status=UserStatus.ACTIVE,
                last_seen_at=now,
                created_at=now,
                updated_at=now,
            )
        else:
            self.user.first_name = telegram_user.first_name
            self.user.last_seen_at = now
        return self.user, created

    async def get_loyalty_settings(self) -> LoyaltySettings | None:
        return self.settings

    def initialize_customer(self, **kwargs: Any) -> None:
        self.initialize_calls.append(kwargs)
        assert self.user is not None
        state = UserLoyaltyState(
            id=uuid4(),
            user_id=self.user.id,
            points_balance=kwargs["welcome_bonus_points"],
            visit_streak=0,
            allowed_misses_used=0,
            stamp_count=0,
            version=1,
            created_at=kwargs["now"],
            updated_at=kwargs["now"],
        )
        card = UserCard(
            id=uuid4(),
            user_id=self.user.id,
            qr_token=kwargs["qr_token"],
            short_code=kwargs["short_code"],
            status=CardStatus.ACTIVE,
            created_at=kwargs["now"],
            updated_at=kwargs["now"],
        )
        self.card_view = CardViewRecord(
            user=self.user,
            card=card,
            loyalty_state=state,
            settings=self.settings,
        )

    def create_session(
        self,
        *,
        user_id: UUID,
        issued: IssuedSessionToken,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None:
        assert self.user is not None
        assert user_id == self.user.id
        assert len(ip_address or "") <= 45
        assert len(user_agent or "") <= 512
        self.issued_sessions.append(issued)

    async def flush(self) -> None:
        return None

    async def get_identity_access(self, user_id: UUID) -> IdentityAccessRecord | None:
        if self.user is None or self.user.id != user_id:
            return None
        return IdentityAccessRecord(user=self.user, staff=None)

    async def get_card_view(self, user_id: UUID) -> CardViewRecord | None:
        if self.user is None or self.user.id != user_id:
            return None
        return self.card_view

    async def revoke_session(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
        now: datetime,
    ) -> None:
        assert now.tzinfo is not None
        self.revoked.append((session_id, user_id))

    async def list_history(
        self,
        *,
        user_id: UUID,
        operation_type: LoyaltyOperationType | None,
        page: int,
        page_size: int,
    ) -> HistoryPageRecord:
        return HistoryPageRecord(items=[], total=0)

    async def list_rewards(
        self,
        *,
        user_id: UUID,
        reward_status: RewardStatus | None,
        page: int,
        page_size: int,
    ) -> RewardPageRecord:
        return RewardPageRecord(items=[], total=0)


def _settings(**overrides: Any) -> Settings:
    return Settings(
        app_env=AppEnvironment.TEST,
        session_token_pepper="test-session-pepper",
        **overrides,
    )


def _telegram_user(user_id: int = 42) -> TelegramUserData:
    return TelegramUserData(
        id=user_id,
        first_name="Ярослав",
        username="coffee_guest",
        language_code="ru",
    )


def _loyalty_settings(welcome_bonus: int) -> LoyaltySettings:
    return LoyaltySettings(
        id=uuid4(),
        singleton_key="default",
        currency_name="баллы",
        currency_code="RUB",
        points_enabled=True,
        welcome_bonus_points=welcome_bonus,
        visit_required_count=5,
        stamp_required_count=9,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.asyncio
async def test_registration_is_repeat_safe_and_initializes_welcome_state_once() -> None:
    repository = FakeIdentityRepository(welcome_bonus=10)
    service = IdentityService(settings=_settings(), repository=repository)

    first = await service.register_telegram_user(_telegram_user(), now=NOW)
    second = await service.register_telegram_user(_telegram_user(), now=NOW)

    assert first.created is True
    assert second.created is False
    assert first.identity.user.id == second.identity.user.id
    assert first.identity.role is Role.CUSTOMER
    assert len(repository.initialize_calls) == 1
    initialization = repository.initialize_calls[0]
    assert initialization["welcome_bonus_points"] == 10
    assert "42" not in initialization["qr_token"]
    assert len(initialization["short_code"]) == 8
    assert first.card.loyalty_state.points_balance == 10
    assert repository.commits == 2


@pytest.mark.asyncio
async def test_registration_completes_customer_state_for_cli_created_owner() -> None:
    repository = FakeIdentityRepository(welcome_bonus=10)
    repository.user = User(
        id=uuid4(),
        telegram_id=42,
        first_name="Local owner",
        status=UserStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
    )
    service = IdentityService(settings=_settings(), repository=repository)

    result = await service.register_telegram_user(_telegram_user(), now=NOW)

    assert result.created is False
    assert result.card.loyalty_state.points_balance == 10
    assert len(repository.initialize_calls) == 1


@pytest.mark.asyncio
async def test_authentication_uses_verifier_and_stores_only_issued_hash() -> None:
    repository = FakeIdentityRepository()
    verifier = FakeVerifier(_telegram_user())
    service = IdentityService(
        settings=_settings(),
        repository=repository,
        verifier=verifier,
    )

    result = await service.authenticate(
        "signed-telegram-init-data",
        ip_address="127.0.0.1",
        user_agent="test-client",
        now=NOW,
    )

    assert verifier.calls == [("signed-telegram-init-data", NOW)]
    assert result.access_token.startswith("cbs_")
    assert repository.issued_sessions[0].raw_token == result.access_token
    assert repository.issued_sessions[0].token_hash != result.access_token
    assert result.registration.identity.user.telegram_id == 42


@pytest.mark.asyncio
async def test_dev_auth_bypasses_verifier_only_in_development() -> None:
    development_repository = FakeIdentityRepository()
    development = IdentityService(
        settings=Settings(
            app_env=AppEnvironment.DEVELOPMENT,
            dev_auth_enabled=True,
            dev_auth_telegram_id=777,
        ),
        repository=development_repository,
    )

    result = await development.authenticate("", now=NOW)

    assert result.registration.identity.user.telegram_id == 777

    test_service = IdentityService(
        settings=_settings(dev_auth_enabled=True, dev_auth_telegram_id=777),
        repository=FakeIdentityRepository(),
    )
    with pytest.raises(RuntimeError, match="only allowed in development"):
        await test_service.authenticate("", now=NOW)


@pytest.mark.asyncio
async def test_logout_revokes_only_the_actor_session() -> None:
    repository = FakeIdentityRepository()
    service = IdentityService(settings=_settings(), repository=repository)
    session_id = uuid4()
    user_id = uuid4()

    await service.logout(session_id=session_id, user_id=user_id, now=NOW)

    assert repository.revoked == [(session_id, user_id)]
    assert repository.commits == 1
