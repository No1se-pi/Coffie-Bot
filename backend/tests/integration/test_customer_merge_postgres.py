from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

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
    RewardStatus,
    RewardType,
    Role,
    UserStatus,
)
from app.models.loyalty import (
    LoyaltyOperation,
    PointTransaction,
    Reward,
    RewardTemplate,
    StampTransaction,
    UserLoyaltyState,
)
from app.repositories.customer_merges import CustomerMergeRepository
from app.repositories.identity import IdentityRepository
from app.security.rbac import Actor
from app.services.customer_merges import CustomerMergeService

NOW = datetime(2026, 8, 24, 12, tzinfo=UTC)


def _database_url() -> str:
    value = os.getenv("DATABASE_URL")
    if not value:
        pytest.skip("DATABASE_URL is required for PostgreSQL integration tests")
    if not value.startswith("postgresql+asyncpg://"):
        pytest.skip("customer merge integration test requires async PostgreSQL")
    return value


def _user(name: str, *, telegram_id: int | None = None) -> User:
    return User(
        id=uuid4(),
        telegram_id=telegram_id,
        first_name=name,
        status=UserStatus.ACTIVE,
    )


def _state(user_id: UUID, *, points: int, stamps: int) -> UserLoyaltyState:
    return UserLoyaltyState(
        id=uuid4(),
        user_id=user_id,
        points_balance=points,
        visit_streak=0,
        allowed_misses_used=0,
        stamp_count=stamps,
        version=1,
    )


def _card(user_id: UUID, marker: str) -> UserCard:
    unique = uuid4().hex
    return UserCard(
        id=uuid4(),
        user_id=user_id,
        qr_token=f"merge-{marker}-{unique}",
        short_code=unique[:16],
        status=CardStatus.ACTIVE,
    )


@pytest.mark.asyncio
async def test_merge_chain_preserves_lineage_history_and_mutable_ownership() -> None:
    """Exercise real constraints, flush ordering, journals, and recursive history."""

    engine = create_async_engine(_database_url())
    connection = await engine.connect()
    outer_transaction = await connection.begin()
    session = AsyncSession(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        template_id = await session.scalar(select(RewardTemplate.id).limit(1))
        assert template_id is not None

        marker = uuid4().hex
        actor_user = _user("Merge admin", telegram_id=7_000_000_000_000_000 + uuid4().int % 10**12)
        actor_staff = StaffMember(
            id=uuid4(),
            user_id=actor_user.id,
            role=Role.ADMIN,
            is_active=True,
        )
        oldest = _user("Oldest", telegram_id=7_100_000_000_000_000 + uuid4().int % 10**12)
        middle = _user("Middle")
        canonical = _user("Canonical")
        oldest_state = _state(oldest.id, points=10, stamps=2)
        middle_state = _state(middle.id, points=20, stamps=3)
        canonical_state = _state(canonical.id, points=30, stamps=4)
        historical_operation = LoyaltyOperation(
            id=uuid4(),
            user_id=oldest.id,
            actor_user_id=actor_user.id,
            actor_staff_id=actor_staff.id,
            operation_type=LoyaltyOperationType.ADMIN_ADJUSTMENT,
            status=OperationStatus.COMMITTED,
            idempotency_key=f"merge-history:{marker}",
            request_hash="f" * 64,
            points_delta=10,
            balance_before=0,
            balance_after=10,
            reason="Historical balance",
            occurred_at=NOW - timedelta(days=1),
        )
        historical_transaction = PointTransaction(
            id=uuid4(),
            operation_id=historical_operation.id,
            user_id=oldest.id,
            delta=10,
            balance_before=0,
            balance_after=10,
            created_at=NOW - timedelta(days=1),
        )
        identity = CustomerIdentity(
            id=uuid4(),
            user_id=oldest.id,
            provider=IdentityProvider.TELEGRAM,
            subject=str(oldest.telegram_id),
            is_verified=True,
            verified_at=NOW,
            provider_metadata={},
        )
        customer_session = Session(
            id=uuid4(),
            user_id=oldest.id,
            token_hash=uuid4().hex + uuid4().hex,
            created_at=NOW,
            expires_at=NOW + timedelta(days=1),
        )
        reward = Reward(
            id=uuid4(),
            user_id=oldest.id,
            template_id=template_id,
            source_operation_id=historical_operation.id,
            name="Merge reward",
            description="Must remain redeemable on the canonical profile",
            reward_type=RewardType.TEXT,
            status=RewardStatus.ACTIVE,
        )
        # These fixtures use FK ids rather than ORM relationships. Flush the
        # principals first so the test setup itself does not rely on unit-of-work
        # relationship ordering that production aggregate creation never needs.
        session.add_all([actor_user, oldest, middle, canonical])
        await session.flush()
        session.add(actor_staff)
        await session.flush()
        session.add_all(
            [
                oldest_state,
                middle_state,
                canonical_state,
                _card(oldest.id, "oldest"),
                _card(middle.id, "middle"),
                _card(canonical.id, "canonical"),
                historical_operation,
                identity,
                customer_session,
            ]
        )
        await session.flush()
        session.add_all([historical_transaction, reward])
        await session.flush()

        actor = Actor(
            user_id=actor_user.id,
            telegram_id=actor_user.telegram_id or 0,
            session_id=uuid4(),
            role=Role.ADMIN,
            staff_member_id=actor_staff.id,
            permissions=frozenset({PermissionCode.ADMIN_USERS_MANAGE}),
        )
        service = CustomerMergeService(CustomerMergeRepository(session))

        first_preview = await service.preview(
            actor,
            source_user_id=oldest.id,
            canonical_user_id=middle.id,
        )
        first = await service.confirm(
            actor,
            source_user_id=oldest.id,
            canonical_user_id=middle.id,
            preview_hash=first_preview.preview_hash,
            reason="First link in a duplicate profile chain",
            idempotency_key=str(uuid4()),
            now=NOW,
        )
        second_preview = await service.preview(
            actor,
            source_user_id=middle.id,
            canonical_user_id=canonical.id,
        )
        second_key = str(uuid4())
        second = await service.confirm(
            actor,
            source_user_id=middle.id,
            canonical_user_id=canonical.id,
            preview_hash=second_preview.preview_hash,
            reason="Second link in a duplicate profile chain",
            idempotency_key=second_key,
            now=NOW + timedelta(seconds=1),
        )
        replay = await service.confirm(
            actor,
            source_user_id=middle.id,
            canonical_user_id=canonical.id,
            preview_hash=second_preview.preview_hash,
            reason="Second link in a duplicate profile chain",
            idempotency_key=second_key,
            now=NOW + timedelta(seconds=2),
        )

        assert replay.idempotent_replay is True
        assert replay.merge.id == second.merge.id
        assert first.merge.canonical_user_id == middle.id
        assert oldest.status is UserStatus.MERGED
        assert oldest.merged_into_user_id == middle.id
        assert middle.status is UserStatus.MERGED
        assert middle.merged_into_user_id == canonical.id
        assert canonical.status is UserStatus.ACTIVE
        assert canonical_state.points_balance == 60
        assert canonical_state.stamp_count == 9
        assert identity.user_id == canonical.id
        assert reward.user_id == canonical.id
        assert customer_session.revoked_at == NOW

        active_card_owner_ids = set(
            await session.scalars(
                select(UserCard.user_id).where(
                    UserCard.user_id.in_([oldest.id, middle.id, canonical.id]),
                    UserCard.status == CardStatus.ACTIVE,
                )
            )
        )
        assert active_card_owner_ids == {canonical.id}
        merge_ids = {first.merge.id, second.merge.id}
        operation_ids = {
            first.merge.source_points_operation_id,
            first.merge.canonical_points_operation_id,
            second.merge.source_points_operation_id,
            second.merge.canonical_points_operation_id,
        }
        assert (
            await session.scalar(
                select(func.count())
                .select_from(CustomerMerge)
                .where(CustomerMerge.id.in_(merge_ids))
            )
            == 2
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(LoyaltyOperation)
                .where(
                    LoyaltyOperation.id.in_(operation_ids),
                    LoyaltyOperation.operation_type.in_(
                        [
                            LoyaltyOperationType.ACCOUNT_MERGE_DEBIT,
                            LoyaltyOperationType.ACCOUNT_MERGE_CREDIT,
                        ]
                    ),
                )
            )
            == 4
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(StampTransaction)
                .where(StampTransaction.operation_id.in_(operation_ids))
            )
            == 4
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.event_type == "customer.merged",
                    AuditEvent.object_id.in_(merge_ids),
                )
            )
            == 2
        )

        history = await IdentityRepository(session).list_history(
            user_id=canonical.id,
            operation_type=None,
            page=1,
            page_size=100,
        )
        assert history.total == 5
        assert historical_operation.id in {item.id for item in history.items}
        assert {item.user_id for item in history.items} == {
            oldest.id,
            middle.id,
            canonical.id,
        }
    finally:
        await session.close()
        if outer_transaction.is_active:
            await outer_transaction.rollback()
        await connection.close()
        await engine.dispose()
