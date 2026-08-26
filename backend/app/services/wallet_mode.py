"""Owner-confirmed, immutable migration between shared and separate wallets."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, NoReturn, Protocol
from uuid import UUID, uuid4

from fastapi import status

from app.core.errors import AppError, ErrorCode
from app.models.access import User
from app.models.audit import AuditEvent
from app.models.content import Venue
from app.models.enums import (
    AuditSeverity,
    LoyaltyOperationType,
    OperationStatus,
    PermissionCode,
    PointAllocationType,
    PointLotSourceType,
    WalletMode,
)
from app.models.loyalty import LoyaltyOperation, LoyaltySettings, UserLoyaltyState
from app.models.loyalty_v2 import (
    LoyaltyWallet,
    PointAllocation,
    PointLot,
    PointLotRoute,
    WalletModeSwitch,
    WalletTransfer,
)
from app.repositories.loyalty_v2 import LotRouteDestination
from app.security.rbac import Actor
from app.services.loyalty_v2 import VenueSummary
from app.services.point_ledger import PointLedger, PointLedgerRepositoryPort


class WalletModeRepositoryPort(PointLedgerRepositoryPort, Protocol):
    def transaction(self) -> AbstractAsyncContextManager[None]: ...

    async def acquire_idempotency_lock(self, namespace: str, key: str) -> None: ...

    async def get_settings(
        self,
        *,
        lock_mode: Literal["none", "share", "update"] = "none",
    ) -> LoyaltySettings | None: ...

    async def list_venues(self, *, for_update: bool = False) -> list[Venue]: ...

    async def list_users_states(
        self,
        *,
        for_update: bool,
    ) -> list[tuple[User, UserLoyaltyState]]: ...

    async def list_all_wallets(self, *, for_update: bool) -> list[LoyaltyWallet]: ...

    async def list_all_lots(self, *, for_update: bool) -> list[PointLot]: ...

    async def list_routed_source_lot_ids(self) -> list[UUID]: ...

    async def latest_route(self, source_lot_id: UUID) -> LotRouteDestination | None: ...

    async def latest_route_timestamp(self) -> datetime | None: ...

    async def get_mode_switch_by_idempotency_key(
        self,
        key: str,
    ) -> WalletModeSwitch | None: ...

    async def count_wallet_transfers(self, switch_id: UUID) -> int: ...


@dataclass(frozen=True, slots=True)
class WalletModePreview:
    current_mode: WalletMode
    target_mode: WalletMode
    preview_hash: str
    customers_affected: int
    wallets_affected: int
    total_balance_points: int
    transfer_operations: int
    fallback_required: bool
    fallback_venue_id: UUID | None
    unresolved_points: int
    eligible_fallback_venues: tuple[VenueSummary, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WalletModeChangeResult:
    wallet_mode: WalletMode
    wallets_created: int
    transfer_operations: int
    total_balance_points: int
    completed_at: datetime
    idempotent_replay: bool


@dataclass(frozen=True, slots=True)
class _LotMove:
    source: PointLot
    source_wallet_id: UUID
    user_id: UUID
    destination_venue_id: UUID | None
    physically_current: bool
    unresolved: bool


@dataclass(frozen=True, slots=True)
class _ModePlan:
    preview: WalletModePreview
    users_states: tuple[tuple[User, UserLoyaltyState], ...]
    wallets: tuple[LoyaltyWallet, ...]
    lots: tuple[PointLot, ...]
    moves: tuple[_LotMove, ...]


class WalletModeService:
    """Preview and confirm the one supported global wallet-mode transition."""

    def __init__(self, repository: WalletModeRepositoryPort) -> None:
        self._repository = repository
        self._ledger = PointLedger(repository)

    async def preview(
        self,
        actor: Actor,
        *,
        target_mode: WalletMode,
        fallback_venue_id: UUID | None,
    ) -> WalletModePreview:
        _require_owner(actor)
        settings = await self._required_settings(lock_mode="none")
        venues = await self._repository.list_venues()
        users_states = await self._repository.list_users_states(for_update=False)
        wallets = await self._repository.list_all_wallets(for_update=False)
        lots = await self._repository.list_all_lots(for_update=False)
        return (
            await self._build_plan(
                settings=settings,
                target_mode=target_mode,
                fallback_venue_id=fallback_venue_id,
                venues=venues,
                users_states=users_states,
                wallets=wallets,
                lots=lots,
            )
        ).preview

    async def confirm(
        self,
        actor: Actor,
        *,
        target_mode: WalletMode,
        fallback_venue_id: UUID | None,
        preview_hash: str,
        reason: str,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> WalletModeChangeResult:
        _require_owner(actor)
        if actor.staff_member_id is None:
            _forbidden()
        normalized_reason = " ".join(reason.split())
        if len(normalized_reason) < 3:
            _validation("reason_required", "A visible wallet-mode change reason is required")
        current_time = _aware_now(now)
        request_hash = _request_hash(
            actor=actor,
            target_mode=target_mode,
            fallback_venue_id=fallback_venue_id,
            preview_hash=preview_hash,
            reason=normalized_reason,
        )
        async with self._repository.transaction():
            await self._repository.acquire_idempotency_lock("wallet-mode", idempotency_key)
            replay = await self._repository.get_mode_switch_by_idempotency_key(idempotency_key)
            if replay is not None:
                if replay.request_hash != request_hash:
                    _conflict(
                        "idempotency_key_reused",
                        "Idempotency-Key was already used with another request",
                    )
                return WalletModeChangeResult(
                    wallet_mode=replay.to_mode,
                    wallets_created=replay.wallets_moved,
                    transfer_operations=await self._repository.count_wallet_transfers(replay.id),
                    total_balance_points=replay.total_points_after,
                    completed_at=replay.completed_at,
                    idempotent_replay=True,
                )
            settings = await self._required_settings(lock_mode="update")
            venues = await self._repository.list_venues(for_update=True)
            users_states = await self._repository.list_users_states(for_update=True)
            wallets = await self._repository.list_all_wallets(for_update=True)
            lots = await self._repository.list_all_lots(for_update=True)
            plan = await self._build_plan(
                settings=settings,
                target_mode=target_mode,
                fallback_venue_id=fallback_venue_id,
                venues=venues,
                users_states=users_states,
                wallets=wallets,
                lots=lots,
            )
            if plan.preview.preview_hash != preview_hash:
                _conflict("wallet_mode_preview_stale", "Wallet-mode preview is stale")
            if plan.preview.fallback_required and fallback_venue_id is None:
                _validation(
                    "fallback_venue_required",
                    "An active fallback venue is required for unattributed lots",
                )
            result = await self._apply_plan(
                actor=actor,
                settings=settings,
                plan=plan,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                reason=normalized_reason,
                now=current_time,
            )
            return result

    async def _build_plan(
        self,
        *,
        settings: LoyaltySettings,
        target_mode: WalletMode,
        fallback_venue_id: UUID | None,
        venues: list[Venue],
        users_states: list[tuple[User, UserLoyaltyState]],
        wallets: list[LoyaltyWallet],
        lots: list[PointLot],
    ) -> _ModePlan:
        if target_mode is settings.wallet_mode:
            _conflict("wallet_mode_unchanged", "Requested wallet mode is already active")
        available_venues = {venue.id: venue for venue in venues if _venue_available(venue)}
        if fallback_venue_id is not None and fallback_venue_id not in available_venues:
            _validation("fallback_venue_unavailable", "Fallback venue must be active")
        if target_mode is WalletMode.SHARED and fallback_venue_id is not None:
            _validation(
                "fallback_venue_not_applicable", "Shared mode does not use a fallback venue"
            )

        states = {state.user_id: state for _user, state in users_states}
        wallets_by_id = {wallet.id: wallet for wallet in wallets}
        lots_by_id = {lot.id: lot for lot in lots}
        for wallet in wallets:
            if wallet.user_id not in states:
                raise RuntimeError("loyalty wallet has no user state")
        for lot in lots:
            if lot.wallet_id not in wallets_by_id:
                raise RuntimeError("point lot has no wallet")
        wallet_totals: dict[UUID, int] = defaultdict(int)
        for lot in lots:
            wallet_totals[lot.wallet_id] += lot.remaining_points
        if any(wallet_totals[wallet.id] != wallet.balance_points for wallet in wallets):
            raise RuntimeError("wallet balance does not equal remaining lot total")
        totals_by_user: dict[UUID, int] = defaultdict(int)
        for wallet in wallets:
            totals_by_user[wallet.user_id] += wallet.balance_points
        if any(
            totals_by_user[user_id] != state.points_balance for user_id, state in states.items()
        ):
            raise RuntimeError("wallet total does not equal loyalty compatibility snapshot")

        current_wallets = {
            wallet.id: wallet
            for wallet in wallets
            if (settings.wallet_mode is WalletMode.SHARED and wallet.venue_id is None)
            or (settings.wallet_mode is WalletMode.SEPARATE and wallet.venue_id is not None)
        }
        inactive = [wallet for wallet in wallets if wallet.id not in current_wallets]
        if any(wallet.balance_points != 0 for wallet in inactive):
            raise RuntimeError("inactive wallet scope has a non-zero balance")

        moves: list[_LotMove] = []
        physical_ids: set[UUID] = set()
        route_snapshot: list[dict[str, object]] = []
        for lot in lots:
            current_wallet = current_wallets.get(lot.wallet_id)
            if current_wallet is None:
                continue
            physical_ids.add(lot.id)
            destination, unresolved = _destination_venue(
                lot,
                target_mode=target_mode,
                available_venues=available_venues,
                fallback_venue_id=fallback_venue_id,
            )
            moves.append(
                _LotMove(
                    source=lot,
                    source_wallet_id=current_wallet.id,
                    user_id=current_wallet.user_id,
                    destination_venue_id=destination,
                    physically_current=True,
                    unresolved=unresolved,
                )
            )
        for source_id in await self._repository.list_routed_source_lot_ids():
            route = await self._repository.latest_route(source_id)
            if route is None:
                continue
            route_snapshot.append(
                {
                    "source_lot_id": str(source_id),
                    "wallet_id": str(route.wallet_id),
                    "lot_id": str(route.lot_id) if route.lot_id is not None else None,
                    "routed_at": route.routed_at.isoformat(),
                }
            )
            if source_id in physical_ids or route.lot_id is not None:
                continue
            current_wallet = current_wallets.get(route.wallet_id)
            source = lots_by_id.get(source_id)
            if current_wallet is None or source is None:
                continue
            destination, unresolved = _destination_venue(
                source,
                target_mode=target_mode,
                available_venues=available_venues,
                fallback_venue_id=fallback_venue_id,
            )
            moves.append(
                _LotMove(
                    source=source,
                    source_wallet_id=current_wallet.id,
                    user_id=current_wallet.user_id,
                    destination_venue_id=destination,
                    physically_current=False,
                    unresolved=unresolved,
                )
            )

        affected_users = {move.user_id for move in moves}
        affected_wallets = {move.source_wallet_id for move in moves}
        transfer_groups = {
            (move.user_id, move.source_wallet_id, move.destination_venue_id)
            for move in moves
            if move.physically_current and move.source.remaining_points > 0
        }
        fallback_required = any(move.unresolved for move in moves)
        unresolved_points = sum(
            move.source.remaining_points
            for move in moves
            if move.unresolved and move.physically_current
        )
        total_balance = sum(state.points_balance for state in states.values())
        hash_payload = {
            "current_mode": settings.wallet_mode.value,
            "target_mode": target_mode.value,
            "fallback_venue_id": str(fallback_venue_id) if fallback_venue_id else None,
            "venues": [
                {
                    "id": str(venue.id),
                    "active": venue.is_active,
                    "archived_at": _iso(venue.archived_at),
                }
                for venue in sorted(venues, key=lambda item: item.id.int)
            ],
            "states": [
                {
                    "user_id": str(state.user_id),
                    "balance": state.points_balance,
                    "version": state.version,
                    "status": user.status.value,
                }
                for user, state in users_states
            ],
            "wallets": [
                {
                    "id": str(wallet.id),
                    "user_id": str(wallet.user_id),
                    "venue_id": str(wallet.venue_id) if wallet.venue_id else None,
                    "balance": wallet.balance_points,
                    "version": wallet.version,
                }
                for wallet in wallets
            ],
            "lots": [
                {
                    "id": str(lot.id),
                    "wallet_id": str(lot.wallet_id),
                    "origin": str(lot.source_venue_id) if lot.source_venue_id else None,
                    "remaining": lot.remaining_points,
                    "earned_at": lot.earned_at.isoformat(),
                    "expires_at": _iso(lot.expires_at),
                    "reminded_at": _iso(lot.expiry_reminder_scheduled_at),
                }
                for lot in lots
            ],
            "routes": route_snapshot,
        }
        preview_hash = hashlib.sha256(
            json.dumps(hash_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        warnings = [
            "Балансы будут перенесены неизменяемыми transfer-операциями.",
            "Суммарный баланс клиентов не изменится.",
        ]
        if fallback_required:
            warnings.append("Партии без активного источника требуют fallback-заведение.")
        preview = WalletModePreview(
            current_mode=settings.wallet_mode,
            target_mode=target_mode,
            preview_hash=preview_hash,
            customers_affected=len(affected_users),
            wallets_affected=len(affected_wallets),
            total_balance_points=total_balance,
            transfer_operations=len(transfer_groups),
            fallback_required=fallback_required,
            fallback_venue_id=fallback_venue_id,
            unresolved_points=unresolved_points,
            eligible_fallback_venues=tuple(
                VenueSummary(id=venue.id, name=venue.name, available=True)
                for venue in sorted(
                    available_venues.values(),
                    key=lambda item: (item.sort_order, item.name, item.id),
                )
            ),
            warnings=tuple(warnings),
        )
        return _ModePlan(
            preview=preview,
            users_states=tuple(users_states),
            wallets=tuple(wallets),
            lots=tuple(lots),
            moves=tuple(moves),
        )

    async def _apply_plan(
        self,
        *,
        actor: Actor,
        settings: LoyaltySettings,
        plan: _ModePlan,
        idempotency_key: str,
        request_hash: str,
        reason: str,
        now: datetime,
    ) -> WalletModeChangeResult:
        staff_id = actor.staff_member_id
        if staff_id is None:
            _forbidden()
        latest_route_time = await self._repository.latest_route_timestamp()
        if latest_route_time is not None and now <= latest_route_time:
            # Settings UPDATE serializes mode switches against merge's settings
            # SHARE lock.  A monotonic timestamp then makes latest_route stable
            # even when callers captured identical or backwards wall clocks.
            now = latest_route_time + timedelta(microseconds=1)
        switch = WalletModeSwitch(
            id=uuid4(),
            actor_user_id=actor.user_id,
            actor_staff_id=staff_id,
            from_mode=settings.wallet_mode,
            to_mode=plan.preview.target_mode,
            fallback_venue_id=plan.preview.fallback_venue_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            preview_hash=plan.preview.preview_hash,
            reason=reason,
            total_points_before=plan.preview.total_balance_points,
            total_points_after=plan.preview.total_balance_points,
            wallets_moved=0,
            lots_moved=len(plan.moves),
            created_at=now,
            completed_at=now,
        )
        self._repository.add(switch)

        wallets = {(wallet.user_id, wallet.venue_id): wallet for wallet in plan.wallets}
        wallets_by_id = {wallet.id: wallet for wallet in plan.wallets}
        created = 0
        for move in plan.moves:
            key = (move.user_id, move.destination_venue_id)
            if key not in wallets:
                wallet = LoyaltyWallet(
                    id=uuid4(),
                    user_id=move.user_id,
                    venue_id=move.destination_venue_id,
                    balance_points=0,
                    version=1,
                )
                wallets[key] = wallet
                wallets_by_id[wallet.id] = wallet
                self._repository.add(wallet)
                created += 1
        switch.wallets_moved = created
        await self._repository.flush()

        groups: dict[tuple[UUID, UUID, UUID], list[_LotMove]] = defaultdict(list)
        for move in plan.moves:
            if move.physically_current and move.source.remaining_points > 0:
                destination = wallets[(move.user_id, move.destination_venue_id)]
                groups[(move.user_id, move.source_wallet_id, destination.id)].append(move)

        operations: dict[tuple[UUID, UUID, UUID], tuple[LoyaltyOperation, LoyaltyOperation]] = {}
        states = {state.user_id: state for _user, state in plan.users_states}
        for ordinal, (group_key, _moves) in enumerate(
            sorted(groups.items(), key=lambda item: tuple(value.int for value in item[0])),
            start=1,
        ):
            user_id, _source_wallet_id, _destination_wallet_id = group_key
            state = states[user_id]
            debit = _transfer_operation(
                user_id=user_id,
                switch_id=switch.id,
                ordinal=ordinal,
                side="debit",
                operation_type=LoyaltyOperationType.WALLET_TRANSFER_DEBIT,
                balance=state.points_balance,
                reason=reason,
                now=now,
            )
            credit = _transfer_operation(
                user_id=user_id,
                switch_id=switch.id,
                ordinal=ordinal,
                side="credit",
                operation_type=LoyaltyOperationType.WALLET_TRANSFER_CREDIT,
                balance=state.points_balance,
                reason=reason,
                now=now,
            )
            operations[group_key] = (debit, credit)
            self._repository.add_all([debit, credit])
        await self._repository.flush()

        source_debits: dict[UUID, int] = defaultdict(int)
        destination_credits: dict[UUID, int] = defaultdict(int)
        touched_users: set[UUID] = set()
        transfer_count = 0
        for group_key, moves in groups.items():
            user_id, source_wallet_id, destination_wallet_id = group_key
            debit, credit = operations[group_key]
            points = sum(move.source.remaining_points for move in moves)
            source_debits[source_wallet_id] += points
            destination_credits[destination_wallet_id] += points
            touched_users.add(user_id)
            transfer_count += 1
            self._repository.add(
                WalletTransfer(
                    id=uuid4(),
                    switch_id=switch.id,
                    user_id=user_id,
                    source_wallet_id=source_wallet_id,
                    destination_wallet_id=destination_wallet_id,
                    debit_operation_id=debit.id,
                    credit_operation_id=credit.id,
                    points=points,
                    created_at=now,
                )
            )
            for move in moves:
                amount = move.source.remaining_points
                destination_lot = PointLot(
                    id=uuid4(),
                    wallet_id=destination_wallet_id,
                    source_operation_id=credit.id,
                    source_venue_id=move.source.source_venue_id,
                    transferred_from_lot_id=move.source.id,
                    source_type=PointLotSourceType.WALLET_TRANSFER,
                    initial_points=amount,
                    remaining_points=amount,
                    earned_at=move.source.earned_at,
                    expires_at=move.source.expires_at,
                    expiry_reminder_scheduled_at=move.source.expiry_reminder_scheduled_at,
                )
                self._repository.add_all(
                    [
                        PointAllocation(
                            id=uuid4(),
                            operation_id=debit.id,
                            lot_id=move.source.id,
                            allocation_type=PointAllocationType.WALLET_TRANSFER_DEBIT,
                            points=amount,
                            created_at=now,
                        ),
                        destination_lot,
                        PointLotRoute(
                            id=uuid4(),
                            switch_id=switch.id,
                            source_lot_id=move.source.id,
                            destination_wallet_id=destination_wallet_id,
                            destination_lot_id=destination_lot.id,
                            created_at=now,
                        ),
                    ]
                )
                move.source.remaining_points = 0

        routed_positive = {move.source.id for moves in groups.values() for move in moves}
        for move in plan.moves:
            if move.source.id in routed_positive:
                continue
            destination = wallets[(move.user_id, move.destination_venue_id)]
            self._repository.add(
                PointLotRoute(
                    id=uuid4(),
                    switch_id=switch.id,
                    source_lot_id=move.source.id,
                    destination_wallet_id=destination.id,
                    destination_lot_id=None,
                    created_at=now,
                )
            )
            touched_users.add(move.user_id)

        for wallet_id, points in source_debits.items():
            wallet = wallets_by_id[wallet_id]
            wallet.balance_points -= points
            wallet.version += 1
        for wallet_id, points in destination_credits.items():
            wallet = wallets_by_id[wallet_id]
            wallet.balance_points += points
            wallet.version += 1
        for user_id in touched_users:
            states[user_id].version += 1

        settings.wallet_mode = plan.preview.target_mode
        settings.updated_by_staff_id = staff_id
        settings.updated_at = now
        self._repository.add(
            AuditEvent(
                id=uuid4(),
                event_type="loyalty.wallet_mode_changed",
                actor_user_id=actor.user_id,
                actor_staff_id=staff_id,
                object_type="wallet_mode_switch",
                object_id=switch.id,
                idempotency_key=f"wallet-mode-audit:{switch.id}",
                event_metadata={
                    "from_mode": switch.from_mode.value,
                    "to_mode": switch.to_mode.value,
                    "preview_hash": switch.preview_hash,
                    "fallback_venue_id": (
                        str(switch.fallback_venue_id) if switch.fallback_venue_id else None
                    ),
                    "customers_affected": len(touched_users),
                    "lots_routed": len(plan.moves),
                    "transfer_operations": transfer_count,
                    "reason": reason,
                },
                severity=AuditSeverity.WARNING,
                is_suspicious=False,
            )
        )
        await self._repository.flush()
        for user_id in touched_users:
            await self._ledger.assert_invariants(states[user_id])
        total_after = sum(state.points_balance for state in states.values())
        if total_after != plan.preview.total_balance_points:
            raise RuntimeError("wallet-mode switch changed global point total")
        return WalletModeChangeResult(
            wallet_mode=settings.wallet_mode,
            wallets_created=created,
            transfer_operations=transfer_count,
            total_balance_points=total_after,
            completed_at=now,
            idempotent_replay=False,
        )

    async def _required_settings(
        self,
        *,
        lock_mode: Literal["none", "share", "update"],
    ) -> LoyaltySettings:
        settings = await self._repository.get_settings(lock_mode=lock_mode)
        if settings is None:
            raise RuntimeError("Loyalty settings are not initialized")
        return settings


def _destination_venue(
    lot: PointLot,
    *,
    target_mode: WalletMode,
    available_venues: dict[UUID, Venue],
    fallback_venue_id: UUID | None,
) -> tuple[UUID | None, bool]:
    if target_mode is WalletMode.SHARED:
        return None, False
    origin_available = lot.source_venue_id in available_venues
    if origin_available:
        return lot.source_venue_id, False
    return fallback_venue_id, True


def _transfer_operation(
    *,
    user_id: UUID,
    switch_id: UUID,
    ordinal: int,
    side: str,
    operation_type: LoyaltyOperationType,
    balance: int,
    reason: str,
    now: datetime,
) -> LoyaltyOperation:
    return LoyaltyOperation(
        id=uuid4(),
        user_id=user_id,
        operation_type=operation_type,
        status=OperationStatus.COMMITTED,
        idempotency_key=f"wallet-switch:{switch_id}:{ordinal}:{side}",
        request_hash=hashlib.sha256(f"{switch_id}:{ordinal}:{side}".encode()).hexdigest(),
        points_delta=0,
        balance_before=balance,
        balance_after=balance,
        reason=reason,
        occurred_at=now,
    )


def _request_hash(
    *,
    actor: Actor,
    target_mode: WalletMode,
    fallback_venue_id: UUID | None,
    preview_hash: str,
    reason: str,
) -> str:
    payload = {
        "actor_user_id": str(actor.user_id),
        "actor_staff_id": str(actor.staff_member_id) if actor.staff_member_id else None,
        "target_mode": target_mode.value,
        "fallback_venue_id": str(fallback_venue_id) if fallback_venue_id else None,
        "preview_hash": preview_hash,
        "reason": reason,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _venue_available(venue: Venue) -> bool:
    return venue.is_active and venue.archived_at is None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _aware_now(value: datetime | None) -> datetime:
    current = value or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return current


def _require_owner(actor: Actor) -> None:
    if not actor.can(PermissionCode.OWNER_CRITICAL_SETTINGS):
        _forbidden()


def _forbidden() -> NoReturn:
    raise AppError(
        code=ErrorCode.FORBIDDEN,
        message="Owner permission is required",
        status_code=status.HTTP_403_FORBIDDEN,
    )


def _validation(code: str, message: str) -> NoReturn:
    raise AppError(code=code, message=message, status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)


def _conflict(code: str, message: str) -> NoReturn:
    raise AppError(code=code, message=message, status_code=status.HTTP_409_CONFLICT)
