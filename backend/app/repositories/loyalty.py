"""PostgreSQL persistence adapter for the transactional loyalty slice."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import Select, String, func, literal, or_, select, update
from sqlalchemy import cast as sql_cast
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.access import Session, StaffMember, User
from app.models.audit import AuditEvent
from app.models.cards import UserCard
from app.models.content import MenuItem
from app.models.customers import CustomerIdentity, CustomerMerge
from app.models.delivery import NotificationOutbox
from app.models.enums import (
    AuditSeverity,
    CardStatus,
    IdentityProvider,
    LoyaltyOperationType,
    OperationStatus,
    RewardStatus,
    TipProfileStatus,
    UserStatus,
)
from app.models.loyalty import (
    LoyaltyOperation,
    LoyaltySettings,
    Reward,
    RewardTemplate,
    StampTransaction,
    UserLoyaltyState,
    Visit,
)
from app.models.staff import StaffTipProfile


@dataclass(frozen=True, slots=True)
class LoyaltyContext:
    user: User
    card: UserCard
    state: UserLoyaltyState
    settings: LoyaltySettings


@dataclass(frozen=True, slots=True)
class OperationArtifacts:
    visit: Visit | None
    stamp: StampTransaction | None
    rewards: tuple[Reward, ...]
    audit_event: AuditEvent | None


@dataclass(frozen=True, slots=True)
class OperationPage:
    items: list[LoyaltyOperation]
    total: int


@dataclass(frozen=True, slots=True)
class RewardPage:
    items: list[Reward]
    total: int


@dataclass(frozen=True, slots=True)
class RewardQrRecord:
    reward: Reward
    user: User


@dataclass(frozen=True, slots=True)
class PostPurchaseRecord:
    operation: LoyaltyOperation
    staff: StaffMember
    staff_user: User
    tip_profile: StaffTipProfile | None


@dataclass(frozen=True, slots=True)
class UserPage:
    items: list[User]
    total: int


@dataclass(frozen=True, slots=True)
class AuditEventPage:
    items: list[AuditEvent]
    total: int


class LoyaltyRepository:
    """Repository whose caller owns the transaction boundary."""

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
        """Serialise creation of an idempotency row that does not exist yet."""

        digest = hashlib.sha256(f"{namespace}:{key}".encode()).digest()
        lock_id = int.from_bytes(digest[:8], byteorder="big", signed=True)
        await self._session.execute(select(func.pg_advisory_xact_lock(lock_id)))

    async def lookup_card(
        self,
        *,
        qr_token: str | None,
        short_code: str | None,
        phone: str | None,
    ) -> LoyaltyContext | None:
        identifiers = []
        if qr_token is not None:
            identifiers.append(UserCard.qr_token == qr_token)
        if short_code is not None:
            identifiers.append(UserCard.short_code == short_code)
        if phone is not None:
            identifiers.append(CustomerIdentity.subject == phone)
        if len(identifiers) != 1:
            raise ValueError("exactly one card identifier is required")
        statement = (
            select(User, UserCard, UserLoyaltyState, LoyaltySettings)
            .join(UserCard, UserCard.user_id == User.id)
            .join(UserLoyaltyState, UserLoyaltyState.user_id == User.id)
            .join(LoyaltySettings, LoyaltySettings.singleton_key == "default")
            .where(UserCard.status == CardStatus.ACTIVE, identifiers[0])
        )
        if phone is not None:
            statement = statement.join(
                CustomerIdentity,
                CustomerIdentity.user_id == User.id,
            ).where(
                CustomerIdentity.provider == IdentityProvider.PHONE,
                CustomerIdentity.is_verified.is_(True),
            )
        return await self._context_from_statement(statement)

    async def get_context(
        self,
        user_id: UUID,
        *,
        for_update: bool,
    ) -> LoyaltyContext | None:
        statement = (
            select(User, UserCard, UserLoyaltyState, LoyaltySettings)
            .join(UserCard, UserCard.user_id == User.id)
            .join(UserLoyaltyState, UserLoyaltyState.user_id == User.id)
            .join(LoyaltySettings, LoyaltySettings.singleton_key == "default")
            .where(
                User.id == user_id,
                UserCard.status == CardStatus.ACTIVE,
            )
        )
        if for_update:
            statement = statement.with_for_update(of=[User, UserCard, UserLoyaltyState])
        return await self._context_from_statement(statement)

    async def _context_from_statement(
        self,
        statement: Select[tuple[User, UserCard, UserLoyaltyState, LoyaltySettings]],
    ) -> LoyaltyContext | None:
        row = (await self._session.execute(statement)).one_or_none()
        if row is None:
            return None
        return LoyaltyContext(
            user=row[0],
            card=row[1],
            state=row[2],
            settings=row[3],
        )

    async def accrued_points_between(
        self,
        *,
        user_id: UUID,
        started_at: datetime,
        ended_at: datetime,
    ) -> int:
        value = await self._session.scalar(
            select(
                func.coalesce(
                    func.sum(LoyaltyOperation.points_delta - LoyaltyOperation.reward_bonus_points),
                    0,
                )
            ).where(
                LoyaltyOperation.user_id == user_id,
                LoyaltyOperation.operation_type == LoyaltyOperationType.PURCHASE_ACCRUAL,
                LoyaltyOperation.status == OperationStatus.COMMITTED,
                LoyaltyOperation.occurred_at >= started_at,
                LoyaltyOperation.occurred_at < ended_at,
            )
        )
        return int(value or 0)

    async def count_visits(self, *, user_id: UUID, business_date: date) -> int:
        value = await self._session.scalar(
            select(func.count())
            .select_from(Visit)
            .where(
                Visit.user_id == user_id,
                Visit.business_date == business_date,
            )
        )
        return int(value or 0)

    async def get_operation_by_idempotency(
        self,
        *,
        operation_type: LoyaltyOperationType,
        idempotency_key: str,
    ) -> LoyaltyOperation | None:
        value = await self._session.scalar(
            select(LoyaltyOperation).where(
                LoyaltyOperation.operation_type == operation_type,
                LoyaltyOperation.idempotency_key == idempotency_key,
            )
        )
        return value

    async def get_operation(
        self,
        operation_id: UUID,
        *,
        for_update: bool,
    ) -> LoyaltyOperation | None:
        statement = select(LoyaltyOperation).where(LoyaltyOperation.id == operation_id)
        if for_update:
            statement = statement.with_for_update()
        value = await self._session.scalar(statement)
        return value

    async def get_reversal(self, operation_id: UUID) -> LoyaltyOperation | None:
        value = await self._session.scalar(
            select(LoyaltyOperation).where(LoyaltyOperation.reversal_of_id == operation_id)
        )
        return value

    async def get_operation_artifacts(self, operation_id: UUID) -> OperationArtifacts:
        visit = cast(
            Visit | None,
            await self._session.scalar(select(Visit).where(Visit.operation_id == operation_id)),
        )
        stamp = cast(
            StampTransaction | None,
            await self._session.scalar(
                select(StampTransaction).where(StampTransaction.operation_id == operation_id)
            ),
        )
        rewards = tuple(
            (
                await self._session.scalars(
                    select(Reward)
                    .where(
                        or_(
                            Reward.source_operation_id == operation_id,
                            Reward.redemption_operation_id == operation_id,
                            Reward.cancellation_operation_id == operation_id,
                        )
                    )
                    .order_by(Reward.created_at, Reward.id)
                )
            ).all()
        )
        audit_event = cast(
            AuditEvent | None,
            await self._session.scalar(
                select(AuditEvent)
                .where(
                    AuditEvent.object_type == "loyalty_operation",
                    AuditEvent.object_id == operation_id,
                )
                .order_by(AuditEvent.created_at.desc())
                .limit(1)
            ),
        )
        return OperationArtifacts(
            visit=visit,
            stamp=stamp,
            rewards=rewards,
            audit_event=audit_event,
        )

    async def get_reward_template(self, template_id: UUID) -> RewardTemplate | None:
        value = await self._session.get(RewardTemplate, template_id)
        return value

    async def get_reward(self, reward_id: UUID, *, for_update: bool) -> Reward | None:
        statement = select(Reward).where(Reward.id == reward_id)
        if for_update:
            statement = statement.with_for_update()
        value = await self._session.scalar(statement)
        return value

    async def get_reward_by_source_operation(self, operation_id: UUID) -> Reward | None:
        value: Reward | None = await self._session.scalar(
            select(Reward).where(Reward.source_operation_id == operation_id)
        )
        return value

    async def get_reward_by_qr(self, qr_payload: str) -> RewardQrRecord | None:
        row = (
            await self._session.execute(
                select(Reward, User)
                .join(User, User.id == Reward.user_id)
                .where(Reward.qr_payload == qr_payload)
            )
        ).one_or_none()
        return None if row is None else RewardQrRecord(reward=row[0], user=row[1])

    async def get_menu_item(self, item_id: UUID, *, for_update: bool) -> MenuItem | None:
        statement = select(MenuItem).where(MenuItem.id == item_id)
        if for_update:
            statement = statement.with_for_update()
        value: MenuItem | None = await self._session.scalar(statement)
        return value

    async def get_post_purchase(
        self, *, operation_id: UUID, user_id: UUID
    ) -> PostPurchaseRecord | None:
        row = (
            await self._session.execute(
                select(LoyaltyOperation, StaffMember, User, StaffTipProfile)
                .join(StaffMember, StaffMember.id == LoyaltyOperation.actor_staff_id)
                .join(User, User.id == StaffMember.user_id)
                .outerjoin(
                    StaffTipProfile,
                    StaffTipProfile.staff_member_id == StaffMember.id,
                )
                .where(
                    LoyaltyOperation.id == operation_id,
                    LoyaltyOperation.user_id == user_id,
                    LoyaltyOperation.status == OperationStatus.COMMITTED,
                )
            )
        ).one_or_none()
        if row is None:
            return None
        profile = row[3]
        if profile is not None and (
            profile.status is not TipProfileStatus.APPROVED or not profile.is_visible
        ):
            profile = None
        return PostPurchaseRecord(
            operation=row[0],
            staff=row[1],
            staff_user=row[2],
            tip_profile=profile,
        )

    async def get_outbox_by_key(self, idempotency_key: str) -> NotificationOutbox | None:
        value = await self._session.scalar(
            select(NotificationOutbox).where(NotificationOutbox.idempotency_key == idempotency_key)
        )
        return value

    async def get_card(self, card_id: UUID) -> UserCard | None:
        value = await self._session.get(UserCard, card_id)
        return value

    async def revoke_user_sessions(
        self,
        *,
        user_id: UUID,
        now: datetime,
        reason: str,
    ) -> None:
        await self._session.execute(
            update(Session)
            .where(Session.user_id == user_id, Session.revoked_at.is_(None))
            .values(revoked_at=now, revoke_reason=reason)
        )

    async def list_operations(
        self,
        *,
        user_id: UUID | None,
        actor_staff_id: UUID | None,
        page: int,
        page_size: int,
    ) -> OperationPage:
        filters: list[ColumnElement[bool]] = []
        if user_id is not None:
            lineage = select(literal(user_id).label("user_id")).cte(
                "admin_customer_history_lineage",
                recursive=True,
            )
            merge_edges = CustomerMerge.__table__.alias("admin_customer_history_merge_edges")
            lineage = lineage.union_all(
                select(merge_edges.c.source_user_id).where(
                    merge_edges.c.canonical_user_id == lineage.c.user_id
                )
            )
            filters.append(LoyaltyOperation.user_id.in_(select(lineage.c.user_id)))
        if actor_staff_id is not None:
            filters.append(LoyaltyOperation.actor_staff_id == actor_staff_id)
        total = int(
            await self._session.scalar(
                select(func.count()).select_from(LoyaltyOperation).where(*filters)
            )
            or 0
        )
        items = list(
            (
                await self._session.scalars(
                    select(LoyaltyOperation)
                    .where(*filters)
                    .order_by(
                        LoyaltyOperation.occurred_at.desc(),
                        LoyaltyOperation.id.desc(),
                    )
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return OperationPage(items=items, total=total)

    async def list_rewards(
        self,
        *,
        user_id: UUID,
        reward_status: RewardStatus | None,
        page: int,
        page_size: int,
    ) -> RewardPage:
        filters = [Reward.user_id == user_id]
        if reward_status is not None:
            filters.append(Reward.status == reward_status)
        total = int(
            await self._session.scalar(select(func.count()).select_from(Reward).where(*filters))
            or 0
        )
        items = list(
            (
                await self._session.scalars(
                    select(Reward)
                    .where(*filters)
                    .order_by(Reward.created_at.desc(), Reward.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return RewardPage(items=items, total=total)

    async def list_users(
        self,
        *,
        query: str | None,
        user_status: UserStatus | None,
        page: int,
        page_size: int,
    ) -> UserPage:
        # The owner-facing list is a customer list, not a directory of every
        # technical account. Staff/owner bootstrap users may not have a card
        # or loyalty state and therefore cannot be opened by the customer
        # management endpoints.
        filters = [UserCard.status == CardStatus.ACTIVE]
        if user_status is not None:
            filters.append(User.status == user_status)
        if query:
            pattern = f"%{query}%"
            filters.append(
                or_(
                    User.first_name.ilike(pattern),
                    User.last_name.ilike(pattern),
                    User.username.ilike(pattern),
                    sql_cast(User.telegram_id, String).ilike(pattern),
                    UserCard.short_code.ilike(pattern),
                )
            )
        total = int(
            await self._session.scalar(
                select(func.count())
                .select_from(User)
                .join(UserCard, UserCard.user_id == User.id)
                .join(UserLoyaltyState, UserLoyaltyState.user_id == User.id)
                .where(*filters)
            )
            or 0
        )
        items = list(
            (
                await self._session.scalars(
                    select(User)
                    .join(UserCard, UserCard.user_id == User.id)
                    .join(UserLoyaltyState, UserLoyaltyState.user_id == User.id)
                    .where(*filters)
                    .order_by(User.created_at.desc(), User.id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return UserPage(items=items, total=total)

    async def list_audit_events(
        self,
        *,
        started_at: datetime | None,
        ended_at: datetime | None,
        actor_user_id: UUID | None,
        subject_user_id: UUID | None,
        event_type: str | None,
        severity: AuditSeverity | None,
        suspicious: bool | None,
        adjustments: bool | None,
        reversed_operations: bool | None,
        page: int,
        page_size: int,
    ) -> AuditEventPage:
        filters = []
        if started_at is not None:
            filters.append(AuditEvent.created_at >= started_at)
        if ended_at is not None:
            filters.append(AuditEvent.created_at < ended_at)
        if actor_user_id is not None:
            filters.append(AuditEvent.actor_user_id == actor_user_id)
        if subject_user_id is not None:
            filters.append(AuditEvent.subject_user_id == subject_user_id)
        if event_type:
            filters.append(AuditEvent.event_type == event_type)
        if severity is not None:
            filters.append(AuditEvent.severity == severity)
        if suspicious is not None:
            filters.append(AuditEvent.is_suspicious == suspicious)
        selected_types: list[str] = []
        if adjustments is True:
            selected_types.append("points.adjusted")
        elif adjustments is False:
            filters.append(AuditEvent.event_type != "points.adjusted")
        if reversed_operations is True:
            selected_types.append("operation.reversed")
        elif reversed_operations is False:
            filters.append(AuditEvent.event_type != "operation.reversed")
        if selected_types:
            filters.append(AuditEvent.event_type.in_(selected_types))

        total = int(
            await self._session.scalar(select(func.count()).select_from(AuditEvent).where(*filters))
            or 0
        )
        items = list(
            (
                await self._session.scalars(
                    select(AuditEvent)
                    .where(*filters)
                    .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return AuditEventPage(items=items, total=total)

    def add_all(self, objects: list[object]) -> None:
        self._session.add_all(objects)

    async def flush(self) -> None:
        await self._session.flush()
