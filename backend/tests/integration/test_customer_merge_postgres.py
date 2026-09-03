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
from app.models.content import Venue
from app.models.customers import CustomerIdentity, CustomerMerge
from app.models.enums import (
    CardStatus,
    FeedbackCategory,
    FeedbackStatus,
    IdentityProvider,
    LoyaltyOperationType,
    OperationStatus,
    PermissionCode,
    PointAllocationType,
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
    RewardTemplate,
    StampTransaction,
    UserLoyaltyState,
)
from app.models.loyalty_v2 import (
    AccountMergeLotRoute,
    LoyaltyWallet,
    PointAllocation,
    PointLot,
)
from app.models.staff import FeedbackItem
from app.repositories.customer_merges import CustomerMergeRepository
from app.repositories.identity import IdentityRepository
from app.repositories.loyalty import LoyaltyRepository
from app.repositories.loyalty_v2 import PointLedgerRepository
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
        oldest.birthday_month = 1
        oldest.birthday_day = 1
        oldest.birthday_set_at = NOW - timedelta(days=100)
        canonical.birthday_month = 2
        canonical.birthday_day = 2
        canonical.birthday_set_at = NOW - timedelta(days=50)
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
        oldest_wallet = LoyaltyWallet(
            id=uuid4(), user_id=oldest.id, venue_id=None, balance_points=10, version=1
        )
        middle_wallet = LoyaltyWallet(
            id=uuid4(), user_id=middle.id, venue_id=None, balance_points=20, version=1
        )
        canonical_wallet = LoyaltyWallet(
            id=uuid4(), user_id=canonical.id, venue_id=None, balance_points=30, version=1
        )
        oldest_lot = PointLot(
            id=uuid4(),
            wallet_id=oldest_wallet.id,
            source_operation_id=historical_operation.id,
            source_venue_id=None,
            source_type=PointLotSourceType.ADMIN_ADJUSTMENT,
            initial_points=10,
            remaining_points=10,
            earned_at=NOW - timedelta(days=1),
            expires_at=None,
        )
        fully_spent_lot = PointLot(
            id=uuid4(),
            wallet_id=oldest_wallet.id,
            source_operation_id=historical_operation.id,
            source_venue_id=None,
            source_type=PointLotSourceType.ADMIN_ADJUSTMENT,
            initial_points=5,
            remaining_points=0,
            earned_at=NOW - timedelta(days=2),
            expires_at=None,
        )
        middle_lot = PointLot(
            id=uuid4(),
            wallet_id=middle_wallet.id,
            source_operation_id=None,
            source_venue_id=None,
            source_type=PointLotSourceType.OPENING_BALANCE,
            initial_points=20,
            remaining_points=20,
            earned_at=NOW - timedelta(days=3),
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
            earned_at=NOW - timedelta(days=4),
            expires_at=None,
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
        feedback = FeedbackItem(
            id=uuid4(),
            user_id=oldest.id,
            rating=5,
            category=FeedbackCategory.SERVICE,
            message="Move through the canonical chain",
            may_contact=True,
            status=FeedbackStatus.NEW,
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
                oldest_wallet,
                middle_wallet,
                canonical_wallet,
            ]
        )
        await session.flush()
        session.add_all(
            [
                historical_transaction,
                reward,
                feedback,
                oldest_lot,
                fully_spent_lot,
                middle_lot,
                canonical_lot,
            ]
        )
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
        assert first_preview.feedback_to_move == 1
        assert first_preview.birthday_conflict is False
        assert first_preview.birthday_resolution_required is False
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
        assert second_preview.feedback_to_move == 1
        assert second_preview.birthday_conflict is True
        assert second_preview.birthday_resolution_required is True
        second_key = str(uuid4())
        second = await service.confirm(
            actor,
            source_user_id=middle.id,
            canonical_user_id=canonical.id,
            preview_hash=second_preview.preview_hash,
            reason="Second link in a duplicate profile chain",
            idempotency_key=second_key,
            birthday_resolution="keep_canonical",
            # A caller-captured equal timestamp must still produce a globally
            # newer route than the first merge.
            now=NOW,
        )
        replay = await service.confirm(
            actor,
            source_user_id=middle.id,
            canonical_user_id=canonical.id,
            preview_hash=second_preview.preview_hash,
            reason="Second link in a duplicate profile chain",
            idempotency_key=second_key,
            birthday_resolution="keep_canonical",
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
        assert oldest_state.points_balance == 0
        assert middle_state.points_balance == 0
        assert oldest_wallet.balance_points == 0
        assert middle_wallet.balance_points == 0
        assert canonical_wallet.balance_points == 60
        assert oldest_wallet.version == 2
        assert middle_wallet.version == 3
        assert canonical_wallet.version == 2
        assert identity.user_id == canonical.id
        assert reward.user_id == canonical.id
        assert feedback.user_id == canonical.id
        assert customer_session.revoked_at == NOW
        assert first.merge.feedback_moved == 1
        assert second.merge.feedback_moved == 1
        assert first.merge.birthday_resolution == "use_source"
        assert second.merge.birthday_resolution == "keep_canonical"
        # The merged profiles retain their historical values. The canonical
        # profile only changes when the explicitly selected policy requires it.
        assert (oldest.birthday_month, oldest.birthday_day) == (1, 1)
        assert (middle.birthday_month, middle.birthday_day) == (1, 1)
        assert (canonical.birthday_month, canonical.birthday_day) == (2, 2)

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
        merge_allocations = list(
            await session.scalars(
                select(PointAllocation)
                .where(
                    PointAllocation.operation_id.in_(
                        [
                            first.merge.source_points_operation_id,
                            second.merge.source_points_operation_id,
                        ]
                    ),
                    PointAllocation.allocation_type == PointAllocationType.ACCOUNT_MERGE_DEBIT,
                )
                .order_by(PointAllocation.operation_id, PointAllocation.lot_id)
            )
        )
        first_allocations = [
            item
            for item in merge_allocations
            if item.operation_id == first.merge.source_points_operation_id
        ]
        second_allocations = [
            item
            for item in merge_allocations
            if item.operation_id == second.merge.source_points_operation_id
        ]
        assert [item.points for item in first_allocations] == [10]
        assert sorted(item.points for item in second_allocations) == [10, 20]

        merge_lots = list(
            await session.scalars(
                select(PointLot)
                .where(PointLot.source_type == PointLotSourceType.ACCOUNT_MERGE)
                .order_by(PointLot.earned_at, PointLot.id)
            )
        )
        relevant_merge_lots = [
            lot
            for lot in merge_lots
            if lot.source_operation_id
            in {
                first.merge.canonical_points_operation_id,
                second.merge.canonical_points_operation_id,
            }
        ]
        assert len(relevant_merge_lots) == 3
        assert sum(lot.remaining_points for lot in relevant_merge_lots) == 30
        assert {
            (lot.initial_points, lot.earned_at)
            for lot in relevant_merge_lots
            if lot.source_operation_id == second.merge.canonical_points_operation_id
        } == {
            (20, middle_lot.earned_at),
            (10, oldest_lot.earned_at),
        }

        routes = list(
            await session.scalars(
                select(AccountMergeLotRoute)
                .where(AccountMergeLotRoute.customer_merge_id.in_(merge_ids))
                .order_by(AccountMergeLotRoute.created_at, AccountMergeLotRoute.id)
            )
        )
        assert len(routes) == 5
        spent_routes = [route for route in routes if route.source_lot_id == fully_spent_lot.id]
        assert len(spent_routes) == 2
        assert spent_routes[0].customer_merge_id == first.merge.id
        assert spent_routes[0].destination_wallet_id == middle_wallet.id
        assert spent_routes[0].destination_lot_id is None
        assert spent_routes[1].customer_merge_id == second.merge.id
        assert spent_routes[1].destination_wallet_id == canonical_wallet.id
        assert spent_routes[1].destination_lot_id is None
        assert spent_routes[1].created_at > spent_routes[0].created_at
        terminal_spent = await PointLedgerRepository(session).latest_route(fully_spent_lot.id)
        assert terminal_spent is not None
        assert terminal_spent.wallet_id == canonical_wallet.id
        assert terminal_spent.lot_id is None
        terminal_positive = await PointLedgerRepository(session).latest_route(oldest_lot.id)
        assert terminal_positive is not None
        assert terminal_positive.wallet_id == canonical_wallet.id
        assert terminal_positive.lot_id is not None

        assert (
            sum(
                wallet.balance_points for wallet in (oldest_wallet, middle_wallet, canonical_wallet)
            )
            == canonical_state.points_balance
        )
        assert (
            sum(
                lot.remaining_points
                for lot in [
                    oldest_lot,
                    fully_spent_lot,
                    middle_lot,
                    canonical_lot,
                    *relevant_merge_lots,
                ]
            )
            == canonical_state.points_balance
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
        merge_audits = list(
            await session.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.event_type == "customer.merged",
                    AuditEvent.object_id.in_(merge_ids),
                )
                .order_by(AuditEvent.created_at, AuditEvent.id)
            )
        )
        assert [item.event_metadata["feedback_moved"] for item in merge_audits] == [1, 1]
        assert {item.event_metadata["birthday_resolution"] for item in merge_audits} == {
            "use_source",
            "keep_canonical",
        }
        for item in merge_audits:
            assert "birthday_month" not in item.event_metadata
            assert "birthday_day" not in item.event_metadata

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
        staff_history = await LoyaltyRepository(session).list_operations(
            user_id=canonical.id,
            actor_staff_id=None,
            page=1,
            page_size=100,
        )
        assert staff_history.total == history.total
        assert {item.id for item in staff_history.items} == {item.id for item in history.items}
    finally:
        await session.close()
        if outer_transaction.is_active:
            await outer_transaction.rollback()
        await connection.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_merge_preserves_separate_archived_wallet_scope() -> None:
    """Archived venue wallets remain valid ledger scopes during account merge."""

    engine = create_async_engine(_database_url())
    connection = await engine.connect()
    outer_transaction = await connection.begin()
    session = AsyncSession(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        marker = uuid4().hex
        settings = await session.scalar(select(LoyaltySettings).with_for_update())
        assert settings is not None
        venue = Venue(
            id=uuid4(),
            slug=f"archived-merge-{marker}",
            name="Archived merge venue",
            is_active=False,
            archived_at=NOW,
        )
        session.add(venue)
        settings.wallet_mode = WalletMode.SEPARATE
        settings.updated_at = NOW
        await session.flush()

        actor_user = _user(
            "Separate merge admin",
            telegram_id=7_200_000_000_000_000 + uuid4().int % 10**12,
        )
        source = _user(
            "Separate source",
            telegram_id=7_300_000_000_000_000 + uuid4().int % 10**12,
        )
        canonical = _user("Separate canonical")
        actor_staff = StaffMember(
            id=uuid4(),
            user_id=actor_user.id,
            role=Role.ADMIN,
            is_active=True,
        )
        source_state = _state(source.id, points=11, stamps=0)
        canonical_state = _state(canonical.id, points=7, stamps=0)
        source_wallet = LoyaltyWallet(
            id=uuid4(), user_id=source.id, venue_id=venue.id, balance_points=11, version=4
        )
        canonical_wallet = LoyaltyWallet(
            id=uuid4(), user_id=canonical.id, venue_id=venue.id, balance_points=7, version=6
        )
        source_lot = PointLot(
            id=uuid4(),
            wallet_id=source_wallet.id,
            source_operation_id=None,
            source_venue_id=None,
            source_type=PointLotSourceType.OPENING_BALANCE,
            initial_points=11,
            remaining_points=11,
            earned_at=NOW - timedelta(days=20),
            expires_at=None,
        )
        canonical_lot = PointLot(
            id=uuid4(),
            wallet_id=canonical_wallet.id,
            source_operation_id=None,
            source_venue_id=None,
            source_type=PointLotSourceType.OPENING_BALANCE,
            initial_points=7,
            remaining_points=7,
            earned_at=NOW - timedelta(days=10),
            expires_at=None,
        )

        session.add_all([actor_user, source, canonical])
        await session.flush()
        session.add(actor_staff)
        await session.flush()
        session.add_all(
            [
                source_state,
                canonical_state,
                _card(source.id, "separate-source"),
                _card(canonical.id, "separate-canonical"),
                source_wallet,
                canonical_wallet,
            ]
        )
        await session.flush()
        session.add_all([source_lot, canonical_lot])
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
        preview = await service.preview(
            actor,
            source_user_id=source.id,
            canonical_user_id=canonical.id,
        )
        result = await service.confirm(
            actor,
            source_user_id=source.id,
            canonical_user_id=canonical.id,
            preview_hash=preview.preview_hash,
            reason="Preserve an archived venue wallet scope",
            idempotency_key=f"separate-archived:{marker}",
            now=NOW + timedelta(hours=1),
        )

        assert result.merge.points_transferred == 11
        assert source_state.points_balance == 0
        assert canonical_state.points_balance == 18
        assert source_wallet.balance_points == 0
        assert source_wallet.version == 5
        assert canonical_wallet.balance_points == 18
        assert canonical_wallet.version == 7
        assert venue.is_active is False
        assert venue.archived_at == NOW
        assert (
            await session.scalar(
                select(func.count())
                .select_from(LoyaltyWallet)
                .where(
                    LoyaltyWallet.user_id == canonical.id,
                    LoyaltyWallet.venue_id.is_(None),
                )
            )
            == 0
        )
        destination_lot = await session.scalar(
            select(PointLot).where(
                PointLot.source_operation_id == result.merge.canonical_points_operation_id,
                PointLot.source_type == PointLotSourceType.ACCOUNT_MERGE,
            )
        )
        assert destination_lot is not None
        assert destination_lot.wallet_id == canonical_wallet.id
        assert destination_lot.remaining_points == 11
        assert destination_lot.earned_at == source_lot.earned_at
        terminal = await PointLedgerRepository(session).latest_route(source_lot.id)
        assert terminal is not None
        assert terminal.wallet_id == canonical_wallet.id
        assert terminal.lot_id == destination_lot.id
    finally:
        await session.close()
        if outer_transaction.is_active:
            await outer_transaction.rollback()
        await connection.close()
        await engine.dispose()
