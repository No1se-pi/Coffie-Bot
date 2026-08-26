"""Locked persistence context for conservative account merge transactions."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.access import Session, StaffMember, User
from app.models.cards import UserCard
from app.models.customers import CustomerIdentity, CustomerMerge
from app.models.enums import CardStatus
from app.models.loyalty import LoyaltySettings, Reward, UserLoyaltyState, Visit
from app.models.loyalty_v2 import LoyaltyWallet, PointLot
from app.models.staff import FeedbackItem
from app.repositories.loyalty_v2 import LotRouteDestination, PointLedgerRepository


@dataclass(frozen=True, slots=True)
class LockedMergeProfile:
    user: User
    staff: StaffMember | None
    loyalty_state: UserLoyaltyState | None
    identities: list[CustomerIdentity]
    latest_visit: Visit | None
    wallets: list[LoyaltyWallet]
    lots: list[PointLot]


@dataclass(frozen=True, slots=True)
class LockedMergeContext:
    settings: LoyaltySettings
    source: LockedMergeProfile
    canonical: LockedMergeProfile
    source_sessions: list[Session]
    source_cards: list[UserCard]
    canonical_card: UserCard | None
    source_rewards: list[Reward]
    source_feedback: list[FeedbackItem]
    source_route_lots: list[PointLot]
    terminal_routes: dict[UUID, LotRouteDestination | None]
    route_timestamp_floor: datetime | None


class CustomerMergeRepository:
    """SQLAlchemy adapter; CustomerMergeService owns the atomic boundary."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.point_ledger_repository = PointLedgerRepository(session)

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

    def add(self, value: object) -> None:
        self._session.add(value)

    def add_all(self, values: list[object]) -> None:
        self._session.add_all(values)

    async def flush(self) -> None:
        await self._session.flush()

    async def acquire_idempotency_lock(self, key: str) -> None:
        """Serialize the gap before a unique merge receipt exists."""

        digest = hashlib.sha256(f"customer-merge:{key}".encode()).digest()
        lock_id = int.from_bytes(digest[:8], byteorder="big", signed=True)
        await self._session.execute(select(func.pg_advisory_xact_lock(lock_id)))

    async def lock_settings_shared(self) -> LoyaltySettings:
        settings = await self.point_ledger_repository.get_settings(lock_mode="share")
        if settings is None:
            raise RuntimeError("Loyalty settings are not initialized")
        return settings

    async def get_by_idempotency_key(self, key: str) -> CustomerMerge | None:
        value: CustomerMerge | None = await self._session.scalar(
            select(CustomerMerge).where(CustomerMerge.idempotency_key == key)
        )
        return value

    async def lock_context(
        self,
        *,
        source_user_id: UUID,
        canonical_user_id: UUID,
    ) -> LockedMergeContext | None:
        """Lock both profiles and all mutable rows in a stable global order.

        Sorting UUIDs before ``FOR UPDATE`` prevents inverse merge requests
        (A→B and B→A) from acquiring user rows in opposite order.  Subsequent
        tables are always locked in the same sequence documented below.
        """

        settings = await self.lock_settings_shared()

        ordered_ids = sorted((source_user_id, canonical_user_id), key=lambda value: value.int)
        users = list(
            await self._session.scalars(
                select(User).where(User.id.in_(ordered_ids)).order_by(User.id).with_for_update()
            )
        )
        users_by_id = {item.id: item for item in users}
        if source_user_id not in users_by_id or canonical_user_id not in users_by_id:
            return None

        staff = list(
            await self._session.scalars(
                select(StaffMember)
                .where(StaffMember.user_id.in_(ordered_ids))
                .order_by(StaffMember.user_id, StaffMember.id)
                .with_for_update()
            )
        )
        staff_by_user_id = {item.user_id: item for item in staff}

        loyalty_states = list(
            await self._session.scalars(
                select(UserLoyaltyState)
                .where(UserLoyaltyState.user_id.in_(ordered_ids))
                .order_by(UserLoyaltyState.user_id, UserLoyaltyState.id)
                .with_for_update()
            )
        )
        states_by_user_id = {item.user_id: item for item in loyalty_states}

        # Point writers use the same settings -> users/state -> wallets -> lots
        # order.  Lock every owned lot (including fully spent history) so the
        # preview hash and the confirm mutation observe one stable aggregate.
        wallets = await self.point_ledger_repository.list_wallets_for_users(
            ordered_ids,
            for_update=True,
        )
        wallets_by_user_id: dict[UUID, list[LoyaltyWallet]] = {
            source_user_id: [],
            canonical_user_id: [],
        }
        for wallet in wallets:
            wallets_by_user_id[wallet.user_id].append(wallet)
        wallet_ids = [wallet.id for wallet in wallets]
        owned_lot_candidates = await self.point_ledger_repository.list_lots_for_wallets(
            wallet_ids,
            for_update=False,
        )
        owned_lot_ids = {lot.id for lot in owned_lot_candidates}
        source_wallet_ids = {wallet.id for wallet in wallets_by_user_id[source_user_id]}

        # A fully spent lot from an earlier A -> B merge has no destination lot,
        # only a terminal wallet route.  Carry that external historic source
        # forward when B is merged into C so a later reversal resolves C.
        external_source_lot_ids: set[UUID] = set()
        for lot_id in await self.point_ledger_repository.list_routed_source_lot_ids():
            if lot_id in owned_lot_ids:
                continue
            route = await self.point_ledger_repository.latest_route(lot_id)
            if route is not None and route.lot_id is None and route.wallet_id in source_wallet_ids:
                external_source_lot_ids.add(lot_id)

        locked_lots = await self.point_ledger_repository.lock_lots_by_ids(
            owned_lot_ids | external_source_lot_ids
        )
        lots_by_wallet_id: dict[UUID, list[PointLot]] = {wallet.id: [] for wallet in wallets}
        locked_by_id = {lot.id: lot for lot in locked_lots}
        for lot in locked_lots:
            if lot.wallet_id in lots_by_wallet_id:
                lots_by_wallet_id[lot.wallet_id].append(lot)
        source_owned_lots = [
            lot
            for wallet in wallets_by_user_id[source_user_id]
            for lot in lots_by_wallet_id[wallet.id]
        ]
        canonical_owned_lots = [
            lot
            for wallet in wallets_by_user_id[canonical_user_id]
            for lot in lots_by_wallet_id[wallet.id]
        ]
        source_route_lots = [
            *source_owned_lots,
            *[
                locked_by_id[lot_id]
                for lot_id in sorted(external_source_lot_ids, key=lambda value: value.int)
                if lot_id in locked_by_id
            ],
        ]
        terminal_routes = {
            lot.id: await self.point_ledger_repository.latest_route(lot.id)
            for lot in source_route_lots
        }

        identities = list(
            await self._session.scalars(
                select(CustomerIdentity)
                .where(CustomerIdentity.user_id.in_(ordered_ids))
                .order_by(
                    CustomerIdentity.user_id,
                    CustomerIdentity.provider,
                    CustomerIdentity.id,
                )
                .with_for_update()
            )
        )
        identities_by_user_id: dict[UUID, list[CustomerIdentity]] = {
            source_user_id: [],
            canonical_user_id: [],
        }
        for identity in identities:
            identities_by_user_id[identity.user_id].append(identity)

        # User/state locks above serialize the loyalty writers that can append a
        # visit. Visits themselves are immutable, so reading their newest row is
        # sufficient to choose the winning snapshot without rewriting history.
        visits = list(
            await self._session.scalars(
                select(Visit)
                .where(Visit.user_id.in_(ordered_ids))
                .distinct(Visit.user_id)
                .order_by(Visit.user_id, Visit.visited_at.desc(), Visit.id.desc())
            )
        )
        latest_visits: dict[UUID, Visit] = {}
        for visit in visits:
            latest_visits.setdefault(visit.user_id, visit)

        source_sessions = list(
            await self._session.scalars(
                select(Session)
                .where(
                    Session.user_id == source_user_id,
                    Session.revoked_at.is_(None),
                )
                .order_by(Session.id)
                .with_for_update()
            )
        )
        active_cards = list(
            await self._session.scalars(
                select(UserCard)
                .where(
                    UserCard.user_id.in_(ordered_ids),
                    UserCard.status == CardStatus.ACTIVE,
                )
                .order_by(UserCard.user_id, UserCard.id)
                .with_for_update()
            )
        )
        source_cards = [item for item in active_cards if item.user_id == source_user_id]
        canonical_cards = [item for item in active_cards if item.user_id == canonical_user_id]
        # PostgreSQL's partial unique index permits at most one active card per
        # user. Treat a violation as corrupted state instead of silently picking
        # one card and leaving merge behaviour nondeterministic.
        if len(canonical_cards) > 1:
            raise RuntimeError("Canonical customer has multiple active cards")
        source_rewards = list(
            await self._session.scalars(
                select(Reward)
                .where(Reward.user_id == source_user_id)
                .order_by(Reward.id)
                .with_for_update()
            )
        )
        source_feedback = list(
            await self._session.scalars(
                select(FeedbackItem)
                .where(FeedbackItem.user_id == source_user_id)
                .order_by(FeedbackItem.id)
                .with_for_update()
            )
        )

        return LockedMergeContext(
            settings=settings,
            source=LockedMergeProfile(
                user=users_by_id[source_user_id],
                staff=staff_by_user_id.get(source_user_id),
                loyalty_state=states_by_user_id.get(source_user_id),
                identities=identities_by_user_id[source_user_id],
                latest_visit=latest_visits.get(source_user_id),
                wallets=wallets_by_user_id[source_user_id],
                lots=source_owned_lots,
            ),
            canonical=LockedMergeProfile(
                user=users_by_id[canonical_user_id],
                staff=staff_by_user_id.get(canonical_user_id),
                loyalty_state=states_by_user_id.get(canonical_user_id),
                identities=identities_by_user_id[canonical_user_id],
                latest_visit=latest_visits.get(canonical_user_id),
                wallets=wallets_by_user_id[canonical_user_id],
                lots=canonical_owned_lots,
            ),
            source_sessions=source_sessions,
            source_cards=source_cards,
            canonical_card=canonical_cards[0] if canonical_cards else None,
            source_rewards=source_rewards,
            source_feedback=source_feedback,
            source_route_lots=source_route_lots,
            terminal_routes=terminal_routes,
            # Read after the user/wallet/lot locks. If an overlapping merge was
            # waiting ahead of us, READ COMMITTED now sees its committed routes.
            # The settings SHARE lock also excludes a concurrent mode switch.
            route_timestamp_floor=(await self.point_ledger_repository.latest_route_timestamp()),
        )
