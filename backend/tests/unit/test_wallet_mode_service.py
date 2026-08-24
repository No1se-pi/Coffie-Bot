from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

import pytest

from app.models.access import User
from app.models.content import Venue
from app.models.enums import (
    PermissionCode,
    PointLotSourceType,
    Role,
    UserStatus,
    WalletMode,
)
from app.models.loyalty import LoyaltySettings, UserLoyaltyState
from app.models.loyalty_v2 import (
    LoyaltyWallet,
    PointLot,
    PointLotRoute,
    WalletModeSwitch,
    WalletTransfer,
)
from app.repositories.loyalty_v2 import LotRouteDestination
from app.security.rbac import Actor
from app.services.wallet_mode import WalletModeService

NOW = datetime(2026, 8, 24, 12, tzinfo=UTC)


class FakeModeRepository:
    def __init__(self) -> None:
        self.settings = LoyaltySettings(
            id=uuid4(),
            singleton_key="default",
            wallet_mode=WalletMode.SHARED,
        )
        self.user = User(id=uuid4(), first_name="Клиент", status=UserStatus.ACTIVE)
        self.state = UserLoyaltyState(
            id=uuid4(),
            user_id=self.user.id,
            points_balance=50,
            visit_streak=0,
            allowed_misses_used=0,
            stamp_count=0,
            version=1,
        )
        self.primary = _venue("primary")
        self.fallback = _venue("fallback")
        self.archived = _venue("archived", active=False, archived=True)
        self.venues = [self.primary, self.fallback, self.archived]
        master = LoyaltyWallet(
            id=uuid4(),
            user_id=self.user.id,
            venue_id=None,
            balance_points=50,
            version=1,
        )
        self.wallets = [master]
        self.lots = [
            _lot(master.id, points=30, source_venue_id=self.primary.id),
            _lot(master.id, points=20, source_venue_id=None, opening=True),
            _lot(master.id, points=0, source_venue_id=self.archived.id),
        ]
        self.switches: list[WalletModeSwitch] = []
        self.routes: list[PointLotRoute] = []
        self.transfers: list[WalletTransfer] = []
        self.added: list[object] = []

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        yield

    async def acquire_idempotency_lock(self, namespace: str, key: str) -> None:
        assert namespace == "wallet-mode"
        assert key

    async def get_settings(
        self,
        *,
        lock_mode: Literal["none", "share", "update"] = "none",
    ) -> LoyaltySettings | None:
        return self.settings

    async def list_venues(self, *, for_update: bool = False) -> list[Venue]:
        return self.venues

    async def list_users_states(
        self,
        *,
        for_update: bool,
    ) -> list[tuple[User, UserLoyaltyState]]:
        return [(self.user, self.state)]

    async def list_all_wallets(self, *, for_update: bool) -> list[LoyaltyWallet]:
        return self.wallets

    async def list_all_lots(self, *, for_update: bool) -> list[PointLot]:
        return self.lots

    async def list_routed_source_lot_ids(self) -> list[UUID]:
        return sorted({route.source_lot_id for route in self.routes})

    async def latest_route(self, source_lot_id: UUID) -> LotRouteDestination | None:
        current = source_lot_id
        terminal: LotRouteDestination | None = None
        for _ in range(10):
            candidates = [route for route in self.routes if route.source_lot_id == current]
            if not candidates:
                return terminal
            latest = max(
                candidates,
                key=lambda route: (
                    next(
                        switch.completed_at
                        for switch in self.switches
                        if switch.id == route.switch_id
                    ),
                    route.id,
                ),
            )
            switched_at = next(
                switch.completed_at for switch in self.switches if switch.id == latest.switch_id
            )
            terminal = LotRouteDestination(
                wallet_id=latest.destination_wallet_id,
                lot_id=latest.destination_lot_id,
                routed_at=switched_at,
            )
            if latest.destination_lot_id is None:
                return terminal
            current = latest.destination_lot_id
        raise RuntimeError("test route cycle")

    async def latest_route_timestamp(self) -> datetime | None:
        return max((switch.completed_at for switch in self.switches), default=None)

    async def get_mode_switch_by_idempotency_key(
        self,
        key: str,
    ) -> WalletModeSwitch | None:
        return next((switch for switch in self.switches if switch.idempotency_key == key), None)

    async def count_wallet_transfers(self, switch_id: UUID) -> int:
        return len([item for item in self.transfers if item.switch_id == switch_id])

    async def wallet_total(self, user_id: UUID) -> int:
        return sum(wallet.balance_points for wallet in self.wallets if wallet.user_id == user_id)

    async def lot_total(self, wallet_id: UUID) -> int:
        return sum(lot.remaining_points for lot in self.lots if lot.wallet_id == wallet_id)

    async def list_wallets(
        self,
        user_id: UUID,
        *,
        for_update: bool,
    ) -> list[LoyaltyWallet]:
        return [wallet for wallet in self.wallets if wallet.user_id == user_id]

    def add(self, value: object) -> None:
        self.added.append(value)
        if isinstance(value, LoyaltyWallet):
            self.wallets.append(value)
        elif isinstance(value, PointLot):
            self.lots.append(value)
        elif isinstance(value, WalletModeSwitch):
            self.switches.append(value)
        elif isinstance(value, PointLotRoute):
            self.routes.append(value)
        elif isinstance(value, WalletTransfer):
            self.transfers.append(value)

    def add_all(self, values: list[object]) -> None:
        for value in values:
            self.add(value)

    async def flush(self) -> None:
        return None


def _venue(slug: str, *, active: bool = True, archived: bool = False) -> Venue:
    return Venue(
        id=uuid4(),
        slug=slug,
        name=slug.title(),
        is_active=active,
        archived_at=(NOW if archived else None),
    )


def _lot(
    wallet_id: UUID,
    *,
    points: int,
    source_venue_id: UUID | None,
    opening: bool = False,
) -> PointLot:
    return PointLot(
        id=uuid4(),
        wallet_id=wallet_id,
        source_operation_id=(None if opening else uuid4()),
        source_venue_id=source_venue_id,
        source_type=(PointLotSourceType.OPENING_BALANCE if opening else PointLotSourceType.ACCRUAL),
        initial_points=max(points, 1),
        remaining_points=points,
        earned_at=NOW,
        expires_at=None,
        expiry_reminder_scheduled_at=(NOW if points == 30 else None),
    )


def _owner() -> Actor:
    return Actor(
        user_id=uuid4(),
        telegram_id=1,
        session_id=uuid4(),
        role=Role.OWNER,
        staff_member_id=uuid4(),
        permissions=frozenset({PermissionCode.OWNER_CRITICAL_SETTINGS}),
    )


@pytest.mark.asyncio
async def test_mode_switch_conserves_lots_routes_reminders_and_replays() -> None:
    repository = FakeModeRepository()
    service = WalletModeService(repository)  # type: ignore[arg-type]
    actor = _owner()

    unresolved = await service.preview(
        actor,
        target_mode=WalletMode.SEPARATE,
        fallback_venue_id=None,
    )
    assert unresolved.fallback_required is True
    assert unresolved.unresolved_points == 20
    preview = await service.preview(
        actor,
        target_mode=WalletMode.SEPARATE,
        fallback_venue_id=repository.fallback.id,
    )
    first = await service.confirm(
        actor,
        target_mode=WalletMode.SEPARATE,
        fallback_venue_id=repository.fallback.id,
        preview_hash=preview.preview_hash,
        reason="Разделение программы",
        idempotency_key="switch-to-separate",
        now=NOW,
    )
    replay = await service.confirm(
        actor,
        target_mode=WalletMode.SEPARATE,
        fallback_venue_id=repository.fallback.id,
        preview_hash=preview.preview_hash,
        reason="Разделение программы",
        idempotency_key="switch-to-separate",
        now=NOW,
    )

    assert first.total_balance_points == replay.total_balance_points == 50
    assert replay.idempotent_replay is True
    assert repository.settings.wallet_mode is WalletMode.SEPARATE
    assert sum(wallet.balance_points for wallet in repository.wallets) == 50
    assert len(repository.routes) == 3
    transferred_primary = next(
        lot for lot in repository.lots if lot.transferred_from_lot_id == repository.lots[0].id
    )
    assert transferred_primary.expiry_reminder_scheduled_at == NOW

    inverse_preview = await service.preview(
        actor,
        target_mode=WalletMode.SHARED,
        fallback_venue_id=None,
    )
    inverse = await service.confirm(
        actor,
        target_mode=WalletMode.SHARED,
        fallback_venue_id=None,
        preview_hash=inverse_preview.preview_hash,
        reason="Возврат общего режима",
        idempotency_key="switch-to-shared",
        now=NOW,
    )

    assert inverse.total_balance_points == 50
    assert repository.settings.wallet_mode is WalletMode.SHARED
    master = next(wallet for wallet in repository.wallets if wallet.venue_id is None)
    assert master.balance_points == 50
    zero_root = repository.lots[2]
    terminal = await repository.latest_route(zero_root.id)
    assert terminal is not None
    assert terminal.wallet_id == master.id
    assert repository.switches[1].completed_at > repository.switches[0].completed_at
