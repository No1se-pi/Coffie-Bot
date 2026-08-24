from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

import pytest

from app.core.errors import AppError
from app.models.access import User
from app.models.audit import AuditEvent
from app.models.cards import UserCard
from app.models.content import Venue
from app.models.enums import CardStatus, PermissionCode, Role, UserStatus, WalletMode
from app.models.loyalty import LoyaltySettings, UserLoyaltyState
from app.models.loyalty_v2 import LoyaltyWallet, PointLot
from app.repositories.loyalty import LoyaltyContext, UserPage
from app.schemas.loyalty import admin_user_response, user_page_response
from app.security.rbac import Actor
from app.services.loyalty_v2 import LoyaltyV2Service

NOW = datetime(2026, 8, 24, 12, tzinfo=UTC)


class FakeRepository:
    def __init__(self) -> None:
        self.settings = LoyaltySettings(
            id=uuid4(),
            singleton_key="default",
            currency_name="баллы",
            currency_code="RUB",
            points_enabled=True,
            minor_units_per_point=1000,
            redemption_minor_units_per_point=100,
            minimum_purchase_minor=0,
            maximum_purchase_minor=1_000_000,
            maximum_redemption_percent=50,
            minimum_redemption_points=1,
            welcome_bonus_points=0,
            wallet_mode=WalletMode.SHARED,
            points_expiry_months=6,
            expiry_reminder_days=14,
            birthday_promotion_enabled=True,
            birthday_discount_basis_points=1000,
            birthday_window_days=1,
            birthday_stackable=False,
            timezone="Europe/Moscow",
            visit_required_count=5,
            visit_daily_limit=1,
            visit_allowed_misses=0,
            stamp_required_count=9,
            stamps_per_purchase=1,
            stamp_operation_limit=1,
            created_at=NOW,
            updated_at=NOW,
        )
        self.user = User(
            id=uuid4(),
            telegram_id=42,
            first_name="Гость",
            status=UserStatus.ACTIVE,
            created_at=NOW,
            updated_at=NOW,
        )
        self.venues: list[Venue] = []
        self.wallet_rows: list[tuple[LoyaltyWallet, Venue | None]] = []
        self.lots: dict[UUID, list[PointLot]] = {}
        self.birthday_venues: list[Venue] = []
        self.added: list[object] = []

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        yield

    async def get_settings(
        self,
        *,
        lock_mode: Literal["none", "share", "update"] = "none",
    ) -> LoyaltySettings | None:
        assert lock_mode in {"none", "share", "update"}
        return self.settings

    async def get_user(self, user_id: UUID, *, for_update: bool) -> User | None:
        assert user_id == self.user.id
        return self.user

    async def list_wallet_views(self, user_id: UUID) -> list[tuple[LoyaltyWallet, Venue | None]]:
        assert user_id == self.user.id
        return self.wallet_rows

    async def list_lots_for_wallets(
        self,
        wallet_ids: list[UUID],
        *,
        for_update: bool,
    ) -> list[PointLot]:
        return [lot for wallet_id in wallet_ids for lot in self.lots.get(wallet_id, [])]

    async def list_birthday_venues(self, settings_id: UUID) -> list[Venue]:
        assert settings_id == self.settings.id
        return self.birthday_venues

    async def list_venues(self, *, for_update: bool = False) -> list[Venue]:
        return self.venues

    async def replace_birthday_venues(
        self,
        *,
        settings_id: UUID,
        venue_ids: list[UUID],
    ) -> None:
        self.birthday_venues = [venue for venue in self.venues if venue.id in venue_ids]

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None


def _actor(user_id: UUID) -> Actor:
    return Actor(
        user_id=user_id,
        telegram_id=42,
        session_id=uuid4(),
        role=Role.CUSTOMER,
        staff_member_id=None,
        permissions=frozenset(),
    )


def _admin_actor(*permissions: PermissionCode) -> Actor:
    return Actor(
        user_id=uuid4(),
        telegram_id=99,
        session_id=uuid4(),
        role=Role.ADMIN,
        staff_member_id=uuid4(),
        permissions=frozenset(permissions),
    )


def _venue(*, active: bool = True, archived: bool = False) -> Venue:
    return Venue(
        id=uuid4(),
        slug=f"venue-{uuid4().hex[:8]}",
        name="Точка",
        is_active=active,
        archived_at=(NOW if archived else None),
    )


def _lot(
    wallet_id: UUID,
    *,
    points: int,
    expires_at: datetime | None,
) -> PointLot:
    return PointLot(
        id=uuid4(),
        wallet_id=wallet_id,
        source_operation_id=uuid4(),
        source_venue_id=None,
        source_type="accrual",
        initial_points=points,
        remaining_points=points,
        earned_at=NOW - timedelta(days=30),
        expires_at=expires_at,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.asyncio
async def test_wallet_view_excludes_due_points_but_keeps_archived_wallet_visible() -> None:
    repository = FakeRepository()
    repository.settings.wallet_mode = WalletMode.SEPARATE
    venue = _venue(active=False, archived=True)
    wallet = LoyaltyWallet(
        id=uuid4(),
        user_id=repository.user.id,
        venue_id=venue.id,
        balance_points=35,
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    repository.wallet_rows = [(wallet, venue)]
    repository.lots[wallet.id] = [
        _lot(wallet.id, points=20, expires_at=NOW - timedelta(seconds=1)),
        _lot(wallet.id, points=15, expires_at=NOW + timedelta(days=3)),
    ]

    value = await LoyaltyV2Service(repository).get_wallets(_actor(repository.user.id), now=NOW)

    assert value.total_balance == 15
    assert value.entries[0].balance == 15
    assert value.entries[0].expiring_amount == 15
    assert value.entries[0].venue is not None
    assert value.entries[0].venue.available is False


@pytest.mark.asyncio
async def test_birthday_exact_put_retry_is_idempotent_but_change_is_locked() -> None:
    repository = FakeRepository()
    service = LoyaltyV2Service(repository)
    actor = _actor(repository.user.id)

    first = await service.set_birthday(actor, month=8, day=24, now=NOW)
    replay = await service.set_birthday(actor, month=8, day=24, now=NOW)

    assert first.birthday == replay.birthday
    audits = [item for item in repository.added if isinstance(item, AuditEvent)]
    assert len(audits) == 1
    assert audits[0].event_metadata == {"birthday_set": True}
    with pytest.raises(AppError) as raised:
        await service.set_birthday(actor, month=8, day=25, now=NOW)
    assert raised.value.code == "birthday_locked"


@pytest.mark.asyncio
async def test_february_29_offer_is_observed_on_february_28() -> None:
    repository = FakeRepository()
    repository.user.birthday_month = 2
    repository.user.birthday_day = 29
    repository.user.birthday_set_at = NOW
    value = await LoyaltyV2Service(repository).get_birthday(
        _actor(repository.user.id),
        now=datetime(2027, 2, 28, 12, tzinfo=UTC),
    )

    assert value.offer is not None
    assert value.offer.active_now is True
    assert value.offer.starts_on == datetime(2027, 2, 28, tzinfo=UTC).date()


@pytest.mark.asyncio
async def test_birthday_window_reports_previous_year_occurrence_across_new_year() -> None:
    repository = FakeRepository()
    repository.settings.birthday_window_days = 2
    repository.user.birthday_month = 12
    repository.user.birthday_day = 31
    repository.user.birthday_set_at = NOW

    value = await LoyaltyV2Service(repository).get_birthday(
        _actor(repository.user.id),
        now=datetime(2027, 1, 1, 12, tzinfo=UTC),
    )

    assert value.offer is not None
    assert value.offer.active_now is True
    assert value.offer.starts_on == date(2026, 12, 31)
    assert value.offer.ends_on == date(2027, 1, 1)


@pytest.mark.asyncio
async def test_birthday_empty_venue_set_means_all_active_only() -> None:
    repository = FakeRepository()
    active = _venue()
    archived = _venue(active=False, archived=True)
    repository.venues = [active, archived]
    repository.user.birthday_month = 8
    repository.user.birthday_day = 24
    repository.user.birthday_set_at = NOW

    value = await LoyaltyV2Service(repository).get_birthday(
        _actor(repository.user.id),
        now=NOW,
    )

    assert value.offer is not None
    assert [venue.id for venue in value.offer.eligible_venues] == [active.id]


@pytest.mark.asyncio
async def test_admin_birthday_retry_is_noop_and_unavailable_account_is_rejected() -> None:
    repository = FakeRepository()
    service = LoyaltyV2Service(repository)
    actor = _admin_actor(PermissionCode.ADMIN_USERS_MANAGE)

    first = await service.admin_set_birthday(
        actor,
        user_id=repository.user.id,
        month=8,
        day=24,
        reason="Подтверждено клиентом",
        now=NOW,
    )
    replay = await service.admin_set_birthday(
        actor,
        user_id=repository.user.id,
        month=8,
        day=24,
        reason="Повтор запроса",
        now=NOW + timedelta(seconds=1),
    )

    assert first == replay
    audits = [item for item in repository.added if isinstance(item, AuditEvent)]
    assert len(audits) == 1
    assert audits[0].event_metadata == {
        "previous_was_set": False,
        "changed": True,
        "reason": "Подтверждено клиентом",
    }
    repository.user.status = UserStatus.MERGED
    with pytest.raises(AppError) as raised:
        await service.admin_set_birthday(
            actor,
            user_id=repository.user.id,
            month=8,
            day=25,
            reason="Коррекция данных",
            now=NOW,
        )
    assert raised.value.code == "account_unavailable"


def test_admin_user_detail_exposes_birthday_without_leaking_it_to_list() -> None:
    repository = FakeRepository()
    repository.user.birthday_month = 8
    repository.user.birthday_day = 24
    repository.user.birthday_set_at = NOW
    card = UserCard(
        id=uuid4(),
        user_id=repository.user.id,
        qr_token="opaque-test-token",
        short_code="TEST1234",
        status=CardStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
    )
    state = UserLoyaltyState(
        id=uuid4(),
        user_id=repository.user.id,
        points_balance=0,
        visit_streak=0,
        allowed_misses_used=0,
        stamp_count=0,
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    context = LoyaltyContext(
        user=repository.user,
        card=card,
        state=state,
        settings=repository.settings,
    )

    detail = admin_user_response(context).model_dump(mode="json")
    listing = user_page_response(UserPage(items=[repository.user], total=1), page=1, page_size=20)
    list_item = listing.items[0].model_dump(mode="json")

    assert detail["birthday"] == {"month": 8, "day": 24}
    assert detail["birthday_locked"] is True
    assert "birthday" not in list_item
    assert "birthday_locked" not in list_item
