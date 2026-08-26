"""Canonical wallet/lot writer used by every Loyalty V2 point mutation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from app.models.enums import (
    PointAllocationType,
    PointLotSourceType,
    WalletMode,
)
from app.models.loyalty import (
    LoyaltyOperation,
    LoyaltySettings,
    PointTransaction,
    UserLoyaltyState,
)
from app.models.loyalty_v2 import LoyaltyWallet, PointAllocation, PointLot
from app.repositories.loyalty_v2 import LotRouteDestination
from app.services.loyalty_calculations import LoyaltyRuleViolation
from app.services.loyalty_v2_calculations import calculate_point_expiry


class PointLedgerRepositoryPort(Protocol):
    async def get_wallet(
        self,
        *,
        user_id: UUID,
        venue_id: UUID | None,
        for_update: bool,
    ) -> LoyaltyWallet | None: ...

    async def get_wallet_by_id(
        self,
        *,
        user_id: UUID,
        wallet_id: UUID,
        for_update: bool,
    ) -> LoyaltyWallet | None: ...

    async def list_wallets(
        self,
        user_id: UUID,
        *,
        for_update: bool,
    ) -> list[LoyaltyWallet]: ...

    async def lock_wallets_by_ids(
        self,
        *,
        user_id: UUID,
        wallet_ids: set[UUID],
    ) -> list[LoyaltyWallet]: ...

    async def get_lot(self, lot_id: UUID, *, for_update: bool) -> PointLot | None: ...

    async def list_lots(
        self,
        wallet_id: UUID,
        *,
        for_update: bool,
        remaining_only: bool = False,
    ) -> list[PointLot]: ...

    async def list_source_lots(
        self,
        operation_id: UUID,
        *,
        for_update: bool,
    ) -> list[PointLot]: ...

    async def list_lot_lineage(
        self,
        root_lot_ids: list[UUID],
        *,
        for_update: bool,
    ) -> list[PointLot]: ...

    async def lock_lots_by_ids(self, lot_ids: set[UUID]) -> list[PointLot]: ...

    async def list_operation_allocations(self, operation_id: UUID) -> list[PointAllocation]: ...

    async def latest_route(self, source_lot_id: UUID) -> LotRouteDestination | None: ...

    async def wallet_total(self, user_id: UUID) -> int: ...

    async def lot_total(self, wallet_id: UUID) -> int: ...

    def add(self, value: object) -> None: ...

    def add_all(self, values: list[object]) -> None: ...

    async def flush(self) -> None: ...


@dataclass(frozen=True, slots=True)
class LedgerMutation:
    global_balance_before: int
    global_balance_after: int
    wallet_id: UUID | None
    wallet_balance_before: int | None
    wallet_balance_after: int | None
    points_changed: int
    lot_ids: tuple[UUID, ...]
    allocation_ids: tuple[UUID, ...]
    point_transaction: PointTransaction | None


@dataclass(frozen=True, slots=True)
class CreditComponent:
    """One independently explainable lot inside a single point operation."""

    points: int
    source_type: PointLotSourceType
    source_venue_id: UUID | None
    expires: bool = True


class PointLedger:
    """Apply one point change to wallet, lots, and the V1 total snapshot.

    The caller owns the surrounding transaction and must already hold settings
    and user/state locks.  This writer then locks/creates the target wallet and
    locks lots in strict ``earned_at, id`` order.  The legacy
    ``UserLoyaltyState.points_balance`` remains a total compatibility snapshot;
    every method updates it by exactly the same delta as the wallet set.
    """

    def __init__(self, repository: PointLedgerRepositoryPort) -> None:
        self._repository = repository

    async def credit(
        self,
        *,
        state: UserLoyaltyState,
        settings: LoyaltySettings,
        operation: LoyaltyOperation,
        points: int,
        source_type: PointLotSourceType,
        source_venue_id: UUID | None,
        now: datetime,
        expires: bool = True,
    ) -> LedgerMutation:
        return await self.credit_components(
            state=state,
            settings=settings,
            operation=operation,
            components=(
                CreditComponent(
                    points=points,
                    source_type=source_type,
                    source_venue_id=source_venue_id,
                    expires=expires,
                ),
            ),
            now=now,
        )

    async def credit_components(
        self,
        *,
        state: UserLoyaltyState,
        settings: LoyaltySettings,
        operation: LoyaltyOperation,
        components: tuple[CreditComponent, ...],
        now: datetime,
    ) -> LedgerMutation:
        """Mint multiple source-attributed lots with one V1 transaction receipt.

        A combined purchase is one public/idempotent operation, but its venue
        percentage and visit/stamp bonus remain separate lots so later expiry,
        transfer, merge, and reversal retain the true provenance.
        """

        nonzero = tuple(component for component in components if component.points > 0)
        if not nonzero or any(component.points < 0 for component in components):
            raise LoyaltyRuleViolation("invalid_credit", "Начисление должно быть положительным")
        scope_ids = {
            None if settings.wallet_mode is WalletMode.SHARED else item.source_venue_id
            for item in nonzero
        }
        if len(scope_ids) != 1:
            raise LoyaltyRuleViolation(
                "credit_components_cross_wallet",
                "Одна операция не может начислять баллы в разные кошельки",
            )
        wallet = await self._target_wallet(
            user_id=state.user_id,
            settings=settings,
            venue_id=nonzero[0].source_venue_id,
        )
        global_before = state.points_balance
        wallet_before = wallet.balance_points
        lots = [
            PointLot(
                id=uuid4(),
                wallet_id=wallet.id,
                source_operation_id=operation.id,
                source_venue_id=component.source_venue_id,
                transferred_from_lot_id=None,
                source_type=component.source_type,
                initial_points=component.points,
                remaining_points=component.points,
                earned_at=now,
                expires_at=(
                    calculate_point_expiry(
                        now,
                        validity_months=settings.points_expiry_months,
                        legacy_validity_days=settings.points_validity_days,
                    )
                    if component.expires
                    else None
                ),
            )
            for component in nonzero
        ]
        points = sum(component.points for component in nonzero)
        wallet.balance_points += points
        wallet.version += 1
        state.points_balance += points
        transaction = _point_transaction(
            operation=operation,
            user_id=state.user_id,
            delta=points,
            balance_before=global_before,
            balance_after=state.points_balance,
            now=now,
        )
        self._repository.add_all([*lots, transaction])
        return LedgerMutation(
            global_balance_before=global_before,
            global_balance_after=state.points_balance,
            wallet_id=wallet.id,
            wallet_balance_before=wallet_before,
            wallet_balance_after=wallet.balance_points,
            points_changed=points,
            lot_ids=tuple(lot.id for lot in lots),
            allocation_ids=(),
            point_transaction=transaction,
        )

    async def debit_fifo(
        self,
        *,
        state: UserLoyaltyState,
        settings: LoyaltySettings,
        operation: LoyaltyOperation,
        points: int,
        venue_id: UUID | None,
        now: datetime,
        allocation_type: PointAllocationType = PointAllocationType.SPEND,
    ) -> LedgerMutation:
        """Debit oldest acquired, currently unexpired lots in strict FIFO order."""

        if points <= 0:
            raise LoyaltyRuleViolation("invalid_debit", "Списание должно быть положительным")
        wallet = await self._target_wallet(
            user_id=state.user_id,
            settings=settings,
            venue_id=venue_id,
            create=False,
        )
        lots = await self._repository.list_lots(
            wallet.id,
            for_update=True,
            remaining_only=True,
        )
        eligible = [lot for lot in lots if lot.expires_at is None or lot.expires_at > now]
        available = sum(lot.remaining_points for lot in eligible)
        if available < points:
            raise LoyaltyRuleViolation("insufficient_points", "Недостаточно доступных баллов")

        global_before = state.points_balance
        wallet_before = wallet.balance_points
        remaining = points
        allocations: list[PointAllocation] = []
        for lot in eligible:
            if remaining == 0:
                break
            allocated = min(lot.remaining_points, remaining)
            lot.remaining_points -= allocated
            allocation = PointAllocation(
                id=uuid4(),
                operation_id=operation.id,
                lot_id=lot.id,
                allocation_type=allocation_type,
                points=allocated,
                created_at=now,
            )
            allocations.append(allocation)
            remaining -= allocated

        wallet.balance_points -= points
        wallet.version += 1
        state.points_balance -= points
        transaction = _point_transaction(
            operation=operation,
            user_id=state.user_id,
            delta=-points,
            balance_before=global_before,
            balance_after=state.points_balance,
            now=now,
        )
        self._repository.add_all([*allocations, transaction])
        return LedgerMutation(
            global_balance_before=global_before,
            global_balance_after=state.points_balance,
            wallet_id=wallet.id,
            wallet_balance_before=wallet_before,
            wallet_balance_after=wallet.balance_points,
            points_changed=-points,
            lot_ids=tuple(allocation.lot_id for allocation in allocations),
            allocation_ids=tuple(allocation.id for allocation in allocations),
            point_transaction=transaction,
        )

    async def expire_lot(
        self,
        *,
        state: UserLoyaltyState,
        wallet: LoyaltyWallet,
        lot: PointLot,
        operation: LoyaltyOperation,
        now: datetime,
    ) -> LedgerMutation:
        if lot.wallet_id != wallet.id or wallet.user_id != state.user_id:
            raise RuntimeError("Locked expiry rows do not belong to one aggregate")
        points = lot.remaining_points
        if points <= 0 or lot.expires_at is None or lot.expires_at > now:
            raise LoyaltyRuleViolation("lot_not_due", "Партия баллов ещё не подлежит сгоранию")
        global_before = state.points_balance
        wallet_before = wallet.balance_points
        lot.remaining_points = 0
        lot.expired_at = now
        wallet.balance_points -= points
        wallet.version += 1
        state.points_balance -= points
        allocation = PointAllocation(
            id=uuid4(),
            operation_id=operation.id,
            lot_id=lot.id,
            allocation_type=PointAllocationType.EXPIRY,
            points=points,
            created_at=now,
        )
        transaction = _point_transaction(
            operation=operation,
            user_id=state.user_id,
            delta=-points,
            balance_before=global_before,
            balance_after=state.points_balance,
            now=now,
        )
        self._repository.add_all([allocation, transaction])
        return LedgerMutation(
            global_balance_before=global_before,
            global_balance_after=state.points_balance,
            wallet_id=wallet.id,
            wallet_balance_before=wallet_before,
            wallet_balance_after=wallet.balance_points,
            points_changed=-points,
            lot_ids=(lot.id,),
            allocation_ids=(allocation.id,),
            point_transaction=transaction,
        )

    async def reverse_spend(
        self,
        *,
        state: UserLoyaltyState,
        settings: LoyaltySettings,
        original_operation_id: UUID,
        reversal: LoyaltyOperation,
        now: datetime,
    ) -> LedgerMutation:
        """Restore exact spend allocations into the current routed scope.

        Each restored amount is a new linked lot with the original acquisition
        timestamp, expiry, and venue.  This avoids exceeding a transferred
        destination lot's ``initial_points`` and prevents a mode switch from
        silently resurrecting an inactive wallet.  If any original allocation
        is already expired, the whole reversal is rejected atomically.
        """

        originals = [
            allocation
            for allocation in await self._repository.list_operation_allocations(
                original_operation_id
            )
            if allocation.allocation_type is PointAllocationType.SPEND
        ]
        if not originals:
            raise LoyaltyRuleViolation(
                "reversal_allocations_missing",
                "Для списания не найдены исходные распределения",
            )
        original_lots: dict[UUID, PointLot] = {}
        destinations: dict[UUID, UUID] = {}
        for original_allocation in originals:
            original_lot = await self._repository.get_lot(
                original_allocation.lot_id,
                for_update=False,
            )
            if original_lot is None:
                raise RuntimeError("Point allocation references a missing lot")
            # A conservative reversal is atomic: if any allocated portion has
            # reached its original deadline, reject the whole action instead of
            # reporting a misleading partial inverse delta.
            if original_lot.expires_at is not None and original_lot.expires_at <= now:
                raise LoyaltyRuleViolation(
                    "reversal_points_expired",
                    "Срок действия части возвращаемых баллов уже истёк",
                )
            original_lots[original_lot.id] = original_lot
            route = await self._repository.latest_route(original_lot.id)
            destinations[original_lot.id] = (
                route.wallet_id if route is not None else original_lot.wallet_id
            )
        locked_wallets = {
            wallet.id: wallet
            for wallet in await self._repository.lock_wallets_by_ids(
                user_id=state.user_id,
                wallet_ids=set(destinations.values()),
            )
        }
        if set(locked_wallets) != set(destinations.values()):
            raise RuntimeError("A routed reversal wallet is missing or belongs to another user")

        global_before = state.points_balance
        restored = 0
        new_lots: list[PointLot] = []
        allocations: list[PointAllocation] = []
        touched_wallets: dict[UUID, LoyaltyWallet] = {}

        for original_allocation in originals:
            original_lot = original_lots[original_allocation.lot_id]
            target_wallet = locked_wallets[destinations[original_lot.id]]
            touched_wallets[target_wallet.id] = target_wallet
            lot = PointLot(
                id=uuid4(),
                wallet_id=target_wallet.id,
                source_operation_id=reversal.id,
                source_venue_id=original_lot.source_venue_id,
                transferred_from_lot_id=original_lot.id,
                source_type=PointLotSourceType.REVERSAL,
                initial_points=original_allocation.points,
                remaining_points=original_allocation.points,
                earned_at=original_lot.earned_at,
                expires_at=original_lot.expires_at,
            )
            allocation = PointAllocation(
                id=uuid4(),
                operation_id=reversal.id,
                lot_id=lot.id,
                allocation_type=PointAllocationType.REVERSAL_RESTORE,
                points=original_allocation.points,
                reverses_allocation_id=original_allocation.id,
                created_at=now,
            )
            target_wallet.balance_points += original_allocation.points
            restored += original_allocation.points
            new_lots.append(lot)
            allocations.append(allocation)

        # Version is a wallet mutation counter, not an allocation counter.
        # Several restored FIFO fragments in one reversal still constitute one
        # atomic change per affected wallet.
        for wallet in touched_wallets.values():
            wallet.version += 1

        if restored <= 0:
            raise RuntimeError("A spend reversal unexpectedly restored zero points")
        state.points_balance += restored
        transaction = _point_transaction(
            operation=reversal,
            user_id=state.user_id,
            delta=restored,
            balance_before=global_before,
            balance_after=state.points_balance,
            now=now,
        )
        # Allocations point at freshly minted reversal lots through scalar FK
        # ids.  Flush lots first; without ORM relationships SQLAlchemy may emit
        # the allocation insert before its referenced lot on PostgreSQL.
        self._repository.add_all([*new_lots])
        await self._repository.flush()
        self._repository.add_all([*allocations, transaction])
        return LedgerMutation(
            global_balance_before=global_before,
            global_balance_after=state.points_balance,
            wallet_id=(next(iter(touched_wallets)) if len(touched_wallets) == 1 else None),
            wallet_balance_before=None,
            wallet_balance_after=None,
            points_changed=restored,
            lot_ids=tuple(lot.id for lot in new_lots),
            allocation_ids=tuple(item.id for item in allocations),
            point_transaction=transaction,
        )

    async def reverse_credit(
        self,
        *,
        state: UserLoyaltyState,
        original_operation_id: UUID,
        reversal: LoyaltyOperation,
        points: int,
        now: datetime,
    ) -> LedgerMutation:
        """Debit only the still-available lots minted by the original credit."""

        sources = await self._repository.list_source_lots(
            original_operation_id,
            for_update=False,
        )
        if not sources:
            raise LoyaltyRuleViolation(
                "reversal_lot_missing", "Для начисления не найдена исходная партия"
            )
        lineage = await self._repository.list_lot_lineage(
            [source.id for source in sources],
            for_update=False,
        )
        active_candidates = [lot for lot in lineage if lot.remaining_points > 0]
        locked_wallets = {
            wallet.id: wallet
            for wallet in await self._repository.lock_wallets_by_ids(
                user_id=state.user_id,
                wallet_ids={lot.wallet_id for lot in active_candidates},
            )
        }
        locked_lots = await self._repository.lock_lots_by_ids({lot.id for lot in active_candidates})
        resolved = [
            (lot, locked_wallets[lot.wallet_id])
            for lot in locked_lots
            if lot.wallet_id in locked_wallets
        ]

        available = sum(
            lot.remaining_points
            for lot, _wallet in resolved
            if lot.expires_at is None or lot.expires_at > now
        )
        if available < points:
            raise LoyaltyRuleViolation(
                "reversal_points_unavailable",
                "Начисленные баллы уже потрачены или истекли; требуется ручной разбор",
            )
        global_before = state.points_balance
        remaining = points
        allocations: list[PointAllocation] = []
        touched_wallets: dict[UUID, LoyaltyWallet] = {}
        for lot, wallet in resolved:
            if remaining == 0:
                break
            if lot.expires_at is not None and lot.expires_at <= now:
                continue
            amount = min(lot.remaining_points, remaining)
            lot.remaining_points -= amount
            wallet.balance_points -= amount
            touched_wallets[wallet.id] = wallet
            allocations.append(
                PointAllocation(
                    id=uuid4(),
                    operation_id=reversal.id,
                    lot_id=lot.id,
                    allocation_type=PointAllocationType.REVERSAL_DEBIT,
                    points=amount,
                    created_at=now,
                )
            )
            remaining -= amount
        for wallet in touched_wallets.values():
            wallet.version += 1
        state.points_balance -= points
        transaction = _point_transaction(
            operation=reversal,
            user_id=state.user_id,
            delta=-points,
            balance_before=global_before,
            balance_after=state.points_balance,
            now=now,
        )
        self._repository.add_all([*allocations, transaction])
        return LedgerMutation(
            global_balance_before=global_before,
            global_balance_after=state.points_balance,
            wallet_id=None,
            wallet_balance_before=None,
            wallet_balance_after=None,
            points_changed=-points,
            lot_ids=tuple(item.lot_id for item in allocations),
            allocation_ids=tuple(item.id for item in allocations),
            point_transaction=transaction,
        )

    async def assert_invariants(self, state: UserLoyaltyState) -> None:
        """Fail the transaction if a V1 snapshot, wallet, or lot sum drifts."""

        await self._repository.flush()
        wallet_total = await self._repository.wallet_total(state.user_id)
        if wallet_total != state.points_balance:
            raise RuntimeError(
                f"wallet total {wallet_total} != loyalty snapshot {state.points_balance}"
            )
        # Locking and checking every wallet is intentionally done after the
        # mutation while the user's state lock still serializes other writers.
        # The repository has no broad cross-user scan in this hot path.
        for wallet in await self._repository.list_wallets(state.user_id, for_update=False):
            if await self._repository.lot_total(wallet.id) != wallet.balance_points:
                raise RuntimeError("wallet balance does not equal remaining lot total")

    async def _target_wallet(
        self,
        *,
        user_id: UUID,
        settings: LoyaltySettings,
        venue_id: UUID | None,
        create: bool = True,
    ) -> LoyaltyWallet:
        scope_venue_id = None if settings.wallet_mode is WalletMode.SHARED else venue_id
        if settings.wallet_mode is WalletMode.SEPARATE and scope_venue_id is None:
            raise LoyaltyRuleViolation(
                "venue_required_for_separate_wallet",
                "Для операции в раздельном режиме требуется заведение",
            )
        wallet = await self._repository.get_wallet(
            user_id=user_id,
            venue_id=scope_venue_id,
            for_update=True,
        )
        if wallet is not None:
            return wallet
        if not create:
            raise LoyaltyRuleViolation("insufficient_points", "Кошелёк не содержит баллов")
        wallet = LoyaltyWallet(
            id=uuid4(),
            user_id=user_id,
            venue_id=scope_venue_id,
            balance_points=0,
            version=1,
        )
        self._repository.add(wallet)
        await self._repository.flush()
        return wallet


def _point_transaction(
    *,
    operation: LoyaltyOperation,
    user_id: UUID,
    delta: int,
    balance_before: int,
    balance_after: int,
    now: datetime,
) -> PointTransaction:
    return PointTransaction(
        id=uuid4(),
        operation_id=operation.id,
        user_id=user_id,
        delta=delta,
        balance_before=balance_before,
        balance_after=balance_after,
        purchase_amount_minor=operation.purchase_amount_minor,
        created_at=now,
    )
