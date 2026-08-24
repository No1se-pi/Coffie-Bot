"""PostgreSQL adapter for Loyalty V2 wallets, lots, and deterministic locking."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import delete, func, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.access import User
from app.models.content import Location, Venue
from app.models.customers import CustomerIdentity
from app.models.enums import IdentityProvider, LoyaltyOperationType
from app.models.loyalty import LoyaltyOperation, LoyaltySettings, UserLoyaltyState
from app.models.loyalty_v2 import (
    AccountMergeLotRoute,
    BirthdayPromotionVenue,
    LoyaltyWallet,
    PointAllocation,
    PointLot,
    PointLotRoute,
    WalletModeSwitch,
    WalletTransfer,
)


@dataclass(frozen=True, slots=True)
class LocationVenue:
    location: Location
    venue: Venue | None


@dataclass(frozen=True, slots=True)
class LotRouteDestination:
    wallet_id: UUID
    lot_id: UUID | None
    routed_at: datetime


@dataclass(frozen=True, slots=True)
class LockedLotOwner:
    user: User
    state: UserLoyaltyState
    wallet: LoyaltyWallet
    lot: PointLot


class PointLedgerRepository:
    """Low-level queries shared by loyalty, registration, merge, and worker services.

    Mutating callers acquire locks in one global order: settings, users/state,
    wallets, then lots.  Keeping that order here prevents spend, expiry, merge,
    and mode-switch transactions from constructing inverse deadlocks.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def transaction(self) -> AbstractAsyncContextManager[None]:
        return self._transaction()

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[None]:
        if not self._session.in_transaction():
            async with self._session.begin():
                yield
            return
        try:
            yield
        except BaseException:
            await self._session.rollback()
            raise
        else:
            await self._session.commit()

    async def acquire_idempotency_lock(self, namespace: str, key: str) -> None:
        digest = hashlib.sha256(f"{namespace}:{key}".encode()).digest()
        lock_id = int.from_bytes(digest[:8], byteorder="big", signed=True)
        await self._session.execute(select(func.pg_advisory_xact_lock(lock_id)))

    async def get_settings(
        self,
        *,
        lock_mode: Literal["none", "share", "update"] = "none",
    ) -> LoyaltySettings | None:
        """Read the singleton settings row with the requested PostgreSQL lock.

        Ordinary point mutations take ``FOR SHARE`` so customers at unrelated
        wallets can proceed concurrently while still excluding an owner mode
        switch.  Settings edits and a mode switch take ``FOR UPDATE``.
        """

        statement = select(LoyaltySettings).where(LoyaltySettings.singleton_key == "default")
        if lock_mode == "share":
            statement = statement.with_for_update(read=True)
        elif lock_mode == "update":
            statement = statement.with_for_update()
        return cast(LoyaltySettings | None, await self._session.scalar(statement))

    async def get_operation_by_idempotency(
        self,
        *,
        operation_type: LoyaltyOperationType,
        idempotency_key: str,
    ) -> LoyaltyOperation | None:
        return cast(
            LoyaltyOperation | None,
            await self._session.scalar(
                select(LoyaltyOperation).where(
                    LoyaltyOperation.operation_type == operation_type,
                    LoyaltyOperation.idempotency_key == idempotency_key,
                )
            ),
        )

    async def get_venue(self, venue_id: UUID, *, for_update: bool = False) -> Venue | None:
        statement = select(Venue).where(Venue.id == venue_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(Venue | None, await self._session.scalar(statement))

    async def list_venues(self, *, for_update: bool = False) -> list[Venue]:
        statement = select(Venue).order_by(Venue.sort_order, Venue.name, Venue.id)
        if for_update:
            statement = statement.with_for_update()
        return list(await self._session.scalars(statement))

    async def get_location_venue(
        self,
        location_id: UUID,
        *,
        for_update: bool = False,
    ) -> LocationVenue | None:
        """Load one physical location and its venue with a stable lock order.

        PostgreSQL cannot lock the nullable side of the previous outer join.
        Mutating callers therefore lock Location first and its referenced Venue
        second, then calculate and persist provenance from this one snapshot.
        """

        statement = select(Location).where(Location.id == location_id)
        if for_update:
            statement = statement.with_for_update()
        location = cast(Location | None, await self._session.scalar(statement))
        if location is None:
            return None
        venue = (
            await self.get_venue(location.venue_id, for_update=for_update)
            if location.venue_id is not None
            else None
        )
        return LocationVenue(location=location, venue=venue)

    async def get_default_location_venue(
        self,
        *,
        for_update: bool = False,
    ) -> LocationVenue | None:
        """Resolve and optionally lock the trusted legacy default once."""

        statement = (
            select(Location)
            .where(
                Location.is_default.is_(True),
                Location.is_active.is_(True),
                Location.venue_id.is_not(None),
            )
            .order_by(Location.id)
            .limit(1)
        )
        if for_update:
            statement = statement.with_for_update()
        location = cast(Location | None, await self._session.scalar(statement))
        if location is None:
            return None
        if location.venue_id is None:  # Narrowed by SQL; defensive for type checkers.
            return LocationVenue(location=location, venue=None)
        venue = await self.get_venue(location.venue_id, for_update=for_update)
        return LocationVenue(location=location, venue=venue)

    async def lock_user_state(self, user_id: UUID) -> tuple[User, UserLoyaltyState] | None:
        row = (
            await self._session.execute(
                select(User, UserLoyaltyState)
                .join(UserLoyaltyState, UserLoyaltyState.user_id == User.id)
                .where(User.id == user_id)
                .with_for_update(of=[User, UserLoyaltyState])
            )
        ).one_or_none()
        return None if row is None else (row[0], row[1])

    async def get_user(self, user_id: UUID, *, for_update: bool) -> User | None:
        statement = select(User).where(User.id == user_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(User | None, await self._session.scalar(statement))

    async def list_users_states(
        self,
        *,
        for_update: bool,
    ) -> list[tuple[User, UserLoyaltyState]]:
        statement = (
            select(User, UserLoyaltyState)
            .join(UserLoyaltyState, UserLoyaltyState.user_id == User.id)
            .order_by(User.id, UserLoyaltyState.id)
        )
        if for_update:
            statement = statement.with_for_update(of=[User, UserLoyaltyState])
        rows = (await self._session.execute(statement)).all()
        return [(row[0], row[1]) for row in rows]

    async def list_users_states_for_update(self) -> list[tuple[User, UserLoyaltyState]]:
        return await self.list_users_states(for_update=True)

    async def get_wallet(
        self,
        *,
        user_id: UUID,
        venue_id: UUID | None,
        for_update: bool,
    ) -> LoyaltyWallet | None:
        statement = select(LoyaltyWallet).where(
            LoyaltyWallet.user_id == user_id,
            (
                LoyaltyWallet.venue_id.is_(None)
                if venue_id is None
                else LoyaltyWallet.venue_id == venue_id
            ),
        )
        if for_update:
            statement = statement.with_for_update()
        return cast(LoyaltyWallet | None, await self._session.scalar(statement))

    async def get_wallet_by_id(
        self,
        *,
        user_id: UUID,
        wallet_id: UUID,
        for_update: bool,
    ) -> LoyaltyWallet | None:
        statement = select(LoyaltyWallet).where(
            LoyaltyWallet.id == wallet_id,
            LoyaltyWallet.user_id == user_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return cast(LoyaltyWallet | None, await self._session.scalar(statement))

    async def list_wallets(
        self,
        user_id: UUID,
        *,
        for_update: bool,
    ) -> list[LoyaltyWallet]:
        statement = (
            select(LoyaltyWallet)
            .where(LoyaltyWallet.user_id == user_id)
            .order_by(LoyaltyWallet.venue_id, LoyaltyWallet.id)
        )
        if for_update:
            statement = statement.with_for_update()
        return list(await self._session.scalars(statement))

    async def list_wallets_for_users(
        self,
        user_ids: list[UUID],
        *,
        for_update: bool,
    ) -> list[LoyaltyWallet]:
        statement = (
            select(LoyaltyWallet)
            .where(LoyaltyWallet.user_id.in_(user_ids))
            .order_by(LoyaltyWallet.user_id, LoyaltyWallet.venue_id, LoyaltyWallet.id)
        )
        if for_update:
            statement = statement.with_for_update()
        return list(await self._session.scalars(statement))

    async def list_all_wallets(self, *, for_update: bool) -> list[LoyaltyWallet]:
        statement = select(LoyaltyWallet).order_by(
            LoyaltyWallet.user_id,
            LoyaltyWallet.venue_id,
            LoyaltyWallet.id,
        )
        if for_update:
            statement = statement.with_for_update()
        return list(await self._session.scalars(statement))

    async def lock_wallets_by_ids(
        self,
        *,
        user_id: UUID,
        wallet_ids: set[UUID],
    ) -> list[LoyaltyWallet]:
        if not wallet_ids:
            return []
        return list(
            await self._session.scalars(
                select(LoyaltyWallet)
                .where(
                    LoyaltyWallet.user_id == user_id,
                    LoyaltyWallet.id.in_(wallet_ids),
                )
                .order_by(LoyaltyWallet.id)
                .with_for_update()
            )
        )

    async def list_lots(
        self,
        wallet_id: UUID,
        *,
        for_update: bool,
        remaining_only: bool = False,
    ) -> list[PointLot]:
        statement = select(PointLot).where(PointLot.wallet_id == wallet_id)
        if remaining_only:
            statement = statement.where(PointLot.remaining_points > 0)
        statement = statement.order_by(PointLot.earned_at, PointLot.id)
        if for_update:
            statement = statement.with_for_update()
        return list(await self._session.scalars(statement))

    async def list_lots_for_wallets(
        self,
        wallet_ids: list[UUID],
        *,
        for_update: bool,
    ) -> list[PointLot]:
        if not wallet_ids:
            return []
        statement = (
            select(PointLot)
            .where(PointLot.wallet_id.in_(wallet_ids))
            .order_by(PointLot.wallet_id, PointLot.earned_at, PointLot.id)
        )
        if for_update:
            statement = statement.with_for_update()
        return list(await self._session.scalars(statement))

    async def list_all_lots(self, *, for_update: bool) -> list[PointLot]:
        statement = select(PointLot).order_by(
            PointLot.wallet_id,
            PointLot.earned_at,
            PointLot.id,
        )
        if for_update:
            statement = statement.with_for_update()
        return list(await self._session.scalars(statement))

    async def lock_lots_by_ids(self, lot_ids: set[UUID]) -> list[PointLot]:
        if not lot_ids:
            return []
        return list(
            await self._session.scalars(
                select(PointLot)
                .where(PointLot.id.in_(lot_ids))
                .order_by(PointLot.wallet_id, PointLot.earned_at, PointLot.id)
                .with_for_update()
            )
        )

    async def list_operation_allocations(self, operation_id: UUID) -> list[PointAllocation]:
        return list(
            await self._session.scalars(
                select(PointAllocation)
                .where(PointAllocation.operation_id == operation_id)
                .order_by(PointAllocation.created_at, PointAllocation.id)
            )
        )

    async def list_source_lots(
        self,
        operation_id: UUID,
        *,
        for_update: bool,
    ) -> list[PointLot]:
        statement = (
            select(PointLot)
            .where(PointLot.source_operation_id == operation_id)
            .order_by(PointLot.earned_at, PointLot.id)
        )
        if for_update:
            statement = statement.with_for_update()
        return list(await self._session.scalars(statement))

    async def list_lot_lineage(
        self,
        root_lot_ids: list[UUID],
        *,
        for_update: bool,
    ) -> list[PointLot]:
        if not root_lot_ids:
            return []
        lineage = (
            select(PointLot.id.label("lot_id"))
            .where(PointLot.id.in_(root_lot_ids))
            .cte("point_lot_lineage", recursive=True)
        )
        lineage = lineage.union_all(
            select(PointLot.id).where(PointLot.transferred_from_lot_id == lineage.c.lot_id)
        )
        statement = (
            select(PointLot)
            .where(PointLot.id.in_(select(lineage.c.lot_id)))
            .order_by(PointLot.wallet_id, PointLot.earned_at, PointLot.id)
        )
        if for_update:
            statement = statement.with_for_update()
        return list(await self._session.scalars(statement))

    async def latest_route(self, source_lot_id: UUID) -> LotRouteDestination | None:
        """Resolve switch/merge chains to the terminal current wallet scope."""

        current_lot_id = source_lot_id
        visited: set[UUID] = set()
        terminal: LotRouteDestination | None = None
        for _ in range(64):
            if current_lot_id in visited:
                raise RuntimeError("Point lot routing cycle detected")
            visited.add(current_lot_id)
            direct = await self._latest_direct_route(current_lot_id)
            if direct is None:
                return terminal
            terminal = direct
            if direct.lot_id is None:
                return direct
            current_lot_id = direct.lot_id
        raise RuntimeError("Point lot routing chain exceeds the safety limit")

    async def _latest_direct_route(self, source_lot_id: UUID) -> LotRouteDestination | None:
        switch_row = (
            await self._session.execute(
                select(
                    PointLotRoute.destination_wallet_id,
                    PointLotRoute.destination_lot_id,
                    WalletModeSwitch.completed_at,
                )
                .join(WalletModeSwitch, WalletModeSwitch.id == PointLotRoute.switch_id)
                .where(PointLotRoute.source_lot_id == source_lot_id)
                .order_by(WalletModeSwitch.completed_at.desc(), PointLotRoute.id.desc())
                .limit(1)
            )
        ).one_or_none()
        merge_row = (
            await self._session.execute(
                select(
                    AccountMergeLotRoute.destination_wallet_id,
                    AccountMergeLotRoute.destination_lot_id,
                    AccountMergeLotRoute.created_at,
                )
                .where(AccountMergeLotRoute.source_lot_id == source_lot_id)
                .order_by(AccountMergeLotRoute.created_at.desc(), AccountMergeLotRoute.id.desc())
                .limit(1)
            )
        ).one_or_none()
        rows = [row for row in (switch_row, merge_row) if row is not None]
        if not rows:
            return None
        if (
            len(rows) == 2
            and rows[0][2] == rows[1][2]
            and (rows[0][0], rows[0][1]) != (rows[1][0], rows[1][1])
        ):
            # Old/eccentric writers could theoretically stamp a switch and a
            # merge route at the exact same instant.  Their real commit order
            # cannot be reconstructed, so choosing a table priority would send
            # future reversals to an arbitrary wallet.  New writers serialize
            # on settings and always choose a timestamp above the global floor.
            raise RuntimeError("Ambiguous equal-time point lot routes")
        row = max(rows, key=lambda item: item[2])
        return LotRouteDestination(wallet_id=row[0], lot_id=row[1], routed_at=row[2])

    async def list_routed_source_lot_ids(self) -> list[UUID]:
        source_ids = union(
            select(PointLotRoute.source_lot_id.label("source_lot_id")),
            select(AccountMergeLotRoute.source_lot_id.label("source_lot_id")),
        ).subquery()
        return list(
            await self._session.scalars(
                select(source_ids.c.source_lot_id).distinct().order_by(source_ids.c.source_lot_id)
            )
        )

    async def latest_route_timestamp(self) -> datetime | None:
        """Return the newest serialized route time across switches and merges."""

        switch_time = await self._session.scalar(
            select(func.max(WalletModeSwitch.completed_at))
            .select_from(PointLotRoute)
            .join(WalletModeSwitch, WalletModeSwitch.id == PointLotRoute.switch_id)
        )
        merge_time = await self._session.scalar(select(func.max(AccountMergeLotRoute.created_at)))
        values = [value for value in (switch_time, merge_time) if value is not None]
        return max(values) if values else None

    async def get_mode_switch_by_idempotency_key(
        self,
        key: str,
    ) -> WalletModeSwitch | None:
        return cast(
            WalletModeSwitch | None,
            await self._session.scalar(
                select(WalletModeSwitch).where(WalletModeSwitch.idempotency_key == key)
            ),
        )

    async def count_wallet_transfers(self, switch_id: UUID) -> int:
        return int(
            await self._session.scalar(
                select(func.count())
                .select_from(WalletTransfer)
                .where(WalletTransfer.switch_id == switch_id)
            )
            or 0
        )

    async def list_birthday_venues(self, settings_id: UUID) -> list[Venue]:
        return list(
            await self._session.scalars(
                select(Venue)
                .join(
                    BirthdayPromotionVenue,
                    BirthdayPromotionVenue.venue_id == Venue.id,
                )
                .where(BirthdayPromotionVenue.settings_id == settings_id)
                .order_by(Venue.sort_order, Venue.name, Venue.id)
            )
        )

    async def replace_birthday_venues(
        self,
        *,
        settings_id: UUID,
        venue_ids: list[UUID],
    ) -> None:
        await self._session.execute(
            delete(BirthdayPromotionVenue).where(BirthdayPromotionVenue.settings_id == settings_id)
        )
        self.add_all(
            [
                BirthdayPromotionVenue(
                    id=UUID(
                        bytes=hashlib.sha256(f"{settings_id}:{venue_id}".encode()).digest()[:16]
                    ),
                    settings_id=settings_id,
                    venue_id=venue_id,
                )
                for venue_id in sorted(set(venue_ids), key=lambda value: value.int)
            ]
        )

    async def due_expiry_lot_ids(self, *, now: datetime, limit: int) -> list[UUID]:
        """Bound the maintenance scan through the partial due index.

        This is intentionally a candidate read without locks.  Each candidate
        is rechecked after settings→user→wallet→lot locks in its own transaction;
        a deterministic operation key makes competing workers idempotent.
        """

        return list(
            await self._session.scalars(
                select(PointLot.id)
                .where(
                    PointLot.remaining_points > 0,
                    PointLot.expires_at.is_not(None),
                    PointLot.expires_at <= now,
                )
                .order_by(PointLot.expires_at, PointLot.wallet_id, PointLot.id)
                .limit(limit)
            )
        )

    async def due_reminder_lot_ids(
        self,
        *,
        starts_at: datetime,
        ends_at: datetime,
        limit: int,
    ) -> list[UUID]:
        return list(
            await self._session.scalars(
                select(PointLot.id)
                .where(
                    PointLot.remaining_points > 0,
                    PointLot.expires_at.is_not(None),
                    PointLot.expires_at > starts_at,
                    PointLot.expires_at <= ends_at,
                    PointLot.expiry_reminder_scheduled_at.is_(None),
                )
                .order_by(PointLot.expires_at, PointLot.wallet_id, PointLot.id)
                .limit(limit)
            )
        )

    async def lock_lot_owner(self, lot_id: UUID) -> LockedLotOwner | None:
        # Resolve identifiers first without locks, then acquire rows in the
        # documented global order.  Every value is rechecked under lock.
        identifiers = (
            await self._session.execute(
                select(LoyaltyWallet.user_id, LoyaltyWallet.id)
                .join(PointLot, PointLot.wallet_id == LoyaltyWallet.id)
                .where(PointLot.id == lot_id)
            )
        ).one_or_none()
        if identifiers is None:
            return None
        locked = await self.lock_user_state(identifiers[0])
        if locked is None:
            return None
        user, state = locked
        wallet = cast(
            LoyaltyWallet | None,
            await self._session.scalar(
                select(LoyaltyWallet)
                .where(
                    LoyaltyWallet.id == identifiers[1],
                    LoyaltyWallet.user_id == user.id,
                )
                .with_for_update()
            ),
        )
        if wallet is None:
            return None
        lot = cast(
            PointLot | None,
            await self._session.scalar(
                select(PointLot)
                .where(PointLot.id == lot_id, PointLot.wallet_id == wallet.id)
                .with_for_update()
            ),
        )
        if lot is None:
            return None
        return LockedLotOwner(user=user, state=state, wallet=wallet, lot=lot)

    async def has_verified_telegram_identity(self, user_id: UUID) -> bool:
        value = await self._session.scalar(
            select(CustomerIdentity.id)
            .where(
                CustomerIdentity.user_id == user_id,
                CustomerIdentity.provider == IdentityProvider.TELEGRAM,
                CustomerIdentity.is_verified.is_(True),
            )
            .limit(1)
        )
        return value is not None

    async def wallet_total(self, user_id: UUID) -> int:
        value = await self._session.scalar(
            select(func.coalesce(func.sum(LoyaltyWallet.balance_points), 0)).where(
                LoyaltyWallet.user_id == user_id
            )
        )
        return int(value or 0)

    async def lot_total(self, wallet_id: UUID) -> int:
        value = await self._session.scalar(
            select(func.coalesce(func.sum(PointLot.remaining_points), 0)).where(
                PointLot.wallet_id == wallet_id
            )
        )
        return int(value or 0)

    async def list_wallet_views(self, user_id: UUID) -> list[tuple[LoyaltyWallet, Venue | None]]:
        rows = (
            await self._session.execute(
                select(LoyaltyWallet, Venue)
                .outerjoin(Venue, Venue.id == LoyaltyWallet.venue_id)
                .where(LoyaltyWallet.user_id == user_id)
                .order_by(LoyaltyWallet.venue_id, LoyaltyWallet.id)
            )
        ).all()
        return [(row[0], row[1]) for row in rows]

    async def list_expiry_buckets(
        self, wallet_id: UUID, *, now: datetime
    ) -> list[tuple[datetime, int]]:
        return [
            (row[0], int(row[1]))
            for row in (
                await self._session.execute(
                    select(PointLot.expires_at, func.sum(PointLot.remaining_points))
                    .where(
                        PointLot.wallet_id == wallet_id,
                        PointLot.remaining_points > 0,
                        PointLot.expires_at.is_not(None),
                        PointLot.expires_at > now,
                    )
                    .group_by(PointLot.expires_at)
                    .order_by(PointLot.expires_at)
                )
            ).all()
            if row[0] is not None
        ]

    async def get_lot(self, lot_id: UUID, *, for_update: bool) -> PointLot | None:
        statement = select(PointLot).where(PointLot.id == lot_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(PointLot | None, await self._session.scalar(statement))

    def add(self, value: object) -> None:
        self._session.add(value)

    def add_all(self, values: list[object]) -> None:
        self._session.add_all(values)

    async def flush(self) -> None:
        await self._session.flush()
