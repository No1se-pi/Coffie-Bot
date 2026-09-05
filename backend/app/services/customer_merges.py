"""Previewed, idempotent, journal-preserving customer account merges."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, NoReturn
from uuid import UUID, uuid4

from fastapi import status

from app.core.errors import AppError, ErrorCode
from app.models.access import User
from app.models.audit import AuditEvent
from app.models.customers import CustomerMerge
from app.models.enums import (
    AuditSeverity,
    CardStatus,
    IdentityProvider,
    LoyaltyOperationType,
    OperationStatus,
    PermissionCode,
    PointAllocationType,
    PointLotSourceType,
    Role,
    UserStatus,
    WalletMode,
)
from app.models.loyalty import (
    LoyaltyOperation,
    PointTransaction,
    StampTransaction,
    UserLoyaltyState,
)
from app.models.loyalty_v2 import (
    AccountMergeLotRoute,
    LoyaltyWallet,
    PointAllocation,
    PointLot,
)
from app.repositories.customer_merges import (
    CustomerMergeRepository,
    LockedMergeContext,
    LockedMergeProfile,
)
from app.security.rbac import Actor


@dataclass(frozen=True, slots=True)
class MergeRequestMetadata:
    ip_address: str | None = None
    user_agent: str | None = None


EMPTY_METADATA = MergeRequestMetadata()
BirthdayResolution = Literal["keep_canonical", "use_source"]
VERIFIED_PHONE_MERGE_REASON = "Verified Telegram contact matched a phone-only profile"


@dataclass(frozen=True, slots=True)
class MergeProfilePreview:
    user_id: UUID
    display_name: str
    status: UserStatus
    identity_providers: tuple[IdentityProvider, ...]
    points_balance: int
    stamp_count: int
    visit_streak: int
    last_visit_business_date: date | None
    staff_role: Role | None
    birthday_set: bool


@dataclass(frozen=True, slots=True)
class CustomerMergePreview:
    source: MergeProfilePreview
    canonical: MergeProfilePreview
    preview_hash: str
    points_to_transfer: int
    stamps_to_transfer: int
    visit_snapshot_from_user_id: UUID | None
    identities_to_move: int
    rewards_to_move: int
    sessions_to_revoke: int
    cards_to_revoke: int
    feedback_to_move: int
    source_staff_rebound: bool
    birthday_conflict: bool
    birthday_resolution_required: bool


@dataclass(frozen=True, slots=True)
class CustomerMergeResult:
    merge: CustomerMerge
    idempotent_replay: bool


class CustomerMergeService:
    """Merge two stable profiles without rewriting immutable business history."""

    def __init__(self, repository: CustomerMergeRepository) -> None:
        self._repository = repository

    async def preview(
        self,
        actor: Actor,
        *,
        source_user_id: UUID,
        canonical_user_id: UUID,
    ) -> CustomerMergePreview:
        _require_permission(actor)
        _require_distinct_users(source_user_id, canonical_user_id)
        async with self._repository.transaction():
            context = await self._repository.lock_context(
                source_user_id=source_user_id,
                canonical_user_id=canonical_user_id,
            )
            if context is None:
                _not_found()
            _validate_merge_rules(actor, context)
            return _preview(context)

    async def merge_verified_phone_profile(
        self,
        *,
        telegram_user_id: UUID,
        telegram_id: int,
        phone_profile_user_id: UUID,
        phone_subject: str,
        now: datetime | None = None,
    ) -> CustomerMergeResult:
        """Merge a proven phone-only profile into its current Telegram profile.

        This method is intentionally not exposed as an HTTP endpoint. The bot
        calls it only after Telegram sends a Contact whose user_id matches the
        sender. The locked identity checks below repeat that proof at the final
        mutation boundary instead of trusting transport-supplied profile ids.
        """

        actor = Actor(
            user_id=telegram_user_id,
            telegram_id=telegram_id,
            session_id=uuid4(),
            role=Role.CUSTOMER,
            staff_member_id=None,
            permissions=frozenset(),
        )
        return await self.confirm(
            actor,
            source_user_id=phone_profile_user_id,
            canonical_user_id=telegram_user_id,
            # Self-service calculates and stores the preview under the final
            # profile locks; there is no unsafe client-provided preview gap.
            preview_hash="",
            reason=VERIFIED_PHONE_MERGE_REASON,
            idempotency_key=(f"verified-phone:{phone_profile_user_id}:{telegram_user_id}"),
            now=now,
            _verified_phone_subject=phone_subject,
        )

    async def confirm(
        self,
        actor: Actor,
        *,
        source_user_id: UUID,
        canonical_user_id: UUID,
        preview_hash: str,
        reason: str,
        idempotency_key: str,
        birthday_resolution: BirthdayResolution | None = None,
        metadata: MergeRequestMetadata = EMPTY_METADATA,
        now: datetime | None = None,
        _verified_phone_subject: str | None = None,
    ) -> CustomerMergeResult:
        if _verified_phone_subject is None:
            _require_permission(actor)
            actor_staff_id: UUID | None = _require_staff_actor(actor)
        else:
            if actor.role is not Role.CUSTOMER or actor.user_id != canonical_user_id:
                raise AppError(
                    code=ErrorCode.FORBIDDEN,
                    message="Verified phone merge must target the current customer",
                    status_code=status.HTTP_403_FORBIDDEN,
                )
            actor_staff_id = None
        _require_distinct_users(source_user_id, canonical_user_id)
        normalized_reason = " ".join(reason.split())
        if len(normalized_reason) < 3:
            raise AppError(
                code=ErrorCode.VALIDATION_ERROR,
                message="Merge reason must contain at least three visible characters",
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        current_time = _aware_now(now)
        request_hash = _request_hash(
            actor=actor,
            source_user_id=source_user_id,
            canonical_user_id=canonical_user_id,
            preview_hash=preview_hash,
            reason=normalized_reason,
            birthday_resolution=birthday_resolution,
            merge_method=(
                "verified_telegram_contact" if _verified_phone_subject is not None else "admin"
            ),
            phone_subject=_verified_phone_subject,
        )

        async with self._repository.transaction():
            # Configuration is always the first database lock.  The advisory
            # key then serializes creation of the immutable merge receipt.
            await self._repository.lock_settings_shared()
            await self._repository.acquire_idempotency_lock(idempotency_key)
            existing = await self._repository.get_by_idempotency_key(idempotency_key)
            if existing is not None:
                if existing.request_hash != request_hash:
                    _conflict(
                        "idempotency_key_reused",
                        "Idempotency key was already used for another merge request",
                    )
                return CustomerMergeResult(merge=existing, idempotent_replay=True)

            context = await self._repository.lock_context(
                source_user_id=source_user_id,
                canonical_user_id=canonical_user_id,
            )
            if context is None:
                _not_found()
            if _verified_phone_subject is None:
                _validate_merge_rules(actor, context)
            else:
                _validate_verified_phone_merge(
                    actor,
                    context,
                    phone_subject=_verified_phone_subject,
                )
            locked_preview = _preview(context)
            effective_preview_hash = locked_preview.preview_hash
            if _verified_phone_subject is None and effective_preview_hash != preview_hash:
                raise AppError(
                    code="customer_merge_preview_stale",
                    message="Customer state changed; request a new merge preview",
                    status_code=status.HTTP_409_CONFLICT,
                    details={"current_preview_hash": locked_preview.preview_hash},
                )
            requested_birthday_resolution = birthday_resolution
            if _verified_phone_subject is not None and _birthday_conflict(context):
                # The authenticated Telegram profile remains canonical. Its
                # already confirmed birthday wins an otherwise ambiguous merge.
                requested_birthday_resolution = "keep_canonical"
            effective_birthday_resolution = _birthday_resolution(
                context, requested_birthday_resolution
            )

            source_state = _ensure_loyalty_state(
                self._repository,
                context.source.user,
                context.source.loyalty_state,
            )
            canonical_state = _ensure_loyalty_state(
                self._repository,
                context.canonical.user,
                context.canonical.loyalty_state,
            )

            # Clear the legacy projection first so a phone-only canonical user
            # can inherit it without violating users.telegram_id UNIQUE. The
            # authoritative CustomerIdentity rows are moved below.
            source_telegram_id = context.source.user.telegram_id
            context.source.user.telegram_id = None
            await self._repository.flush()
            if context.canonical.user.telegram_id is None:
                context.canonical.user.telegram_id = source_telegram_id

            points_transferred = source_state.points_balance
            source_points_before = source_state.points_balance
            canonical_points_before = canonical_state.points_balance
            source_stamps_before = source_state.stamp_count
            canonical_stamps_before = canonical_state.stamp_count
            canonical_points_after = canonical_points_before + points_transferred
            canonical_stamps_after = canonical_stamps_before + source_stamps_before

            merge_id = uuid4()
            source_operation_id = uuid4()
            canonical_operation_id = uuid4()
            operation_key = f"customer-merge:{merge_id}"
            operation_comment = f"merge {source_user_id} into canonical profile {canonical_user_id}"
            source_operation = LoyaltyOperation(
                id=source_operation_id,
                user_id=source_user_id,
                actor_user_id=actor.user_id,
                actor_staff_id=actor_staff_id,
                operation_type=LoyaltyOperationType.ACCOUNT_MERGE_DEBIT,
                status=OperationStatus.COMMITTED,
                idempotency_key=operation_key,
                request_hash=request_hash,
                points_delta=-points_transferred,
                balance_before=source_points_before,
                balance_after=0,
                reason=normalized_reason,
                comment=operation_comment,
                occurred_at=current_time,
            )
            canonical_operation = LoyaltyOperation(
                id=canonical_operation_id,
                user_id=canonical_user_id,
                actor_user_id=actor.user_id,
                actor_staff_id=actor_staff_id,
                operation_type=LoyaltyOperationType.ACCOUNT_MERGE_CREDIT,
                status=OperationStatus.COMMITTED,
                idempotency_key=operation_key,
                request_hash=request_hash,
                points_delta=points_transferred,
                balance_before=canonical_points_before,
                balance_after=canonical_points_after,
                reason=normalized_reason,
                comment=operation_comment,
                occurred_at=current_time,
            )
            point_transactions: list[object] = [
                PointTransaction(
                    id=uuid4(),
                    operation_id=source_operation_id,
                    user_id=source_user_id,
                    delta=-points_transferred,
                    balance_before=source_points_before,
                    balance_after=0,
                    created_at=current_time,
                ),
                PointTransaction(
                    id=uuid4(),
                    operation_id=canonical_operation_id,
                    user_id=canonical_user_id,
                    delta=points_transferred,
                    balance_before=canonical_points_before,
                    balance_after=canonical_points_after,
                    created_at=current_time,
                ),
            ]
            if source_stamps_before > 0:
                # StampTransaction forbids zero deltas. Reusing the paired merge
                # operations keeps points and stamps explained by one atomic
                # business action while preserving separate immutable journals.
                point_transactions.extend(
                    [
                        StampTransaction(
                            id=uuid4(),
                            operation_id=source_operation_id,
                            user_id=source_user_id,
                            delta=-source_stamps_before,
                            stamps_before=source_stamps_before,
                            stamps_after=0,
                            created_at=current_time,
                        ),
                        StampTransaction(
                            id=uuid4(),
                            operation_id=canonical_operation_id,
                            user_id=canonical_user_id,
                            delta=source_stamps_before,
                            stamps_before=canonical_stamps_before,
                            stamps_after=canonical_stamps_after,
                            created_at=current_time,
                        ),
                    ]
                )

            # CustomerMerge and the transaction rows carry FK ids but no ORM
            # relationships: the objects are intentionally immutable records,
            # not a mutable aggregate graph. Explicit staged flushes therefore
            # establish the parent operations before their journal children and
            # lineage receipt. All stages remain inside this one DB transaction,
            # so any later failure rolls every inserted row back atomically.
            self._repository.add_all([source_operation, canonical_operation])
            await self._repository.flush()
            self._repository.add_all(point_transactions)
            await self._repository.flush()

            visit_winner_id = locked_preview.visit_snapshot_from_user_id
            merge = CustomerMerge(
                id=merge_id,
                source_user_id=source_user_id,
                canonical_user_id=canonical_user_id,
                actor_user_id=actor.user_id,
                actor_staff_id=actor_staff_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                preview_hash=effective_preview_hash,
                reason=normalized_reason,
                source_points_operation_id=source_operation_id,
                canonical_points_operation_id=canonical_operation_id,
                source_points_before=source_points_before,
                canonical_points_before=canonical_points_before,
                points_transferred=points_transferred,
                canonical_points_after=canonical_points_after,
                source_stamps_before=source_stamps_before,
                canonical_stamps_before=canonical_stamps_before,
                stamps_transferred=source_stamps_before,
                canonical_stamps_after=canonical_stamps_after,
                visit_snapshot_from_user_id=visit_winner_id,
                identities_moved=len(context.source.identities),
                rewards_moved=len(context.source_rewards),
                sessions_revoked=len(context.source_sessions),
                cards_revoked=len(context.source_cards),
                feedback_moved=len(context.source_feedback),
                birthday_resolution=effective_birthday_resolution,
                source_staff_rebound=context.source.staff is not None,
                created_at=current_time,
                completed_at=current_time,
            )
            self._repository.add(merge)
            await self._repository.flush()

            await _move_wallet_lots(
                self._repository,
                context,
                merge_id=merge_id,
                source_operation_id=source_operation_id,
                canonical_operation_id=canonical_operation_id,
                expected_points=points_transferred,
                now=current_time,
            )

            source_state.points_balance = 0
            canonical_state.points_balance = canonical_points_after
            source_state.stamp_count = 0
            canonical_state.stamp_count = canonical_stamps_after
            if visit_winner_id == source_user_id:
                _copy_visit_snapshot(source_state, canonical_state)
            source_state.version += 1
            canonical_state.version += 1
            source_state.updated_at = current_time
            canonical_state.updated_at = current_time

            for identity in context.source.identities:
                identity.user_id = canonical_user_id
                identity.updated_at = current_time
            for customer_session in context.source_sessions:
                customer_session.revoked_at = current_time
                customer_session.revoke_reason = "customer_merged"
            for card in context.source_cards:
                card.status = CardStatus.REVOKED
                card.revoked_at = current_time
                card.revoked_by_staff_id = actor_staff_id
                card.revoke_reason = "Аккаунт объединён с основным профилем"
                card.updated_at = current_time
            for reward in context.source_rewards:
                reward.user_id = canonical_user_id
                reward.updated_at = current_time
            for feedback in context.source_feedback:
                feedback.user_id = canonical_user_id
                feedback.updated_at = current_time
            _apply_birthday_resolution(
                context,
                effective_birthday_resolution,
                actor_staff_id=actor_staff_id,
                now=current_time,
            )

            source_staff_rebound = context.source.staff is not None
            if context.source.staff is not None:
                # The rules guarantee the canonical profile has no StaffMember,
                # so the one-to-one staff identity can be moved without deleting
                # its permissions, tips, audit references, or employment history.
                context.source.staff.user_id = canonical_user_id
                context.source.staff.updated_at = current_time

            context.source.user.status = UserStatus.MERGED
            context.source.user.merged_into_user_id = canonical_user_id
            context.source.user.merged_at = current_time
            context.source.user.updated_at = current_time
            context.canonical.user.updated_at = current_time
            _assert_merge_wallet_invariants(
                context,
                source_state=source_state,
                canonical_state=canonical_state,
            )

            audit = AuditEvent(
                id=uuid4(),
                event_type="customer.merged",
                actor_user_id=actor.user_id,
                actor_staff_id=actor_staff_id,
                subject_user_id=source_user_id,
                object_type="customer_merge",
                object_id=merge_id,
                idempotency_key=f"customer-merge:{idempotency_key}",
                event_metadata={
                    "canonical_user_id": str(canonical_user_id),
                    "source_user_id": str(source_user_id),
                    "preview_hash": effective_preview_hash,
                    "request_hash": request_hash,
                    "reason": normalized_reason,
                    "points_transferred": points_transferred,
                    "stamps_transferred": source_stamps_before,
                    "identities_moved": len(context.source.identities),
                    "rewards_moved": len(context.source_rewards),
                    "sessions_revoked": len(context.source_sessions),
                    "cards_revoked": len(context.source_cards),
                    "feedback_moved": len(context.source_feedback),
                    "source_staff_rebound": source_staff_rebound,
                    "birthday_source_was_set": locked_preview.source.birthday_set,
                    "birthday_canonical_was_set": locked_preview.canonical.birthday_set,
                    "birthday_conflict": locked_preview.birthday_conflict,
                    "birthday_resolution": effective_birthday_resolution,
                    "visit_snapshot_from_user_id": (
                        str(visit_winner_id) if visit_winner_id is not None else None
                    ),
                    "merge_method": (
                        "verified_telegram_contact"
                        if _verified_phone_subject is not None
                        else "admin"
                    ),
                },
                severity=AuditSeverity.CRITICAL,
                is_suspicious=False,
                ip_address=_truncate(metadata.ip_address, 45),
                user_agent=_truncate(metadata.user_agent, 512),
            )
            self._repository.add(audit)
            await self._repository.flush()
            return CustomerMergeResult(merge=merge, idempotent_replay=False)


def _preview(context: LockedMergeContext) -> CustomerMergePreview:
    _assert_merge_wallet_invariants(context)
    visit_winner_id = _visit_snapshot_winner(context)
    birthday_conflict = _birthday_conflict(context)
    snapshot = {
        "wallet_mode": context.settings.wallet_mode.value,
        "settings_updated_at": context.settings.updated_at,
        "source": _hashable_profile(context.source),
        "canonical": _hashable_profile(context.canonical),
        "source_session_ids": sorted(str(item.id) for item in context.source_sessions),
        "source_card_ids": sorted(str(item.id) for item in context.source_cards),
        "canonical_active_card_id": (
            str(context.canonical_card.id) if context.canonical_card is not None else None
        ),
        "source_reward_ids": sorted(str(item.id) for item in context.source_rewards),
        "source_feedback": [
            {
                "id": str(item.id),
                "status": item.status.value,
                "assigned_to_staff_id": (
                    str(item.assigned_to_staff_id)
                    if item.assigned_to_staff_id is not None
                    else None
                ),
                "updated_at": item.updated_at,
            }
            for item in context.source_feedback
        ],
        "terminal_routes": [_hashable_route(context, lot) for lot in context.source_route_lots],
        "visit_snapshot_from_user_id": (
            str(visit_winner_id) if visit_winner_id is not None else None
        ),
    }
    preview_hash = hashlib.sha256(
        json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()
    source_state = context.source.loyalty_state
    return CustomerMergePreview(
        source=_profile_preview(context.source),
        canonical=_profile_preview(context.canonical),
        preview_hash=preview_hash,
        points_to_transfer=source_state.points_balance if source_state is not None else 0,
        stamps_to_transfer=source_state.stamp_count if source_state is not None else 0,
        visit_snapshot_from_user_id=visit_winner_id,
        identities_to_move=len(context.source.identities),
        rewards_to_move=len(context.source_rewards),
        sessions_to_revoke=len(context.source_sessions),
        cards_to_revoke=len(context.source_cards),
        feedback_to_move=len(context.source_feedback),
        source_staff_rebound=context.source.staff is not None,
        birthday_conflict=birthday_conflict,
        birthday_resolution_required=birthday_conflict,
    )


def _profile_preview(profile: LockedMergeProfile) -> MergeProfilePreview:
    state = profile.loyalty_state
    display_name = " ".join(
        value for value in (profile.user.first_name, profile.user.last_name) if value
    )
    providers = tuple(
        sorted({item.provider for item in profile.identities}, key=lambda value: value.value)
    )
    return MergeProfilePreview(
        user_id=profile.user.id,
        display_name=display_name,
        status=profile.user.status,
        identity_providers=providers,
        points_balance=state.points_balance if state is not None else 0,
        stamp_count=state.stamp_count if state is not None else 0,
        visit_streak=state.visit_streak if state is not None else 0,
        last_visit_business_date=(state.last_visit_business_date if state is not None else None),
        staff_role=profile.staff.role if profile.staff is not None else None,
        birthday_set=_birthday_is_set(profile.user),
    )


def _hashable_profile(profile: LockedMergeProfile) -> dict[str, Any]:
    state = profile.loyalty_state
    return {
        "user_id": str(profile.user.id),
        "status": profile.user.status.value,
        "merged_into_user_id": (
            str(profile.user.merged_into_user_id)
            if profile.user.merged_into_user_id is not None
            else None
        ),
        "telegram_id": profile.user.telegram_id,
        "birthday": (
            [profile.user.birthday_month, profile.user.birthday_day]
            if _birthday_is_set(profile.user)
            else None
        ),
        "staff": (
            {
                "id": str(profile.staff.id),
                "role": profile.staff.role.value,
                "is_active": profile.staff.is_active,
                "archived_at": profile.staff.archived_at,
            }
            if profile.staff is not None
            else None
        ),
        "loyalty": (
            {
                "id": str(state.id),
                "points_balance": state.points_balance,
                "visit_streak": state.visit_streak,
                "last_visit_business_date": state.last_visit_business_date,
                "visit_cycle_started_on": state.visit_cycle_started_on,
                "allowed_misses_used": state.allowed_misses_used,
                "stamp_count": state.stamp_count,
                "version": state.version,
            }
            if state is not None
            else None
        ),
        "identities": [
            {
                "id": str(item.id),
                "provider": item.provider.value,
                "subject": item.subject,
                "is_verified": item.is_verified,
            }
            for item in profile.identities
        ],
        "latest_visit": (
            {
                "id": str(profile.latest_visit.id),
                "business_date": profile.latest_visit.business_date,
                "visited_at": profile.latest_visit.visited_at,
                "streak_after": profile.latest_visit.streak_after,
            }
            if profile.latest_visit is not None
            else None
        ),
        "wallets": [
            {
                "id": str(wallet.id),
                "venue_id": str(wallet.venue_id) if wallet.venue_id is not None else None,
                "balance_points": wallet.balance_points,
                "version": wallet.version,
            }
            for wallet in profile.wallets
        ],
        "lots": [
            {
                "id": str(lot.id),
                "wallet_id": str(lot.wallet_id),
                "remaining_points": lot.remaining_points,
                "earned_at": lot.earned_at,
                "expires_at": lot.expires_at,
                "expired_at": lot.expired_at,
            }
            for lot in profile.lots
        ],
    }


def _hashable_route(context: LockedMergeContext, lot: PointLot) -> dict[str, Any]:
    route = context.terminal_routes.get(lot.id)
    return {
        "source_lot_id": str(lot.id),
        "wallet_id": str(route.wallet_id) if route is not None else None,
        "lot_id": (str(route.lot_id) if route is not None and route.lot_id is not None else None),
        "routed_at": route.routed_at if route is not None else None,
    }


def _assert_merge_wallet_invariants(
    context: LockedMergeContext,
    *,
    source_state: UserLoyaltyState | None = None,
    canonical_state: UserLoyaltyState | None = None,
) -> None:
    states = (
        source_state or context.source.loyalty_state,
        canonical_state or context.canonical.loyalty_state,
    )
    for profile, state in zip((context.source, context.canonical), states, strict=True):
        expected = state.points_balance if state else 0
        if sum(wallet.balance_points for wallet in profile.wallets) != expected:
            _conflict(
                "customer_merge_wallet_inconsistent",
                "Loyalty wallet totals do not match the customer snapshot",
            )
        lots_by_wallet: dict[UUID, int] = {}
        for lot in profile.lots:
            lots_by_wallet[lot.wallet_id] = (
                lots_by_wallet.get(lot.wallet_id, 0) + lot.remaining_points
            )
        for wallet in profile.wallets:
            if lots_by_wallet.get(wallet.id, 0) != wallet.balance_points:
                _conflict(
                    "customer_merge_lot_inconsistent",
                    "Loyalty lots do not match their wallet snapshot",
                )
            inactive_scope = (
                context.settings.wallet_mode is WalletMode.SHARED and wallet.venue_id is not None
            ) or (context.settings.wallet_mode is WalletMode.SEPARATE and wallet.venue_id is None)
            if inactive_scope and wallet.balance_points != 0:
                _conflict(
                    "customer_merge_wallet_mode_inconsistent",
                    "An inactive loyalty wallet scope still has a balance",
                )


async def _move_wallet_lots(
    repository: CustomerMergeRepository,
    context: LockedMergeContext,
    *,
    merge_id: UUID,
    source_operation_id: UUID,
    canonical_operation_id: UUID,
    expected_points: int,
    now: datetime,
) -> None:
    source_wallets = {wallet.id: wallet for wallet in context.source.wallets}
    canonical_by_scope = {wallet.venue_id: wallet for wallet in context.canonical.wallets}
    moved = 0
    new_wallets: list[LoyaltyWallet] = []
    destination_lots: list[PointLot] = []
    allocations: list[PointAllocation] = []
    routes: list[AccountMergeLotRoute] = []
    source_debits: dict[UUID, int] = {}
    target_credits: dict[UUID, int] = {}
    route_time = now
    if context.route_timestamp_floor is not None and context.route_timestamp_floor >= route_time:
        route_time = context.route_timestamp_floor + timedelta(microseconds=1)

    for lot in context.source_route_lots:
        prior_route = context.terminal_routes.get(lot.id)
        terminal_wallet_id = prior_route.wallet_id if prior_route is not None else lot.wallet_id
        terminal_wallet = source_wallets.get(terminal_wallet_id)
        if terminal_wallet is None:
            _conflict(
                "customer_merge_route_inconsistent",
                "A historical point lot no longer resolves to the source profile",
            )
        if lot.remaining_points > 0 and prior_route is not None:
            _conflict(
                "customer_merge_route_inconsistent",
                "A routed historical lot unexpectedly retains points",
            )
        if (
            context.settings.wallet_mode is WalletMode.SHARED
            and terminal_wallet.venue_id is not None
        ) or (
            context.settings.wallet_mode is WalletMode.SEPARATE and terminal_wallet.venue_id is None
        ):
            _conflict(
                "customer_merge_route_missing",
                "A historical point lot has no route to the current wallet mode",
            )

        target_wallet = canonical_by_scope.get(terminal_wallet.venue_id)
        if target_wallet is None:
            target_wallet = LoyaltyWallet(
                id=uuid4(),
                user_id=context.canonical.user.id,
                venue_id=terminal_wallet.venue_id,
                balance_points=0,
                version=1,
                created_at=now,
                updated_at=now,
            )
            canonical_by_scope[terminal_wallet.venue_id] = target_wallet
            context.canonical.wallets.append(target_wallet)
            new_wallets.append(target_wallet)

        amount = lot.remaining_points
        destination_lot: PointLot | None = None
        if amount > 0:
            actual_source_wallet = source_wallets.get(lot.wallet_id)
            if actual_source_wallet is None:
                raise RuntimeError("A positive merge lot is not owned by the source profile")
            source_debits[actual_source_wallet.id] = (
                source_debits.get(actual_source_wallet.id, 0) + amount
            )
            target_credits[target_wallet.id] = target_credits.get(target_wallet.id, 0) + amount
            lot.remaining_points = 0
            destination_lot = PointLot(
                id=uuid4(),
                wallet_id=target_wallet.id,
                source_operation_id=canonical_operation_id,
                source_venue_id=lot.source_venue_id,
                transferred_from_lot_id=lot.id,
                source_type=PointLotSourceType.ACCOUNT_MERGE,
                initial_points=amount,
                remaining_points=amount,
                earned_at=lot.earned_at,
                expires_at=lot.expires_at,
                expired_at=None,
                expiry_reminder_scheduled_at=lot.expiry_reminder_scheduled_at,
                created_at=now,
                updated_at=now,
            )
            context.canonical.lots.append(destination_lot)
            destination_lots.append(destination_lot)
            allocations.append(
                PointAllocation(
                    id=uuid4(),
                    operation_id=source_operation_id,
                    lot_id=lot.id,
                    allocation_type=PointAllocationType.ACCOUNT_MERGE_DEBIT,
                    points=amount,
                    created_at=now,
                )
            )
            moved += amount

        if prior_route is not None and prior_route.routed_at >= route_time:
            raise RuntimeError("Global point-lot route timestamp is inconsistent")
        routes.append(
            AccountMergeLotRoute(
                id=uuid4(),
                customer_merge_id=merge_id,
                source_lot_id=lot.id,
                destination_wallet_id=target_wallet.id,
                destination_lot_id=(destination_lot.id if destination_lot is not None else None),
                created_at=route_time,
            )
        )

    if moved != expected_points:
        _conflict(
            "customer_merge_point_lineage_incomplete",
            "Point lots do not explain the transferable balance",
        )
    targets_by_id = {wallet.id: wallet for wallet in canonical_by_scope.values()}
    for wallet_id in sorted(source_debits, key=lambda value: value.int):
        wallet = source_wallets[wallet_id]
        wallet.balance_points -= source_debits[wallet_id]
        wallet.version += 1
    for wallet_id in sorted(target_credits, key=lambda value: value.int):
        wallet = targets_by_id[wallet_id]
        wallet.balance_points += target_credits[wallet_id]
        wallet.version += 1
    # These append-only models intentionally carry FK ids without mutable ORM
    # relationships. Stage the flushes so PostgreSQL never observes a route
    # before its newly created destination wallet/lot exists.
    stages: tuple[list[object], ...] = (
        list(new_wallets),
        list(destination_lots),
        list(allocations),
        list(routes),
    )
    for objects in stages:
        if objects:
            repository.add_all(objects)
            await repository.flush()


def _birthday_is_set(user: User) -> bool:
    return user.birthday_month is not None and user.birthday_day is not None


def _birthday_conflict(context: LockedMergeContext) -> bool:
    if not (_birthday_is_set(context.source.user) and _birthday_is_set(context.canonical.user)):
        return False
    return (
        context.source.user.birthday_month,
        context.source.user.birthday_day,
    ) != (
        context.canonical.user.birthday_month,
        context.canonical.user.birthday_day,
    )


def _birthday_resolution(
    context: LockedMergeContext,
    requested: BirthdayResolution | None,
) -> BirthdayResolution:
    conflict = _birthday_conflict(context)
    if conflict and requested is None:
        raise AppError(
            code="customer_merge_birthday_resolution_required",
            message="Choose which confirmed birthday the canonical profile keeps",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    if not conflict and requested is not None:
        raise AppError(
            code="customer_merge_birthday_resolution_not_applicable",
            message="Birthday resolution is only accepted for conflicting values",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    if requested is not None:
        return requested
    if _birthday_is_set(context.source.user) and not _birthday_is_set(context.canonical.user):
        return "use_source"
    return "keep_canonical"


def _apply_birthday_resolution(
    context: LockedMergeContext,
    resolution: BirthdayResolution,
    *,
    actor_staff_id: UUID | None,
    now: datetime,
) -> None:
    if resolution != "use_source":
        return
    source = context.source.user
    canonical = context.canonical.user
    if not _birthday_is_set(source):
        raise RuntimeError("Source birthday is unavailable for the selected resolution")
    canonical.birthday_month = source.birthday_month
    canonical.birthday_day = source.birthday_day
    canonical.birthday_set_at = source.birthday_set_at or now
    canonical.birthday_updated_at = now
    canonical.birthday_updated_by_staff_id = actor_staff_id


def _visit_snapshot_winner(context: LockedMergeContext) -> UUID | None:
    source_visit = context.source.latest_visit
    canonical_visit = context.canonical.latest_visit
    if source_visit is not None and (
        canonical_visit is None or source_visit.visited_at > canonical_visit.visited_at
    ):
        return context.source.user.id
    if canonical_visit is not None:
        return context.canonical.user.id

    source_date = (
        context.source.loyalty_state.last_visit_business_date
        if context.source.loyalty_state is not None
        else None
    )
    canonical_date = (
        context.canonical.loyalty_state.last_visit_business_date
        if context.canonical.loyalty_state is not None
        else None
    )
    if source_date is not None and (canonical_date is None or source_date > canonical_date):
        return context.source.user.id
    if canonical_date is not None:
        return context.canonical.user.id
    return None


def _ensure_loyalty_state(
    repository: CustomerMergeRepository,
    user: User,
    current: UserLoyaltyState | None,
) -> UserLoyaltyState:
    if current is not None:
        return current
    state = UserLoyaltyState(
        id=uuid4(),
        user_id=user.id,
        points_balance=0,
        visit_streak=0,
        last_visit_business_date=None,
        visit_cycle_started_on=None,
        allowed_misses_used=0,
        stamp_count=0,
        version=1,
    )
    repository.add(state)
    return state


def _copy_visit_snapshot(source: UserLoyaltyState, canonical: UserLoyaltyState) -> None:
    canonical.visit_streak = source.visit_streak
    canonical.last_visit_business_date = source.last_visit_business_date
    canonical.visit_cycle_started_on = source.visit_cycle_started_on
    canonical.allowed_misses_used = source.allowed_misses_used


def _validate_merge_rules(actor: Actor, context: LockedMergeContext) -> None:
    for profile in (context.source, context.canonical):
        if profile.user.status is UserStatus.MERGED or profile.user.merged_into_user_id is not None:
            _conflict("customer_already_merged", "A selected customer is already merged")
        if profile.user.status is UserStatus.ANONYMIZED:
            _conflict("anonymized_customer", "An anonymized customer cannot be merged")

    if context.canonical.user.status not in {UserStatus.ACTIVE, UserStatus.BLOCKED}:
        _conflict(
            "canonical_customer_unavailable",
            "Canonical customer must be active or blocked",
        )
    if context.canonical_card is None:
        # Source cards must be revoked, never silently rebound. Requiring an
        # already-issued canonical card therefore preserves the invariant that
        # the surviving profile has one usable opaque QR after the transaction.
        _conflict(
            "canonical_active_card_required",
            "Canonical customer must have an active card before accounts are merged",
        )

    staff_profiles = [
        profile.staff
        for profile in (context.source, context.canonical)
        if profile.staff is not None
    ]
    if any(item.role is Role.OWNER for item in staff_profiles):
        _conflict("owner_profile_merge_forbidden", "An owner profile can never be merged")
    if len(staff_profiles) == 2:
        _conflict("two_staff_profiles", "Two staff profiles cannot be merged")
    if staff_profiles and actor.role is not Role.OWNER:
        raise AppError(
            code=ErrorCode.FORBIDDEN,
            message="Only an owner may merge a profile that belongs to staff",
            status_code=status.HTTP_403_FORBIDDEN,
        )


def _validate_verified_phone_merge(
    actor: Actor,
    context: LockedMergeContext,
    *,
    phone_subject: str,
) -> None:
    """Repeat all self-service ownership checks while both users are locked."""

    if (
        context.source.user.status is not UserStatus.ACTIVE
        or context.canonical.user.status is not UserStatus.ACTIVE
    ):
        _conflict(
            "phone_profile_merge_unavailable",
            "Only active customer profiles can be linked automatically",
        )
    if context.source.staff is not None or context.canonical.staff is not None:
        _conflict(
            "staff_phone_merge_forbidden",
            "Staff profiles require an owner-reviewed merge",
        )
    if context.canonical_card is None:
        _conflict(
            "canonical_active_card_required",
            "The Telegram profile must have an active card",
        )
    if len(context.source_cards) != 1:
        _conflict(
            "phone_profile_active_card_required",
            "The phone-only profile must have one active card",
        )
    if context.source.user.telegram_id is not None:
        _conflict(
            "phone_profile_has_telegram",
            "A profile already linked to Telegram cannot be merged automatically",
        )
    if context.canonical.user.telegram_id != actor.telegram_id:
        raise AppError(
            code=ErrorCode.FORBIDDEN,
            message="Telegram identity does not belong to the current profile",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    source_phone_identities = [
        identity
        for identity in context.source.identities
        if identity.provider is IdentityProvider.PHONE
    ]
    if (
        len(source_phone_identities) != 1
        or source_phone_identities[0].subject != phone_subject
        or not source_phone_identities[0].is_verified
        or source_phone_identities[0].verified_by_staff_id is None
        or source_phone_identities[0].provider_metadata.get("verification_method") != "staff"
    ):
        raise AppError(
            code=ErrorCode.FORBIDDEN,
            message="The phone-only profile has no matching verified staff contact",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    if len(context.source.identities) != 1:
        _conflict(
            "phone_profile_not_exclusive",
            "A profile with additional identities requires an administrator",
        )

    canonical_telegram = [
        identity
        for identity in context.canonical.identities
        if identity.provider is IdentityProvider.TELEGRAM
        and identity.subject == str(actor.telegram_id)
        and identity.is_verified
    ]
    if len(canonical_telegram) != 1:
        raise AppError(
            code=ErrorCode.FORBIDDEN,
            message="The current profile has no matching verified Telegram identity",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    if any(
        identity.provider is IdentityProvider.PHONE for identity in context.canonical.identities
    ):
        _conflict(
            "phone_already_linked",
            "The Telegram profile already has a phone number",
        )


def _request_hash(
    *,
    actor: Actor,
    source_user_id: UUID,
    canonical_user_id: UUID,
    preview_hash: str,
    reason: str,
    birthday_resolution: BirthdayResolution | None,
    merge_method: str = "admin",
    phone_subject: str | None = None,
) -> str:
    payload = {
        "action": "customer_merge",
        "actor_user_id": str(actor.user_id),
        "actor_staff_id": str(actor.staff_member_id) if actor.staff_member_id else None,
        "source_user_id": str(source_user_id),
        "canonical_user_id": str(canonical_user_id),
        "preview_hash": preview_hash,
        "reason": reason,
        "birthday_resolution": birthday_resolution,
        "merge_method": merge_method,
        # Bind the proof to the immutable receipt hash without writing the
        # plaintext phone number into the merge audit event.
        "phone_subject": phone_subject,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _require_permission(actor: Actor) -> None:
    if PermissionCode.ADMIN_USERS_MANAGE not in actor.permissions:
        raise AppError(
            code=ErrorCode.FORBIDDEN,
            message="Insufficient permissions",
            status_code=status.HTTP_403_FORBIDDEN,
        )


def _require_staff_actor(actor: Actor) -> UUID:
    if actor.staff_member_id is None:
        raise AppError(
            code=ErrorCode.FORBIDDEN,
            message="Staff identity is required",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    return actor.staff_member_id


def _require_distinct_users(source_user_id: UUID, canonical_user_id: UUID) -> None:
    if source_user_id == canonical_user_id:
        raise AppError(
            code=ErrorCode.VALIDATION_ERROR,
            message="Source and canonical customer must be different",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )


def _not_found() -> NoReturn:
    raise AppError(
        code=ErrorCode.NOT_FOUND,
        message="Source or canonical customer was not found",
        status_code=status.HTTP_404_NOT_FOUND,
    )


def _conflict(code: str, message: str) -> NoReturn:
    raise AppError(code=code, message=message, status_code=status.HTTP_409_CONFLICT)


def _aware_now(value: datetime | None) -> datetime:
    current = value or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("Merge timestamps must be timezone-aware")
    return current


def _truncate(value: str | None, limit: int) -> str | None:
    return value[:limit] if value is not None else None
