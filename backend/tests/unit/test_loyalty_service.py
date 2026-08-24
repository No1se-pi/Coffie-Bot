from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import TracebackType
from typing import cast
from uuid import UUID, uuid4

import pytest

from app.core.errors import AppError
from app.models.access import User
from app.models.audit import AuditEvent
from app.models.cards import UserCard
from app.models.content import MenuItem
from app.models.delivery import NotificationOutbox
from app.models.enums import (
    CardStatus,
    LoyaltyOperationType,
    LoyaltyProgram,
    OperationStatus,
    PermissionCode,
    RewardType,
    Role,
    RoundingMode,
    UserStatus,
)
from app.models.loyalty import (
    LoyaltyOperation,
    LoyaltySettings,
    PointTransaction,
    Reward,
    RewardTemplate,
    StampTransaction,
    UserLoyaltyState,
    Visit,
)
from app.repositories.loyalty import (
    LoyaltyContext,
    OperationArtifacts,
    OperationPage,
    RewardPage,
)
from app.security.rbac import Actor
from app.services.loyalty import LoyaltyRepositoryPort, LoyaltyService

NOW = datetime(2026, 7, 27, 12, tzinfo=UTC)


class FakeTransaction:
    def __init__(self, repository: FakeRepository) -> None:
        self.repository = repository

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.repository.release_current_lock()


class FakeRepository:
    def __init__(self, context: LoyaltyContext) -> None:
        self.context = context
        self.operations: dict[tuple[LoyaltyOperationType, str], LoyaltyOperation] = {}
        self.audits: dict[UUID, AuditEvent] = {}
        self.point_transactions: list[PointTransaction] = []
        self.visits: list[Visit] = []
        self.stamp_transactions: list[StampTransaction] = []
        self.rewards: list[Reward] = []
        self.reward_templates: dict[UUID, RewardTemplate] = {}
        self.menu_items: dict[UUID, MenuItem] = {}
        self.outboxes: dict[str, NotificationOutbox] = {}
        self.cards: dict[UUID, UserCard] = {context.card.id: context.card}
        self.revoked_session_calls = 0
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._held_locks: dict[asyncio.Task[object], asyncio.Lock] = {}
        self.for_update_calls: list[bool] = []

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self)

    async def acquire_idempotency_lock(self, namespace: str, key: str) -> None:
        lock = self._locks.setdefault((namespace, key), asyncio.Lock())
        await lock.acquire()
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("test must run in an asyncio task")
        self._held_locks[cast(asyncio.Task[object], task)] = lock

    def release_current_lock(self) -> None:
        task = asyncio.current_task()
        if task is None:
            return
        lock = self._held_locks.pop(cast(asyncio.Task[object], task), None)
        if lock is not None:
            lock.release()

    async def get_operation_by_idempotency(
        self,
        *,
        operation_type: LoyaltyOperationType,
        idempotency_key: str,
    ) -> LoyaltyOperation | None:
        return self.operations.get((operation_type, idempotency_key))

    async def lookup_card(
        self,
        *,
        qr_token: str | None,
        short_code: str | None,
        phone: str | None,
    ) -> LoyaltyContext | None:
        if (
            qr_token == self.context.card.qr_token
            or short_code == self.context.card.short_code
            or phone == "+79991234567"
        ):
            return self.context
        return None

    async def list_rewards(self, **_kwargs: object) -> RewardPage:
        return RewardPage(items=[], total=0)

    async def list_operations(self, **_kwargs: object) -> OperationPage:
        return OperationPage(items=[], total=0)

    async def get_context(
        self,
        user_id: UUID,
        *,
        for_update: bool,
    ) -> LoyaltyContext | None:
        self.for_update_calls.append(for_update)
        return self.context if self.context.user.id == user_id else None

    async def accrued_points_between(
        self,
        *,
        user_id: UUID,
        started_at: object,
        ended_at: object,
    ) -> int:
        assert user_id == self.context.user.id
        assert started_at != ended_at
        return 0

    async def count_visits(self, *, user_id: UUID, business_date: object) -> int:
        return sum(
            visit.user_id == user_id and visit.business_date == business_date
            for visit in self.visits
        )

    async def get_reward_template(self, template_id: UUID) -> RewardTemplate | None:
        return self.reward_templates.get(template_id)

    async def get_menu_item(self, item_id: UUID, *, for_update: bool) -> MenuItem | None:
        assert for_update is True
        return self.menu_items.get(item_id)

    async def get_reward_by_source_operation(self, operation_id: UUID) -> Reward | None:
        return next(
            (reward for reward in self.rewards if reward.source_operation_id == operation_id),
            None,
        )

    def add_all(self, objects: list[object]) -> None:
        for item in objects:
            if isinstance(item, LoyaltyOperation):
                self.operations[(item.operation_type, item.idempotency_key)] = item
            elif isinstance(item, PointTransaction):
                self.point_transactions.append(item)
            elif isinstance(item, Visit):
                self.visits.append(item)
            elif isinstance(item, StampTransaction):
                self.stamp_transactions.append(item)
            elif isinstance(item, Reward):
                self.rewards.append(item)
            elif isinstance(item, NotificationOutbox):
                self.outboxes[item.idempotency_key] = item
            elif isinstance(item, UserCard):
                self.cards[item.id] = item
            elif isinstance(item, AuditEvent) and item.object_id is not None:
                self.audits[item.object_id] = item

    async def flush(self) -> None:
        return None

    async def get_operation_artifacts(self, operation_id: UUID) -> OperationArtifacts:
        return OperationArtifacts(
            visit=next(
                (visit for visit in self.visits if visit.operation_id == operation_id),
                None,
            ),
            stamp=next(
                (
                    transaction
                    for transaction in self.stamp_transactions
                    if transaction.operation_id == operation_id
                ),
                None,
            ),
            rewards=tuple(
                reward for reward in self.rewards if reward.source_operation_id == operation_id
            ),
            audit_event=self.audits.get(operation_id),
        )

    async def get_outbox_by_key(
        self,
        idempotency_key: str,
    ) -> NotificationOutbox | None:
        return self.outboxes.get(idempotency_key)

    async def revoke_user_sessions(
        self,
        *,
        user_id: UUID,
        now: object,
        reason: str,
    ) -> None:
        assert user_id == self.context.user.id
        assert now is not None
        assert reason
        self.revoked_session_calls += 1

    async def get_card(self, card_id: UUID) -> UserCard | None:
        return self.cards.get(card_id)


def loyalty_context(
    *,
    large_operation_requires_approval: bool = False,
    points_balance: int = 10,
) -> LoyaltyContext:
    user_id = uuid4()
    user = User(
        id=user_id,
        telegram_id=1001,
        first_name="Клиент",
        last_name="Тестовый",
        status=UserStatus.ACTIVE,
    )
    card = UserCard(
        id=uuid4(),
        user_id=user_id,
        qr_token="opaque-card-token-for-test",
        short_code="TEST1234",
        status=CardStatus.ACTIVE,
    )
    state = UserLoyaltyState(
        id=uuid4(),
        user_id=user_id,
        points_balance=points_balance,
        visit_streak=0,
        allowed_misses_used=0,
        stamp_count=0,
        version=1,
    )
    settings = LoyaltySettings(
        id=uuid4(),
        singleton_key="default",
        points_enabled=True,
        minor_units_per_point=1_000,
        minimum_purchase_minor=0,
        maximum_purchase_minor=1_000_000,
        rounding_mode=RoundingMode.FLOOR,
        redemption_minor_units_per_point=100,
        minimum_redemption_points=1,
        maximum_redemption_percent=50,
        daily_accrual_limit_points=None,
        operation_accrual_limit_points=None,
        large_operation_threshold_minor=(20_000 if large_operation_requires_approval else None),
        large_operation_requires_approval=large_operation_requires_approval,
        visits_enabled=True,
        visit_required_count=5,
        visits_must_be_consecutive=True,
        visit_daily_limit=1,
        visit_allowed_misses=0,
        visit_reset_on_miss=True,
        visit_restart_cycle=True,
        stamps_enabled=True,
        stamp_required_count=9,
        stamps_per_purchase=1,
        stamp_operation_limit=10,
        reset_stamps_after_reward=True,
        timezone="Europe/Moscow",
        business_day_boundary_minutes=240,
    )
    return LoyaltyContext(user=user, card=card, state=state, settings=settings)


def staff_actor(*permissions: PermissionCode) -> Actor:
    return Actor(
        user_id=uuid4(),
        telegram_id=9001,
        session_id=uuid4(),
        role=Role.STAFF,
        staff_member_id=uuid4(),
        permissions=frozenset(permissions),
    )


def customer_actor(user_id: UUID) -> Actor:
    return Actor(
        user_id=user_id,
        telegram_id=1001,
        session_id=uuid4(),
        role=Role.CUSTOMER,
        staff_member_id=None,
        permissions=frozenset(),
    )


@pytest.mark.asyncio
async def test_lookup_card_returns_operational_customer_summary() -> None:
    context = loyalty_context(points_balance=37)
    repository = FakeRepository(context)
    service = LoyaltyService(cast(LoyaltyRepositoryPort, repository))

    result = await service.lookup_card(
        staff_actor(PermissionCode.CARD_LOOKUP),
        qr_token=context.card.qr_token,
        short_code=None,
    )

    assert result.user_id == context.user.id
    assert result.points_balance == 37
    assert result.currency_name == context.settings.currency_name
    assert result.active_rewards == ()
    assert result.recent_operations == ()


@pytest.mark.asyncio
async def test_lookup_card_normalizes_phone_before_repository_query() -> None:
    context = loyalty_context(points_balance=37)
    repository = FakeRepository(context)
    service = LoyaltyService(cast(LoyaltyRepositoryPort, repository))

    result = await service.lookup_card(
        staff_actor(PermissionCode.CARD_LOOKUP),
        qr_token=None,
        short_code=None,
        phone="8 (999) 123-45-67",
    )

    assert result.user_id == context.user.id


@pytest.mark.asyncio
async def test_menu_item_purchase_deducts_points_and_issues_opaque_qr_idempotently() -> None:
    context = loyalty_context(points_balance=120)
    repository = FakeRepository(context)
    template = RewardTemplate(
        id=uuid4(),
        name="Капучино",
        description="Бесплатный капучино",
        reward_type=RewardType.FREE_PRODUCT,
        source_program=LoyaltyProgram.POINTS,
        value_int=80,
        validity_days=30,
        is_active=True,
    )
    item = MenuItem(
        id=uuid4(),
        category_id=uuid4(),
        name="Капучино",
        price_minor=29_000,
        points_price=80,
        points_reward_template_id=template.id,
        labels=[],
        is_available=True,
        is_visible=True,
        sort_order=0,
    )
    repository.reward_templates[template.id] = template
    repository.menu_items[item.id] = item
    service = LoyaltyService(cast(LoyaltyRepositoryPort, repository))
    actor = customer_actor(context.user.id)
    key = str(uuid4())

    first = await service.purchase_menu_item_with_points(
        actor, item_id=item.id, idempotency_key=key, now=NOW
    )
    replay = await service.purchase_menu_item_with_points(
        actor, item_id=item.id, idempotency_key=key, now=NOW
    )

    assert context.state.points_balance == 40
    assert first.reward_id == replay.reward_id
    assert replay.idempotent_replay is True
    assert first.qr_payload.startswith("coffee-reward:v1:")
    assert str(context.user.telegram_id) not in first.qr_payload
    assert len(repository.point_transactions) == 1


@pytest.mark.asyncio
async def test_same_idempotency_key_replays_without_second_balance_change() -> None:
    context = loyalty_context()
    repository = FakeRepository(context)
    service = LoyaltyService(cast(LoyaltyRepositoryPort, repository))
    actor = staff_actor(PermissionCode.POINTS_ACCRUE)
    key = str(uuid4())

    first = await service.confirm_accrual(
        actor,
        user_id=context.user.id,
        purchase_amount_minor=20_000,
        idempotency_key=key,
    )
    replay = await service.confirm_accrual(
        actor,
        user_id=context.user.id,
        purchase_amount_minor=20_000,
        idempotency_key=key,
    )

    assert first.operation_id == replay.operation_id
    assert first.idempotent_replay is False
    assert replay.idempotent_replay is True
    assert context.state.points_balance == 30
    assert len(repository.point_transactions) == 1


@pytest.mark.asyncio
async def test_purchase_commits_points_stamps_and_one_automatic_daily_visit() -> None:
    context = loyalty_context()
    repository = FakeRepository(context)
    service = LoyaltyService(cast(LoyaltyRepositoryPort, repository))
    actor = staff_actor(PermissionCode.POINTS_ACCRUE, PermissionCode.STAMPS_ADD)
    current_time = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
    key = str(uuid4())

    preview = await service.preview_purchase(
        actor,
        user_id=context.user.id,
        purchase_amount_minor=20_000,
        stamps_to_add=2,
        now=current_time,
    )
    first = await service.confirm_purchase(
        actor,
        user_id=context.user.id,
        purchase_amount_minor=20_000,
        stamps_to_add=2,
        idempotency_key=key,
        now=current_time,
    )
    replay = await service.confirm_purchase(
        actor,
        user_id=context.user.id,
        purchase_amount_minor=20_000,
        stamps_to_add=2,
        idempotency_key=key,
        now=current_time,
    )

    assert preview.visit_will_be_recorded is True
    assert preview.projected_visit_streak == 1
    assert preview.projected_stamps_after == 2
    assert first.points_delta == 20
    assert first.streak_after == 1
    assert first.stamps_after == 2
    assert replay.idempotent_replay is True
    assert context.state.points_balance == 30
    assert context.state.visit_streak == 1
    assert context.state.stamp_count == 2
    assert context.state.version == 2
    assert len(repository.point_transactions) == 1
    assert len(repository.visits) == 1
    assert len(repository.stamp_transactions) == 1

    second = await service.confirm_purchase(
        actor,
        user_id=context.user.id,
        purchase_amount_minor=10_000,
        stamps_to_add=1,
        idempotency_key=str(uuid4()),
        now=current_time,
    )

    assert second.streak_after is None
    assert second.stamps_after == 3
    assert context.state.points_balance == 40
    assert context.state.visit_streak == 1
    assert len(repository.visits) == 1
    assert len(repository.point_transactions) == 2


@pytest.mark.asyncio
async def test_purchase_issues_visit_and_stamp_rewards_at_both_goals() -> None:
    context = loyalty_context()
    context.state.visit_streak = 4
    context.state.last_visit_business_date = datetime(2026, 7, 25, tzinfo=UTC).date()
    context.state.stamp_count = 8
    visit_template = RewardTemplate(
        id=uuid4(),
        name="Награда за посещения",
        description="Тестовая награда",
        reward_type=RewardType.FREE_PRODUCT,
        source_program=LoyaltyProgram.VISITS,
        validity_days=7,
        is_active=True,
    )
    stamp_template = RewardTemplate(
        id=uuid4(),
        name="Награда за штампы",
        description="Тестовая награда",
        reward_type=RewardType.FREE_PRODUCT,
        source_program=LoyaltyProgram.STAMPS,
        validity_days=30,
        is_active=True,
    )
    context.settings.visit_reward_template_id = visit_template.id
    context.settings.stamp_reward_template_id = stamp_template.id
    repository = FakeRepository(context)
    repository.reward_templates = {
        visit_template.id: visit_template,
        stamp_template.id: stamp_template,
    }
    service = LoyaltyService(cast(LoyaltyRepositoryPort, repository))

    result = await service.confirm_purchase(
        staff_actor(PermissionCode.POINTS_ACCRUE, PermissionCode.STAMPS_ADD),
        user_id=context.user.id,
        purchase_amount_minor=10_000,
        stamps_to_add=1,
        idempotency_key=str(uuid4()),
        now=datetime(2026, 7, 26, 10, 0, tzinfo=UTC),
    )

    assert context.state.visit_streak == 0
    assert context.state.stamp_count == 0
    assert len(result.reward_ids) == 2
    assert {reward.template_id for reward in repository.rewards} == {
        visit_template.id,
        stamp_template.id,
    }
    assert all(
        reward.qr_payload is not None and reward.qr_payload.startswith("coffee-reward:v1:")
        for reward in repository.rewards
    )
    assert len({reward.qr_payload for reward in repository.rewards}) == 2


@pytest.mark.asyncio
async def test_visit_goal_awards_points_atomically_without_qr_reward() -> None:
    context = loyalty_context(points_balance=10)
    context.state.visit_streak = 4
    context.state.last_visit_business_date = datetime(2026, 7, 26, tzinfo=UTC).date()
    template = RewardTemplate(
        id=uuid4(),
        name="25 баллов",
        description="Автоматический бонус",
        reward_type=RewardType.POINTS,
        source_program=LoyaltyProgram.VISITS,
        value_int=25,
        is_active=True,
    )
    context.settings.visit_reward_template_id = template.id
    repository = FakeRepository(context)
    repository.reward_templates[template.id] = template
    service = LoyaltyService(cast(LoyaltyRepositoryPort, repository))

    result = await service.mark_visit(
        staff_actor(PermissionCode.VISITS_MARK),
        user_id=context.user.id,
        idempotency_key=str(uuid4()),
        now=NOW,
    )

    assert result.points_delta == 25
    assert result.balance_before == 10
    assert result.balance_after == 35
    assert result.reward_ids == ()
    assert context.state.points_balance == 35
    assert len(repository.rewards) == 0
    assert len(repository.point_transactions) == 1
    assert repository.point_transactions[0].delta == 25
    operation = next(iter(repository.operations.values()))
    assert operation.reward_bonus_points == 25


@pytest.mark.asyncio
async def test_stamp_points_reward_multiplies_for_each_completed_cycle() -> None:
    context = loyalty_context(points_balance=10)
    context.state.stamp_count = 8
    template = RewardTemplate(
        id=uuid4(),
        name="15 баллов",
        description="Автоматический бонус",
        reward_type=RewardType.POINTS,
        source_program=LoyaltyProgram.STAMPS,
        value_int=15,
        is_active=True,
    )
    context.settings.stamp_reward_template_id = template.id
    repository = FakeRepository(context)
    repository.reward_templates[template.id] = template
    service = LoyaltyService(cast(LoyaltyRepositoryPort, repository))

    result = await service.add_stamps(
        staff_actor(PermissionCode.STAMPS_ADD),
        user_id=context.user.id,
        stamps_to_add=10,
        idempotency_key=str(uuid4()),
        now=NOW,
    )

    assert result.points_delta == 30
    assert result.stamps_after == 0
    assert context.state.points_balance == 40
    assert len(repository.point_transactions) == 1
    assert repository.point_transactions[0].delta == 30
    assert repository.stamp_transactions[0].issued_reward_id is None


@pytest.mark.asyncio
async def test_purchase_combines_accrual_and_both_point_rewards_once() -> None:
    context = loyalty_context(points_balance=10)
    context.state.visit_streak = 4
    context.state.last_visit_business_date = datetime(2026, 7, 26, tzinfo=UTC).date()
    context.state.stamp_count = 8
    visit_template = RewardTemplate(
        id=uuid4(),
        name="20 баллов",
        description="За серию",
        reward_type=RewardType.POINTS,
        source_program=LoyaltyProgram.VISITS,
        value_int=20,
        is_active=True,
    )
    stamp_template = RewardTemplate(
        id=uuid4(),
        name="30 баллов",
        description="За штампы",
        reward_type=RewardType.POINTS,
        source_program=LoyaltyProgram.STAMPS,
        value_int=30,
        is_active=True,
    )
    context.settings.visit_reward_template_id = visit_template.id
    context.settings.stamp_reward_template_id = stamp_template.id
    repository = FakeRepository(context)
    repository.reward_templates = {
        visit_template.id: visit_template,
        stamp_template.id: stamp_template,
    }
    service = LoyaltyService(cast(LoyaltyRepositoryPort, repository))
    actor = staff_actor(PermissionCode.POINTS_ACCRUE, PermissionCode.STAMPS_ADD)
    key = str(uuid4())

    preview = await service.preview_purchase(
        actor,
        user_id=context.user.id,
        purchase_amount_minor=10_000,
        stamps_to_add=1,
        now=NOW,
    )
    first = await service.confirm_purchase(
        actor,
        user_id=context.user.id,
        purchase_amount_minor=10_000,
        stamps_to_add=1,
        idempotency_key=key,
        now=NOW,
    )
    replay = await service.confirm_purchase(
        actor,
        user_id=context.user.id,
        purchase_amount_minor=10_000,
        stamps_to_add=1,
        idempotency_key=key,
        now=NOW,
    )

    assert preview.awarded_points == 10
    assert preview.reward_bonus_points == 50
    assert preview.projected_balance_after == 70
    assert first.points_delta == 60
    assert first.balance_after == 70
    assert replay.idempotent_replay is True
    assert context.state.points_balance == 70
    assert len(repository.point_transactions) == 1
    assert repository.point_transactions[0].delta == 60
    operation = repository.operations[(LoyaltyOperationType.PURCHASE_ACCRUAL, key)]
    assert operation.reward_bonus_points == 50
    assert repository.rewards == []


@pytest.mark.asyncio
async def test_runtime_rejects_points_reward_when_points_program_is_disabled() -> None:
    context = loyalty_context()
    context.settings.points_enabled = False
    context.state.visit_streak = 4
    context.state.last_visit_business_date = datetime(2026, 7, 26, tzinfo=UTC).date()
    template = RewardTemplate(
        id=uuid4(),
        name="25 баллов",
        description="Автоматический бонус",
        reward_type=RewardType.POINTS,
        source_program=LoyaltyProgram.VISITS,
        value_int=25,
        is_active=True,
    )
    context.settings.visit_reward_template_id = template.id
    repository = FakeRepository(context)
    repository.reward_templates[template.id] = template
    service = LoyaltyService(cast(LoyaltyRepositoryPort, repository))

    with pytest.raises(AppError) as error:
        await service.mark_visit(
            staff_actor(PermissionCode.VISITS_MARK),
            user_id=context.user.id,
            idempotency_key=str(uuid4()),
            now=NOW,
        )

    assert error.value.status_code == 409
    assert context.state.points_balance == 10
    assert repository.point_transactions == []


@pytest.mark.asyncio
async def test_purchase_requires_stamp_permission_only_when_stamps_are_added() -> None:
    context = loyalty_context()
    repository = FakeRepository(context)
    service = LoyaltyService(cast(LoyaltyRepositoryPort, repository))
    actor = staff_actor(PermissionCode.POINTS_ACCRUE)

    preview = await service.preview_purchase(
        actor,
        user_id=context.user.id,
        purchase_amount_minor=10_000,
        stamps_to_add=0,
    )
    assert preview.stamps_to_add == 0

    with pytest.raises(AppError) as error:
        await service.confirm_purchase(
            actor,
            user_id=context.user.id,
            purchase_amount_minor=10_000,
            stamps_to_add=1,
            idempotency_key=str(uuid4()),
        )

    assert error.value.status_code == 403
    assert repository.operations == {}


@pytest.mark.asyncio
async def test_pending_purchase_mutates_none_of_the_loyalty_snapshots() -> None:
    context = loyalty_context(large_operation_requires_approval=True)
    repository = FakeRepository(context)
    service = LoyaltyService(cast(LoyaltyRepositoryPort, repository))

    result = await service.confirm_purchase(
        staff_actor(PermissionCode.POINTS_ACCRUE, PermissionCode.STAMPS_ADD),
        user_id=context.user.id,
        purchase_amount_minor=20_000,
        stamps_to_add=1,
        idempotency_key=str(uuid4()),
    )

    assert result.operation_status is OperationStatus.PENDING
    assert context.state.points_balance == 10
    assert context.state.visit_streak == 0
    assert context.state.stamp_count == 0
    assert context.state.version == 1
    assert repository.point_transactions == []
    assert repository.visits == []
    assert repository.stamp_transactions == []


@pytest.mark.asyncio
async def test_same_key_with_different_payload_is_conflict() -> None:
    context = loyalty_context()
    repository = FakeRepository(context)
    service = LoyaltyService(cast(LoyaltyRepositoryPort, repository))
    actor = staff_actor(PermissionCode.POINTS_ACCRUE)
    key = str(uuid4())
    await service.confirm_accrual(
        actor,
        user_id=context.user.id,
        purchase_amount_minor=20_000,
        idempotency_key=key,
    )

    with pytest.raises(AppError) as error:
        await service.confirm_accrual(
            actor,
            user_id=context.user.id,
            purchase_amount_minor=21_000,
            idempotency_key=key,
        )

    assert error.value.status_code == 409
    assert error.value.code == "idempotency_conflict"
    assert context.state.points_balance == 30


@pytest.mark.asyncio
async def test_large_pending_operation_does_not_mutate_snapshot_or_ledger() -> None:
    context = loyalty_context(large_operation_requires_approval=True)
    repository = FakeRepository(context)
    service = LoyaltyService(cast(LoyaltyRepositoryPort, repository))
    result = await service.confirm_accrual(
        staff_actor(PermissionCode.POINTS_ACCRUE),
        user_id=context.user.id,
        purchase_amount_minor=20_000,
        idempotency_key=str(uuid4()),
    )

    assert result.operation_status is OperationStatus.PENDING
    assert result.balance_after is None
    assert context.state.points_balance == 10
    assert context.state.version == 1
    assert repository.point_transactions == []


@pytest.mark.asyncio
async def test_concurrent_same_key_is_serialized_to_one_commit() -> None:
    context = loyalty_context()
    repository = FakeRepository(context)
    service = LoyaltyService(cast(LoyaltyRepositoryPort, repository))
    actor = staff_actor(PermissionCode.POINTS_ACCRUE)
    key = str(uuid4())

    results = await asyncio.gather(
        service.confirm_accrual(
            actor,
            user_id=context.user.id,
            purchase_amount_minor=20_000,
            idempotency_key=key,
        ),
        service.confirm_accrual(
            actor,
            user_id=context.user.id,
            purchase_amount_minor=20_000,
            idempotency_key=key,
        ),
    )

    assert {item.idempotent_replay for item in results} == {False, True}
    assert results[0].operation_id == results[1].operation_id
    assert context.state.points_balance == 30
    assert len(repository.point_transactions) == 1


@pytest.mark.asyncio
async def test_idempotency_key_is_scoped_to_actor_and_payload() -> None:
    context = loyalty_context()
    repository = FakeRepository(context)
    service = LoyaltyService(cast(LoyaltyRepositoryPort, repository))
    key = str(uuid4())
    await service.confirm_accrual(
        staff_actor(PermissionCode.POINTS_ACCRUE),
        user_id=context.user.id,
        purchase_amount_minor=20_000,
        idempotency_key=key,
    )

    with pytest.raises(AppError) as error:
        await service.confirm_accrual(
            staff_actor(PermissionCode.POINTS_ACCRUE),
            user_id=context.user.id,
            purchase_amount_minor=20_000,
            idempotency_key=key,
        )

    assert error.value.code == "idempotency_conflict"


@pytest.mark.asyncio
async def test_confirm_recalculates_redemption_against_locked_current_balance() -> None:
    context = loyalty_context(points_balance=100)
    repository = FakeRepository(context)
    service = LoyaltyService(cast(LoyaltyRepositoryPort, repository))
    actor = staff_actor(PermissionCode.POINTS_REDEEM)
    preview = await service.preview_redemption(
        actor,
        user_id=context.user.id,
        purchase_amount_minor=20_000,
        requested_points=50,
    )
    assert preview.projected_balance_after == 50

    context.state.points_balance = 40
    with pytest.raises(AppError) as error:
        await service.confirm_redemption(
            actor,
            user_id=context.user.id,
            purchase_amount_minor=20_000,
            requested_points=50,
            idempotency_key=str(uuid4()),
        )

    assert error.value.code == "insufficient_points"
    assert repository.for_update_calls[-1] is True
    assert context.state.points_balance == 40


@pytest.mark.asyncio
async def test_blocked_and_self_cards_are_rejected_before_mutation() -> None:
    context = loyalty_context()
    context.user.status = UserStatus.BLOCKED
    repository = FakeRepository(context)
    service = LoyaltyService(cast(LoyaltyRepositoryPort, repository))
    actor = staff_actor(PermissionCode.POINTS_ACCRUE)

    with pytest.raises(AppError) as blocked_error:
        await service.confirm_accrual(
            actor,
            user_id=context.user.id,
            purchase_amount_minor=20_000,
            idempotency_key=str(uuid4()),
        )
    assert blocked_error.value.code == "card_blocked"

    context.user.status = UserStatus.ACTIVE
    self_actor = Actor(
        user_id=context.user.id,
        telegram_id=1001,
        session_id=uuid4(),
        role=Role.STAFF,
        staff_member_id=uuid4(),
        permissions=frozenset({PermissionCode.POINTS_ACCRUE}),
    )
    with pytest.raises(AppError) as self_error:
        await service.confirm_accrual(
            self_actor,
            user_id=context.user.id,
            purchase_amount_minor=20_000,
            idempotency_key=str(uuid4()),
        )
    assert self_error.value.code == "self_operation_forbidden"
    assert repository.point_transactions == []


@pytest.mark.asyncio
async def test_block_unblock_and_reissue_are_idempotent_admin_actions() -> None:
    context = loyalty_context()
    old_card_id = context.card.id
    repository = FakeRepository(context)
    service = LoyaltyService(cast(LoyaltyRepositoryPort, repository))
    actor = staff_actor(PermissionCode.ADMIN_USERS_MANAGE)

    block_key = str(uuid4())
    blocked = await service.block_user(
        actor,
        user_id=context.user.id,
        reason="подозрительная активность",
        idempotency_key=block_key,
    )
    blocked_replay = await service.block_user(
        actor,
        user_id=context.user.id,
        reason="подозрительная активность",
        idempotency_key=block_key,
    )
    assert blocked.user_status is UserStatus.BLOCKED
    assert blocked_replay.idempotent_replay is True
    assert blocked_replay.audit_message == blocked.audit_message
    assert repository.revoked_session_calls == 1

    await service.unblock_user(
        actor,
        user_id=context.user.id,
        idempotency_key=str(uuid4()),
    )
    assert context.user.status is UserStatus.ACTIVE

    reissue_key = str(uuid4())
    reissued = await service.reissue_card(
        actor,
        user_id=context.user.id,
        idempotency_key=reissue_key,
    )
    replay = await service.reissue_card(
        actor,
        user_id=context.user.id,
        idempotency_key=reissue_key,
    )
    assert repository.cards[old_card_id].status is CardStatus.REVOKED
    assert reissued.card_id != old_card_id
    assert replay.card_id == reissued.card_id
    assert replay.qr_payload == reissued.qr_payload
