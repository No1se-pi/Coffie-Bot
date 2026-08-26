"""Persistence adapter for admin content, staff, tips, feedback, and media."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.models.access import Session, StaffInvite, StaffMember, StaffPermission, User
from app.models.audit import AuditEvent
from app.models.content import Location, MenuCategory, MenuItem, Promotion, Venue
from app.models.enums import (
    FeedbackStatus,
    LoyaltyProgram,
    MediaStatus,
    PermissionCode,
    PromotionStatus,
    Role,
    TipProfileStatus,
)
from app.models.loyalty import LoyaltySettings, RewardTemplate
from app.models.media import MediaFile
from app.models.staff import FeedbackItem, StaffTipProfile


@dataclass(frozen=True, slots=True)
class MenuCategoryPage:
    items: list[MenuCategory]
    total: int


@dataclass(frozen=True, slots=True)
class MenuItemPage:
    items: list[MenuItem]
    total: int


@dataclass(frozen=True, slots=True)
class PromotionPage:
    items: list[Promotion]
    total: int


@dataclass(frozen=True, slots=True)
class FeedbackRecord:
    feedback: FeedbackItem
    user: User


@dataclass(frozen=True, slots=True)
class FeedbackPage:
    items: list[FeedbackRecord]
    total: int


@dataclass(frozen=True, slots=True)
class StaffPage:
    items: list[StaffMember]
    total: int


@dataclass(frozen=True, slots=True)
class LockedStaffManagement:
    target: StaffMember
    active_owner_count: int


@dataclass(frozen=True, slots=True)
class TipProfileRecord:
    profile: StaffTipProfile
    staff: StaffMember
    user: User


@dataclass(frozen=True, slots=True)
class TipProfilePage:
    items: list[TipProfileRecord]
    total: int


class AdminRepository:
    """SQLAlchemy operations; services own business rules and transaction boundaries."""

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

    async def flush(self) -> None:
        await self._session.flush()

    def add(self, value: object) -> None:
        self._session.add(value)

    def add_all(self, values: list[object]) -> None:
        self._session.add_all(values)

    async def acquire_idempotency_lock(self, namespace: str, key: str) -> None:
        """Serialize creation of an idempotency receipt that does not exist yet."""

        digest = hashlib.sha256(f"{namespace}:{key}".encode()).digest()
        lock_id = int.from_bytes(digest[:8], byteorder="big", signed=True)
        await self._session.execute(select(func.pg_advisory_xact_lock(lock_id)))

    async def get_audit_event_by_idempotency_key(self, key: str) -> AuditEvent | None:
        value: AuditEvent | None = await self._session.scalar(
            select(AuditEvent).where(AuditEvent.idempotency_key == key)
        )
        return value

    async def get_loyalty_settings(self, *, for_update: bool) -> LoyaltySettings | None:
        statement = select(LoyaltySettings).where(LoyaltySettings.singleton_key == "default")
        if for_update:
            statement = statement.with_for_update()
        value: LoyaltySettings | None = await self._session.scalar(statement)
        return value

    async def get_venue(self, venue_id: UUID) -> Venue | None:
        return await self._session.get(Venue, venue_id)

    async def get_default_active_venue(self) -> Venue | None:
        """Resolve the venue used by legacy clients that do not send venue_id."""
        statement = (
            select(Venue)
            .outerjoin(Location, Location.venue_id == Venue.id)
            .where(Venue.is_active.is_(True), Venue.archived_at.is_(None))
            .order_by(Location.is_default.desc(), Venue.sort_order, Venue.id)
            .limit(1)
        )
        value: Venue | None = await self._session.scalar(statement)
        return value

    async def list_menu_categories(
        self,
        *,
        page: int,
        page_size: int,
        include_archived: bool,
    ) -> MenuCategoryPage:
        filters = [] if include_archived else [MenuCategory.archived_at.is_(None)]
        total = int(
            await self._session.scalar(
                select(func.count()).select_from(MenuCategory).where(*filters)
            )
            or 0
        )
        items = list(
            (
                await self._session.scalars(
                    select(MenuCategory)
                    .where(*filters)
                    .order_by(MenuCategory.sort_order, MenuCategory.id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return MenuCategoryPage(items=items, total=total)

    async def get_menu_category(
        self,
        category_id: UUID,
        *,
        for_update: bool,
    ) -> MenuCategory | None:
        statement = select(MenuCategory).where(MenuCategory.id == category_id)
        if for_update:
            statement = statement.with_for_update()
        value: MenuCategory | None = await self._session.scalar(statement)
        return value

    async def list_menu_items(
        self,
        *,
        category_id: UUID | None,
        page: int,
        page_size: int,
        include_archived: bool,
    ) -> MenuItemPage:
        filters: list[ColumnElement[bool]] = (
            [] if include_archived else [MenuItem.archived_at.is_(None)]
        )
        if category_id is not None:
            filters.append(MenuItem.category_id == category_id)
        total = int(
            await self._session.scalar(select(func.count()).select_from(MenuItem).where(*filters))
            or 0
        )
        items = list(
            (
                await self._session.scalars(
                    select(MenuItem)
                    .where(*filters)
                    .order_by(MenuItem.sort_order, MenuItem.id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return MenuItemPage(items=items, total=total)

    async def get_menu_item(self, item_id: UUID, *, for_update: bool) -> MenuItem | None:
        statement = select(MenuItem).where(MenuItem.id == item_id)
        if for_update:
            statement = statement.with_for_update()
        value: MenuItem | None = await self._session.scalar(statement)
        return value

    async def delete_menu_item(self, item: MenuItem) -> None:
        await self._session.delete(item)

    async def get_menu_item_loyalty_reward_programs(
        self,
        item_id: UUID,
        *,
        for_update: bool,
    ) -> frozenset[LoyaltyProgram]:
        """Return programs whose current reward is sourced from ``item_id``.

        Locking the singleton settings row serializes this check with loyalty
        configuration updates.  The referenced templates are then locked in
        the same transaction so an archive/delete cannot detach the source
        menu item from a reward that has just become current.
        """

        settings_statement = select(LoyaltySettings).where(
            LoyaltySettings.singleton_key == "default"
        )
        if for_update:
            settings_statement = settings_statement.with_for_update()
        settings = await self._session.scalar(settings_statement)
        if settings is None:
            return frozenset()

        configured_templates = {
            LoyaltyProgram.VISITS: settings.visit_reward_template_id,
            LoyaltyProgram.STAMPS: settings.stamp_reward_template_id,
        }
        linked_programs: set[LoyaltyProgram] = set()
        # Match AdminService.update_loyalty_settings lock order exactly:
        # visits template first, then stamps template.
        for program in (LoyaltyProgram.VISITS, LoyaltyProgram.STAMPS):
            template_id = configured_templates[program]
            if template_id is None:
                continue
            template_statement = select(RewardTemplate.source_menu_item_id).where(
                RewardTemplate.id == template_id
            )
            if for_update:
                template_statement = template_statement.with_for_update()
            source_menu_item_id = await self._session.scalar(template_statement)
            if source_menu_item_id == item_id:
                linked_programs.add(program)
        return frozenset(linked_programs)

    async def get_reward_template(
        self,
        template_id: UUID,
        *,
        for_update: bool = False,
    ) -> RewardTemplate | None:
        statement = select(RewardTemplate).where(RewardTemplate.id == template_id)
        if for_update:
            statement = statement.with_for_update()
        value: RewardTemplate | None = await self._session.scalar(statement)
        return value

    async def list_promotions(
        self,
        *,
        promotion_status: PromotionStatus | None,
        page: int,
        page_size: int,
    ) -> PromotionPage:
        filters = (
            [Promotion.status != PromotionStatus.ARCHIVED]
            if promotion_status is None
            else [Promotion.status == promotion_status]
        )
        total = int(
            await self._session.scalar(select(func.count()).select_from(Promotion).where(*filters))
            or 0
        )
        items = list(
            (
                await self._session.scalars(
                    select(Promotion)
                    .where(*filters)
                    .order_by(Promotion.created_at.desc(), Promotion.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return PromotionPage(items=items, total=total)

    async def get_promotion(
        self,
        promotion_id: UUID,
        *,
        for_update: bool,
    ) -> Promotion | None:
        statement = select(Promotion).where(Promotion.id == promotion_id)
        if for_update:
            statement = statement.with_for_update()
        value: Promotion | None = await self._session.scalar(statement)
        return value

    async def delete_promotion(self, promotion: Promotion) -> None:
        await self._session.delete(promotion)

    async def list_feedback(
        self,
        *,
        feedback_status: FeedbackStatus | None,
        page: int,
        page_size: int,
    ) -> FeedbackPage:
        filters = (
            [FeedbackItem.status != FeedbackStatus.ARCHIVED]
            if feedback_status is None
            else [FeedbackItem.status == feedback_status]
        )
        total = int(
            await self._session.scalar(
                select(func.count()).select_from(FeedbackItem).where(*filters)
            )
            or 0
        )
        rows = (
            await self._session.execute(
                select(FeedbackItem, User)
                .join(User, User.id == FeedbackItem.user_id)
                .where(*filters)
                .order_by(FeedbackItem.created_at.desc(), FeedbackItem.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return FeedbackPage(
            items=[FeedbackRecord(feedback=row[0], user=row[1]) for row in rows],
            total=total,
        )

    async def get_feedback(
        self,
        feedback_id: UUID,
        *,
        for_update: bool,
    ) -> FeedbackRecord | None:
        statement = (
            select(FeedbackItem, User)
            .join(User, User.id == FeedbackItem.user_id)
            .where(FeedbackItem.id == feedback_id)
        )
        if for_update:
            statement = statement.with_for_update(of=FeedbackItem)
        row = (await self._session.execute(statement)).one_or_none()
        return None if row is None else FeedbackRecord(feedback=row[0], user=row[1])

    async def delete_feedback(self, feedback: FeedbackItem) -> None:
        await self._session.delete(feedback)

    async def list_staff(
        self,
        *,
        role: Role | None,
        active: bool | None,
        query: str | None,
        page: int,
        page_size: int,
    ) -> StaffPage:
        filters: list[ColumnElement[bool]] = [StaffMember.archived_at.is_(None)]
        if role is not None:
            filters.append(StaffMember.role == role)
        if active is not None:
            filters.append(StaffMember.is_active == active)
        if query:
            pattern = f"%{query}%"
            filters.append(
                or_(
                    StaffMember.display_name.ilike(pattern),
                    StaffMember.position.ilike(pattern),
                    User.first_name.ilike(pattern),
                    User.last_name.ilike(pattern),
                    User.username.ilike(pattern),
                )
            )
        total = int(
            await self._session.scalar(
                select(func.count())
                .select_from(StaffMember)
                .join(User, User.id == StaffMember.user_id)
                .where(*filters)
            )
            or 0
        )
        items = list(
            (
                await self._session.scalars(
                    select(StaffMember)
                    .join(User, User.id == StaffMember.user_id)
                    .options(
                        selectinload(StaffMember.user),
                        selectinload(StaffMember.permissions),
                    )
                    .where(*filters)
                    .order_by(StaffMember.created_at, StaffMember.id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return StaffPage(items=items, total=total)

    async def get_staff(self, staff_id: UUID, *, for_update: bool) -> StaffMember | None:
        statement = (
            select(StaffMember)
            .options(selectinload(StaffMember.user), selectinload(StaffMember.permissions))
            .where(StaffMember.id == staff_id)
        )
        if for_update:
            statement = statement.with_for_update(of=StaffMember)
        value: StaffMember | None = await self._session.scalar(statement)
        return value

    async def get_staff_by_user(
        self,
        user_id: UUID,
        *,
        for_update: bool,
    ) -> StaffMember | None:
        statement = (
            select(StaffMember)
            .options(selectinload(StaffMember.user), selectinload(StaffMember.permissions))
            .where(StaffMember.user_id == user_id)
        )
        if for_update:
            statement = statement.with_for_update(of=StaffMember)
        value: StaffMember | None = await self._session.scalar(statement)
        return value

    async def get_user_for_staff_creation(self, user_id: UUID) -> User | None:
        value: User | None = await self._session.scalar(
            select(User).where(User.id == user_id).with_for_update()
        )
        return value

    async def lock_staff_management(self, staff_id: UUID) -> LockedStaffManagement | None:
        owners = list(
            (
                await self._session.scalars(
                    select(StaffMember)
                    .where(
                        StaffMember.role == Role.OWNER,
                        StaffMember.archived_at.is_(None),
                    )
                    .order_by(StaffMember.id)
                    .with_for_update()
                )
            ).all()
        )
        target = await self.get_staff(staff_id, for_update=True)
        if target is None:
            return None
        return LockedStaffManagement(
            target=target,
            active_owner_count=sum(owner.is_active for owner in owners),
        )

    def replace_staff_permissions(
        self,
        staff: StaffMember,
        permissions: dict[PermissionCode, bool],
    ) -> None:
        existing = {value.permission: value for value in staff.permissions}
        for permission, allowed in sorted(permissions.items(), key=lambda item: item[0].value):
            current = existing.pop(permission, None)
            if current is None:
                staff.permissions.append(
                    StaffPermission(
                        staff_member_id=staff.id,
                        permission=permission,
                        allowed=allowed,
                    )
                )
            else:
                current.allowed = allowed
        for obsolete in existing.values():
            staff.permissions.remove(obsolete)

    async def revoke_user_sessions(
        self,
        *,
        user_id: UUID,
        now: datetime,
        reason: str,
    ) -> int:
        result = await self._session.execute(
            update(Session)
            .where(Session.user_id == user_id, Session.revoked_at.is_(None))
            .values(revoked_at=now, revoke_reason=reason)
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def revoke_open_invites_for_target(
        self,
        *,
        target_telegram_id: int,
        now: datetime,
    ) -> None:
        await self._session.execute(
            update(StaffInvite)
            .where(
                StaffInvite.target_telegram_id == target_telegram_id,
                StaffInvite.used_at.is_(None),
                StaffInvite.revoked_at.is_(None),
                StaffInvite.expires_at > now,
            )
            .values(revoked_at=now)
        )

    async def get_tip_profile_for_staff(
        self,
        staff_id: UUID,
        *,
        for_update: bool,
    ) -> TipProfileRecord | None:
        statement = (
            select(StaffTipProfile, StaffMember, User)
            .join(StaffMember, StaffMember.id == StaffTipProfile.staff_member_id)
            .join(User, User.id == StaffMember.user_id)
            .where(StaffTipProfile.staff_member_id == staff_id)
        )
        if for_update:
            statement = statement.with_for_update(of=StaffTipProfile)
        row = (await self._session.execute(statement)).one_or_none()
        return None if row is None else TipProfileRecord(profile=row[0], staff=row[1], user=row[2])

    async def get_staff_for_tip_profile(
        self,
        staff_id: UUID,
        *,
        for_update: bool,
    ) -> StaffMember | None:
        statement = (
            select(StaffMember)
            .options(selectinload(StaffMember.user))
            .where(StaffMember.id == staff_id)
        )
        if for_update:
            statement = statement.with_for_update(of=StaffMember)
        value: StaffMember | None = await self._session.scalar(statement)
        return value

    async def list_pending_tip_profiles(self, *, page: int, page_size: int) -> TipProfilePage:
        filters = [StaffTipProfile.status == TipProfileStatus.PENDING_REVIEW]
        total = int(
            await self._session.scalar(
                select(func.count()).select_from(StaffTipProfile).where(*filters)
            )
            or 0
        )
        rows = (
            await self._session.execute(
                select(StaffTipProfile, StaffMember, User)
                .join(StaffMember, StaffMember.id == StaffTipProfile.staff_member_id)
                .join(User, User.id == StaffMember.user_id)
                .where(*filters)
                .order_by(StaffTipProfile.submitted_at, StaffTipProfile.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return TipProfilePage(
            items=[TipProfileRecord(profile=row[0], staff=row[1], user=row[2]) for row in rows],
            total=total,
        )

    async def get_tip_profile(
        self,
        profile_id: UUID,
        *,
        for_update: bool,
    ) -> TipProfileRecord | None:
        statement = (
            select(StaffTipProfile, StaffMember, User)
            .join(StaffMember, StaffMember.id == StaffTipProfile.staff_member_id)
            .join(User, User.id == StaffMember.user_id)
            .where(StaffTipProfile.id == profile_id)
        )
        if for_update:
            statement = statement.with_for_update(of=StaffTipProfile)
        row = (await self._session.execute(statement)).one_or_none()
        return None if row is None else TipProfileRecord(profile=row[0], staff=row[1], user=row[2])

    async def get_media(self, media_id: UUID, *, active_only: bool) -> MediaFile | None:
        filters = [MediaFile.id == media_id]
        if active_only:
            filters.append(MediaFile.status == MediaStatus.ACTIVE)
        value: MediaFile | None = await self._session.scalar(select(MediaFile).where(*filters))
        return value
