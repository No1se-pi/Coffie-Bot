"""Previewed, idempotent, journal-preserving customer account merges."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, NoReturn
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
    Role,
    UserStatus,
)
from app.models.loyalty import (
    LoyaltyOperation,
    PointTransaction,
    StampTransaction,
    UserLoyaltyState,
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
    source_staff_rebound: bool


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

    async def confirm(
        self,
        actor: Actor,
        *,
        source_user_id: UUID,
        canonical_user_id: UUID,
        preview_hash: str,
        reason: str,
        idempotency_key: str,
        metadata: MergeRequestMetadata = EMPTY_METADATA,
        now: datetime | None = None,
    ) -> CustomerMergeResult:
        _require_permission(actor)
        _require_distinct_users(source_user_id, canonical_user_id)
        actor_staff_id = _require_staff_actor(actor)
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
        )

        async with self._repository.transaction():
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
            _validate_merge_rules(actor, context)
            locked_preview = _preview(context)
            if locked_preview.preview_hash != preview_hash:
                raise AppError(
                    code="customer_merge_preview_stale",
                    message="Customer state changed; request a new merge preview",
                    status_code=status.HTTP_409_CONFLICT,
                    details={"current_preview_hash": locked_preview.preview_hash},
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

            source_state.points_balance = 0
            canonical_state.points_balance = canonical_points_after
            source_state.stamp_count = 0
            canonical_state.stamp_count = canonical_stamps_after
            visit_winner_id = locked_preview.visit_snapshot_from_user_id
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

            merge = CustomerMerge(
                id=merge_id,
                source_user_id=source_user_id,
                canonical_user_id=canonical_user_id,
                actor_user_id=actor.user_id,
                actor_staff_id=actor_staff_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                preview_hash=preview_hash,
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
                source_staff_rebound=source_staff_rebound,
                created_at=current_time,
                completed_at=current_time,
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
                    "preview_hash": preview_hash,
                    "request_hash": request_hash,
                    "reason": normalized_reason,
                    "points_transferred": points_transferred,
                    "stamps_transferred": source_stamps_before,
                    "identities_moved": len(context.source.identities),
                    "rewards_moved": len(context.source_rewards),
                    "sessions_revoked": len(context.source_sessions),
                    "cards_revoked": len(context.source_cards),
                    "source_staff_rebound": source_staff_rebound,
                    "visit_snapshot_from_user_id": (
                        str(visit_winner_id) if visit_winner_id is not None else None
                    ),
                },
                severity=AuditSeverity.CRITICAL,
                is_suspicious=False,
                ip_address=_truncate(metadata.ip_address, 45),
                user_agent=_truncate(metadata.user_agent, 512),
            )
            self._repository.add_all([merge, audit])
            await self._repository.flush()
            return CustomerMergeResult(merge=merge, idempotent_replay=False)


def _preview(context: LockedMergeContext) -> CustomerMergePreview:
    visit_winner_id = _visit_snapshot_winner(context)
    snapshot = {
        "source": _hashable_profile(context.source),
        "canonical": _hashable_profile(context.canonical),
        "source_session_ids": sorted(str(item.id) for item in context.source_sessions),
        "source_card_ids": sorted(str(item.id) for item in context.source_cards),
        "canonical_active_card_id": (
            str(context.canonical_card.id) if context.canonical_card is not None else None
        ),
        "source_reward_ids": sorted(str(item.id) for item in context.source_rewards),
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
        source_staff_rebound=context.source.staff is not None,
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
    }


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


def _request_hash(
    *,
    actor: Actor,
    source_user_id: UUID,
    canonical_user_id: UUID,
    preview_hash: str,
    reason: str,
) -> str:
    payload = {
        "action": "customer_merge",
        "actor_user_id": str(actor.user_id),
        "actor_staff_id": str(actor.staff_member_id) if actor.staff_member_id else None,
        "source_user_id": str(source_user_id),
        "canonical_user_id": str(canonical_user_id),
        "preview_hash": preview_hash,
        "reason": reason,
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
