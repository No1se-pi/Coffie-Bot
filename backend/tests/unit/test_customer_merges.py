from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from app.api.routes import customer_merges
from app.core.errors import AppError
from app.models.access import Session, StaffMember, User
from app.models.audit import AuditEvent
from app.models.cards import UserCard
from app.models.customers import CustomerIdentity, CustomerMerge
from app.models.enums import (
    CardStatus,
    IdentityProvider,
    LoyaltyOperationType,
    OperationStatus,
    PermissionCode,
    PointLotSourceType,
    RewardStatus,
    RewardType,
    Role,
    UserStatus,
    WalletMode,
)
from app.models.loyalty import (
    LoyaltyOperation,
    LoyaltySettings,
    PointTransaction,
    Reward,
    StampTransaction,
    UserLoyaltyState,
    Visit,
)
from app.models.loyalty_v2 import LoyaltyWallet, PointLot
from app.repositories.customer_merges import (
    CustomerMergeRepository,
    LockedMergeContext,
    LockedMergeProfile,
)
from app.schemas.customer_merges import (
    CustomerMergeConfirmRequest,
    customer_merge_preview_response,
)
from app.security.rbac import Actor
from app.services.customer_merges import CustomerMergeService, MergeRequestMetadata

NOW = datetime(2026, 8, 24, 12, tzinfo=UTC)


class RecordingMergeRepository:
    def __init__(self, context: LockedMergeContext) -> None:
        self.context = context
        self.existing: CustomerMerge | None = None
        self.added: list[object] = []
        self.idempotency_locks: list[str] = []
        self.lock_context_calls = 0
        self.flushes = 0
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

    def add(self, value: object) -> None:
        self.added.append(value)
        if isinstance(value, CustomerMerge):
            self.existing = value

    def add_all(self, values: list[object]) -> None:
        self.added.extend(values)
        for value in values:
            if isinstance(value, CustomerMerge):
                self.existing = value

    async def flush(self) -> None:
        self.flushes += 1

    async def acquire_idempotency_lock(self, key: str) -> None:
        self.idempotency_locks.append(key)

    async def lock_settings_shared(self) -> LoyaltySettings:
        return self.context.settings

    async def get_by_idempotency_key(self, key: str) -> CustomerMerge | None:
        if self.existing is not None and self.existing.idempotency_key == key:
            return self.existing
        return None

    async def lock_context(
        self,
        *,
        source_user_id: UUID,
        canonical_user_id: UUID,
    ) -> LockedMergeContext | None:
        assert source_user_id == self.context.source.user.id
        assert canonical_user_id == self.context.canonical.user.id
        self.lock_context_calls += 1
        return self.context


def _actor(role: Role = Role.ADMIN) -> Actor:
    return Actor(
        user_id=uuid4(),
        telegram_id=9001,
        session_id=uuid4(),
        role=role,
        staff_member_id=uuid4(),
        permissions=frozenset({PermissionCode.ADMIN_USERS_MANAGE}),
    )


def _user(*, telegram_id: int | None, name: str) -> User:
    return User(
        id=uuid4(),
        telegram_id=telegram_id,
        first_name=name,
        status=UserStatus.ACTIVE,
        merged_into_user_id=None,
        merged_at=None,
    )


def _state(user_id: UUID, *, points: int, stamps: int, visit_day: date) -> UserLoyaltyState:
    return UserLoyaltyState(
        id=uuid4(),
        user_id=user_id,
        points_balance=points,
        visit_streak=4,
        last_visit_business_date=visit_day,
        visit_cycle_started_on=visit_day - timedelta(days=3),
        allowed_misses_used=1,
        stamp_count=stamps,
        version=3,
    )


def _context(
    *,
    source_staff_role: Role | None = None,
    canonical_staff_role: Role | None = None,
) -> LockedMergeContext:
    source = _user(telegram_id=101, name="Источник")
    canonical = _user(telegram_id=None, name="Основной")
    source_staff = (
        StaffMember(
            id=uuid4(),
            user_id=source.id,
            role=source_staff_role,
            is_active=True,
        )
        if source_staff_role is not None
        else None
    )
    canonical_staff = (
        StaffMember(
            id=uuid4(),
            user_id=canonical.id,
            role=canonical_staff_role,
            is_active=True,
        )
        if canonical_staff_role is not None
        else None
    )
    source_state = _state(
        source.id,
        points=70,
        stamps=3,
        visit_day=date(2026, 8, 24),
    )
    canonical_state = _state(
        canonical.id,
        points=30,
        stamps=4,
        visit_day=date(2026, 8, 20),
    )
    identity = CustomerIdentity(
        id=uuid4(),
        user_id=source.id,
        provider=IdentityProvider.TELEGRAM,
        subject="101",
        is_verified=True,
        provider_metadata={},
    )
    customer_session = Session(
        id=uuid4(),
        user_id=source.id,
        token_hash="a" * 64,
        created_at=NOW - timedelta(days=1),
        expires_at=NOW + timedelta(days=1),
    )
    card = UserCard(
        id=uuid4(),
        user_id=source.id,
        qr_token="source-card-token",
        short_code="SRC12345",
        status=CardStatus.ACTIVE,
    )
    canonical_card = UserCard(
        id=uuid4(),
        user_id=canonical.id,
        qr_token="canonical-card-token",
        short_code="CAN12345",
        status=CardStatus.ACTIVE,
    )
    reward = Reward(
        id=uuid4(),
        user_id=source.id,
        template_id=uuid4(),
        name="Подарок",
        description="Описание",
        reward_type=RewardType.TEXT,
        status=RewardStatus.ACTIVE,
    )
    visit = Visit(
        id=uuid4(),
        operation_id=uuid4(),
        user_id=source.id,
        staff_member_id=uuid4(),
        business_date=date(2026, 8, 24),
        ordinal=1,
        visited_at=NOW - timedelta(hours=1),
        streak_after=4,
    )
    canonical_visit = Visit(
        id=uuid4(),
        operation_id=uuid4(),
        user_id=canonical.id,
        staff_member_id=uuid4(),
        business_date=date(2026, 8, 20),
        ordinal=1,
        visited_at=NOW - timedelta(days=4),
        streak_after=4,
    )
    settings = LoyaltySettings(
        id=uuid4(),
        singleton_key="default",
        wallet_mode=WalletMode.SHARED,
        updated_at=NOW,
    )
    source_wallet = LoyaltyWallet(
        id=uuid4(),
        user_id=source.id,
        venue_id=None,
        balance_points=70,
        version=1,
    )
    canonical_wallet = LoyaltyWallet(
        id=uuid4(),
        user_id=canonical.id,
        venue_id=None,
        balance_points=30,
        version=1,
    )
    source_lot = PointLot(
        id=uuid4(),
        wallet_id=source_wallet.id,
        source_operation_id=None,
        source_venue_id=None,
        source_type=PointLotSourceType.OPENING_BALANCE,
        initial_points=70,
        remaining_points=70,
        earned_at=NOW - timedelta(days=30),
        expires_at=None,
    )
    canonical_lot = PointLot(
        id=uuid4(),
        wallet_id=canonical_wallet.id,
        source_operation_id=None,
        source_venue_id=None,
        source_type=PointLotSourceType.OPENING_BALANCE,
        initial_points=30,
        remaining_points=30,
        earned_at=NOW - timedelta(days=20),
        expires_at=None,
    )
    return LockedMergeContext(
        settings=settings,
        source=LockedMergeProfile(
            user=source,
            staff=source_staff,
            loyalty_state=source_state,
            identities=[identity],
            latest_visit=visit,
            wallets=[source_wallet],
            lots=[source_lot],
        ),
        canonical=LockedMergeProfile(
            user=canonical,
            staff=canonical_staff,
            loyalty_state=canonical_state,
            identities=[],
            latest_visit=canonical_visit,
            wallets=[canonical_wallet],
            lots=[canonical_lot],
        ),
        source_sessions=[customer_session],
        source_cards=[card],
        canonical_card=canonical_card,
        source_rewards=[reward],
        source_feedback=[],
        source_route_lots=[source_lot],
        terminal_routes={source_lot.id: None},
        route_timestamp_floor=None,
    )


def test_merge_routes_require_preview_confirmation_and_idempotency_header() -> None:
    app = FastAPI()
    app.include_router(customer_merges.router, prefix="/api/v1")

    paths = app.openapi()["paths"]
    assert "post" in paths["/api/v1/admin/customer-merge/preview"]
    confirm = paths["/api/v1/admin/customer-merge/confirm"]["post"]
    assert any(
        parameter["name"] == "Idempotency-Key"
        and parameter["in"] == "header"
        and parameter["required"] is True
        for parameter in confirm["parameters"]
    )
    assert confirm["security"]


def test_confirm_schema_requires_explicit_true_and_normalized_reason() -> None:
    values = {
        "source_user_id": uuid4(),
        "canonical_user_id": uuid4(),
        "preview_hash": "a" * 64,
        "reason": "  Дубликат   профиля  ",
        "confirm": True,
    }
    assert CustomerMergeConfirmRequest(**values).reason == "Дубликат профиля"

    with pytest.raises(ValidationError):
        CustomerMergeConfirmRequest(**{**values, "confirm": False})
    with pytest.raises(ValidationError):
        CustomerMergeConfirmRequest(**{**values, "role": "owner"})


@pytest.mark.asyncio
async def test_preview_is_hashed_and_does_not_expose_identity_subjects() -> None:
    context = _context()
    repository = RecordingMergeRepository(context)
    service = CustomerMergeService(cast(CustomerMergeRepository, repository))

    preview = await service.preview(
        _actor(),
        source_user_id=context.source.user.id,
        canonical_user_id=context.canonical.user.id,
    )
    response = customer_merge_preview_response(preview).model_dump(mode="json")

    assert len(preview.preview_hash) == 64
    assert preview.points_to_transfer == 70
    assert preview.stamps_to_transfer == 3
    assert preview.visit_snapshot_from_user_id == context.source.user.id
    assert response["source"]["identity_providers"] == ["telegram"]
    # Check the response shape instead of searching the random SHA-256 digest:
    # a digest can legitimately contain the digits of the Telegram subject.
    assert "identity_subjects" not in response["source"]
    assert "telegram_id" not in response["source"]


@pytest.mark.asyncio
async def test_confirm_moves_mutable_ownership_and_writes_paired_journals() -> None:
    context = _context()
    repository = RecordingMergeRepository(context)
    service = CustomerMergeService(cast(CustomerMergeRepository, repository))
    actor = _actor()
    preview = await service.preview(
        actor,
        source_user_id=context.source.user.id,
        canonical_user_id=context.canonical.user.id,
    )
    key = str(uuid4())

    result = await service.confirm(
        actor,
        source_user_id=context.source.user.id,
        canonical_user_id=context.canonical.user.id,
        preview_hash=preview.preview_hash,
        reason="Подтверждённый дубликат профиля",
        idempotency_key=key,
        metadata=MergeRequestMetadata(ip_address="127.0.0.1", user_agent="pytest"),
        now=NOW,
    )

    source_state = context.source.loyalty_state
    canonical_state = context.canonical.loyalty_state
    assert source_state is not None
    assert canonical_state is not None
    assert source_state.points_balance == 0
    assert canonical_state.points_balance == 100
    assert source_state.stamp_count == 0
    assert canonical_state.stamp_count == 7
    assert canonical_state.last_visit_business_date == date(2026, 8, 24)
    assert context.source.user.status is UserStatus.MERGED
    assert context.source.user.merged_into_user_id == context.canonical.user.id
    assert context.source.user.telegram_id is None
    assert context.canonical.user.telegram_id == 101
    assert context.source.identities[0].user_id == context.canonical.user.id
    assert context.source_sessions[0].revoked_at == NOW
    assert context.source_cards[0].status is CardStatus.REVOKED
    assert context.source_rewards[0].user_id == context.canonical.user.id

    operations = [item for item in repository.added if isinstance(item, LoyaltyOperation)]
    assert {item.operation_type for item in operations} == {
        LoyaltyOperationType.ACCOUNT_MERGE_DEBIT,
        LoyaltyOperationType.ACCOUNT_MERGE_CREDIT,
    }
    assert all(item.status is OperationStatus.COMMITTED for item in operations)
    assert sorted(item.points_delta for item in operations) == [-70, 70]
    point_transactions = [item for item in repository.added if isinstance(item, PointTransaction)]
    stamp_transactions = [item for item in repository.added if isinstance(item, StampTransaction)]
    assert sorted(item.delta for item in point_transactions) == [-70, 70]
    assert sorted(item.delta for item in stamp_transactions) == [-3, 3]

    assert result.idempotent_replay is False
    assert result.merge.points_transferred == 70
    assert result.merge.stamps_transferred == 3
    audit = next(item for item in repository.added if isinstance(item, AuditEvent))
    assert audit.event_type == "customer.merged"
    assert audit.idempotency_key == f"customer-merge:{key}"
    assert audit.event_metadata["canonical_user_id"] == str(context.canonical.user.id)
    assert repository.flushes == 8


@pytest.mark.asyncio
async def test_confirm_replays_same_request_and_rejects_key_reuse() -> None:
    context = _context()
    repository = RecordingMergeRepository(context)
    service = CustomerMergeService(cast(CustomerMergeRepository, repository))
    actor = _actor()
    preview = await service.preview(
        actor,
        source_user_id=context.source.user.id,
        canonical_user_id=context.canonical.user.id,
    )
    key = str(uuid4())
    first = await service.confirm(
        actor,
        source_user_id=context.source.user.id,
        canonical_user_id=context.canonical.user.id,
        preview_hash=preview.preview_hash,
        reason="Один подтверждённый профиль",
        idempotency_key=key,
        now=NOW,
    )
    calls_after_first = repository.lock_context_calls
    second = await service.confirm(
        actor,
        source_user_id=context.source.user.id,
        canonical_user_id=context.canonical.user.id,
        preview_hash=preview.preview_hash,
        reason="Один подтверждённый профиль",
        idempotency_key=key,
        now=NOW,
    )

    assert first.merge is second.merge
    assert second.idempotent_replay is True
    assert repository.lock_context_calls == calls_after_first

    with pytest.raises(AppError) as conflict:
        await service.confirm(
            actor,
            source_user_id=context.source.user.id,
            canonical_user_id=context.canonical.user.id,
            preview_hash=preview.preview_hash,
            reason="Другая причина",
            idempotency_key=key,
            now=NOW,
        )
    assert conflict.value.status_code == 409
    assert conflict.value.code == "idempotency_key_reused"


@pytest.mark.asyncio
async def test_stale_preview_fails_before_any_merge_mutation() -> None:
    context = _context()
    repository = RecordingMergeRepository(context)
    service = CustomerMergeService(cast(CustomerMergeRepository, repository))

    with pytest.raises(AppError) as error:
        await service.confirm(
            _actor(),
            source_user_id=context.source.user.id,
            canonical_user_id=context.canonical.user.id,
            preview_hash="0" * 64,
            reason="Подтверждённый дубликат",
            idempotency_key=str(uuid4()),
            now=NOW,
        )

    assert error.value.status_code == 409
    assert error.value.code == "customer_merge_preview_stale"
    assert context.source.user.status is UserStatus.ACTIVE
    assert repository.added == []


@pytest.mark.asyncio
async def test_staff_merge_rules_are_conservative() -> None:
    source_staff = _context(source_staff_role=Role.STAFF)
    service = CustomerMergeService(
        cast(CustomerMergeRepository, RecordingMergeRepository(source_staff))
    )
    with pytest.raises(AppError) as admin_error:
        await service.preview(
            _actor(Role.ADMIN),
            source_user_id=source_staff.source.user.id,
            canonical_user_id=source_staff.canonical.user.id,
        )
    assert admin_error.value.status_code == 403

    owner_preview = await service.preview(
        _actor(Role.OWNER),
        source_user_id=source_staff.source.user.id,
        canonical_user_id=source_staff.canonical.user.id,
    )
    assert owner_preview.source_staff_rebound is True

    two_staff = _context(source_staff_role=Role.STAFF, canonical_staff_role=Role.ADMIN)
    with pytest.raises(AppError) as two_staff_error:
        await CustomerMergeService(
            cast(CustomerMergeRepository, RecordingMergeRepository(two_staff))
        ).preview(
            _actor(Role.OWNER),
            source_user_id=two_staff.source.user.id,
            canonical_user_id=two_staff.canonical.user.id,
        )
    assert two_staff_error.value.code == "two_staff_profiles"

    owner_profile = _context(source_staff_role=Role.OWNER)
    with pytest.raises(AppError) as owner_profile_error:
        await CustomerMergeService(
            cast(CustomerMergeRepository, RecordingMergeRepository(owner_profile))
        ).preview(
            _actor(Role.OWNER),
            source_user_id=owner_profile.source.user.id,
            canonical_user_id=owner_profile.canonical.user.id,
        )
    assert owner_profile_error.value.code == "owner_profile_merge_forbidden"


@pytest.mark.asyncio
async def test_canonical_profile_must_be_available_and_keep_an_active_card() -> None:
    inactive = _context()
    inactive.canonical.user.status = UserStatus.INACTIVE
    with pytest.raises(AppError) as inactive_error:
        await CustomerMergeService(
            cast(CustomerMergeRepository, RecordingMergeRepository(inactive))
        ).preview(
            _actor(),
            source_user_id=inactive.source.user.id,
            canonical_user_id=inactive.canonical.user.id,
        )
    assert inactive_error.value.code == "canonical_customer_unavailable"

    missing_card = _context()
    missing_card = LockedMergeContext(
        settings=missing_card.settings,
        source=missing_card.source,
        canonical=missing_card.canonical,
        source_sessions=missing_card.source_sessions,
        source_cards=missing_card.source_cards,
        canonical_card=None,
        source_rewards=missing_card.source_rewards,
        source_feedback=missing_card.source_feedback,
        source_route_lots=missing_card.source_route_lots,
        terminal_routes=missing_card.terminal_routes,
        route_timestamp_floor=missing_card.route_timestamp_floor,
    )
    with pytest.raises(AppError) as card_error:
        await CustomerMergeService(
            cast(CustomerMergeRepository, RecordingMergeRepository(missing_card))
        ).preview(
            _actor(),
            source_user_id=missing_card.source.user.id,
            canonical_user_id=missing_card.canonical.user.id,
        )
    assert card_error.value.code == "canonical_active_card_required"


@pytest.mark.asyncio
async def test_owner_confirm_rebinds_the_only_staff_profile() -> None:
    context = _context(source_staff_role=Role.STAFF)
    repository = RecordingMergeRepository(context)
    service = CustomerMergeService(cast(CustomerMergeRepository, repository))
    actor = _actor(Role.OWNER)
    preview = await service.preview(
        actor,
        source_user_id=context.source.user.id,
        canonical_user_id=context.canonical.user.id,
    )

    result = await service.confirm(
        actor,
        source_user_id=context.source.user.id,
        canonical_user_id=context.canonical.user.id,
        preview_hash=preview.preview_hash,
        reason="Сотрудник создал второй профиль",
        idempotency_key=str(uuid4()),
        now=NOW,
    )

    assert context.source.staff is not None
    assert context.source.staff.user_id == context.canonical.user.id
    assert result.merge.source_staff_rebound is True


@pytest.mark.asyncio
async def test_zero_stamp_progress_does_not_create_invalid_zero_transactions() -> None:
    context = _context()
    assert context.source.loyalty_state is not None
    context.source.loyalty_state.stamp_count = 0
    repository = RecordingMergeRepository(context)
    service = CustomerMergeService(cast(CustomerMergeRepository, repository))
    actor = _actor()
    preview = await service.preview(
        actor,
        source_user_id=context.source.user.id,
        canonical_user_id=context.canonical.user.id,
    )

    await service.confirm(
        actor,
        source_user_id=context.source.user.id,
        canonical_user_id=context.canonical.user.id,
        preview_hash=preview.preview_hash,
        reason="Нет штампов для переноса",
        idempotency_key=str(uuid4()),
        now=NOW,
    )

    assert not any(isinstance(item, StampTransaction) for item in repository.added)
