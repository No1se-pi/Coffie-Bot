"""Persistence adapter for idempotent installation bootstrap commands."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import case, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.access import StaffMember, StaffPermission, User
from app.models.audit import AuditEvent
from app.models.content import AppSetting, Location, MenuCategory, MenuItem, Promotion
from app.models.enums import AuditSeverity, PermissionCode, Role, UserStatus
from app.models.loyalty import LoyaltySettings, RewardTemplate
from app.models.media import MediaFile

BOOTSTRAP_LOCK_KEY = 4_349_346_470_191
SEED_IDS_SETTING = "seed.entity_ids"


class BootstrapRepository:
    """SQLAlchemy implementation; application services own the transaction boundary."""

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

    async def acquire_lock(self) -> None:
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": BOOTSTRAP_LOCK_KEY},
        )

    async def load_seed_entity_ids(self) -> dict[str, UUID]:
        raw = await self._session.scalar(
            select(AppSetting.value).where(AppSetting.key == SEED_IDS_SETTING)
        )
        if not isinstance(raw, dict):
            return {}
        result: dict[str, UUID] = {}
        for key, value in raw.items():
            if not isinstance(key, str) or not isinstance(value, str):
                continue
            try:
                result[key] = UUID(value)
            except ValueError:
                continue
        return result

    async def save_seed_entity_ids(self, values: Mapping[str, UUID]) -> None:
        await self.upsert_app_setting(
            SEED_IDS_SETTING,
            {key: str(value) for key, value in sorted(values.items())},
            is_public=False,
        )

    async def upsert_app_setting(self, key: str, value: Any, *, is_public: bool) -> None:
        statement = (
            pg_insert(AppSetting)
            .values(id=uuid4(), key=key, value=value, is_public=is_public)
            .on_conflict_do_update(
                index_elements=[AppSetting.key],
                set_={"value": value, "is_public": is_public},
            )
        )
        await self._session.execute(statement)

    async def upsert_location(self, slug: str, values: Mapping[str, Any]) -> UUID:
        if values.get("is_default") is True:
            await self._session.execute(
                update(Location)
                .where(Location.slug != slug, Location.is_default.is_(True))
                .values(is_default=False)
            )
        location = await self._session.scalar(
            select(Location).where(Location.slug == slug).with_for_update()
        )
        if location is None:
            location = Location(id=uuid4(), slug=slug, **values)
            self._session.add(location)
        else:
            _assign(location, values)
        await self._session.flush()
        return location.id

    async def find_media_id(self, storage_key: str | None) -> UUID | None:
        if not storage_key:
            return None
        return cast(
            UUID | None,
            await self._session.scalar(
                select(MediaFile.id).where(MediaFile.storage_key == storage_key)
            ),
        )

    async def upsert_reward_template(
        self,
        entity_id: UUID,
        values: Mapping[str, Any],
    ) -> UUID:
        template = await self._session.get(RewardTemplate, entity_id)
        if template is None:
            template = RewardTemplate(id=entity_id, **values)
            self._session.add(template)
        else:
            _assign(template, values)
        await self._session.flush()
        return template.id

    async def upsert_loyalty_settings(self, values: Mapping[str, Any]) -> UUID:
        settings = await self._session.scalar(
            select(LoyaltySettings)
            .where(LoyaltySettings.singleton_key == "default")
            .with_for_update()
        )
        if settings is None:
            settings = LoyaltySettings(id=uuid4(), singleton_key="default", **values)
            self._session.add(settings)
        else:
            _assign(settings, values)
        await self._session.flush()
        return settings.id

    async def upsert_menu_category(
        self,
        entity_id: UUID,
        values: Mapping[str, Any],
    ) -> UUID:
        category = await self._session.get(MenuCategory, entity_id)
        if category is None:
            category = MenuCategory(id=entity_id, **values)
            self._session.add(category)
        else:
            _assign(category, values)
        await self._session.flush()
        return category.id

    async def upsert_menu_item(
        self,
        entity_id: UUID,
        values: Mapping[str, Any],
    ) -> UUID:
        item = await self._session.get(MenuItem, entity_id)
        if item is None:
            item = MenuItem(id=entity_id, **values)
            self._session.add(item)
        else:
            _assign(item, values)
        await self._session.flush()
        return item.id

    async def upsert_promotion(
        self,
        entity_id: UUID,
        values: Mapping[str, Any],
    ) -> UUID:
        promotion = await self._session.get(Promotion, entity_id)
        if promotion is None:
            promotion = Promotion(id=entity_id, **values)
            self._session.add(promotion)
        else:
            preserved_creator = promotion.created_by_staff_id
            _assign(promotion, values)
            promotion.created_by_staff_id = preserved_creator
        await self._session.flush()
        return promotion.id

    async def find_active_staff_id(self) -> UUID | None:
        owner_first = case((StaffMember.role == Role.OWNER, 0), else_=1)
        return cast(
            UUID | None,
            await self._session.scalar(
                select(StaffMember.id)
                .where(StaffMember.is_active.is_(True))
                .order_by(owner_first, StaffMember.created_at, StaffMember.id)
                .limit(1)
            ),
        )

    async def upsert_seed_staff(
        self,
        *,
        telegram_id: int,
        display_name: str,
        role: Role,
        permissions: set[PermissionCode],
        is_active: bool,
    ) -> UUID:
        user = await self._upsert_user(
            telegram_id=telegram_id,
            first_name=display_name,
        )
        staff = await self._session.scalar(
            select(StaffMember).where(StaffMember.user_id == user.id).with_for_update()
        )
        if staff is None:
            staff = StaffMember(
                id=uuid4(),
                user_id=user.id,
                role=role,
                display_name=display_name,
                is_active=is_active,
                disabled_at=None if is_active else datetime.now(UTC),
            )
            self._session.add(staff)
            await self._session.flush()
        elif staff.role != Role.OWNER:
            staff.role = role
            staff.display_name = display_name
            staff.is_active = is_active
            staff.disabled_at = None if is_active else staff.disabled_at or datetime.now(UTC)

        for permission in permissions:
            await self._session.execute(
                pg_insert(StaffPermission)
                .values(
                    id=uuid4(),
                    staff_member_id=staff.id,
                    permission=permission,
                    allowed=True,
                )
                .on_conflict_do_update(
                    index_elements=[
                        StaffPermission.staff_member_id,
                        StaffPermission.permission,
                    ],
                    set_={"allowed": True},
                )
            )
        return staff.id

    async def upsert_owner(
        self,
        *,
        telegram_id: int,
        display_name: str | None,
    ) -> tuple[UUID, UUID, bool]:
        await self.acquire_lock()
        user = await self._upsert_user(
            telegram_id=telegram_id,
            first_name=display_name or "Владелец",
            replace_name=display_name is not None,
        )
        staff = await self._session.scalar(
            select(StaffMember).where(StaffMember.user_id == user.id).with_for_update()
        )
        changed = False
        if staff is None:
            staff = StaffMember(
                id=uuid4(),
                user_id=user.id,
                role=Role.OWNER,
                display_name=display_name,
                is_active=True,
                disabled_at=None,
            )
            self._session.add(staff)
            changed = True
        else:
            changed = (
                staff.role != Role.OWNER
                or not staff.is_active
                or staff.disabled_at is not None
                or (display_name is not None and staff.display_name != display_name)
            )
            staff.role = Role.OWNER
            staff.is_active = True
            staff.disabled_at = None
            if display_name is not None:
                staff.display_name = display_name
        await self._session.flush()
        if changed:
            self._session.add(
                AuditEvent(
                    id=uuid4(),
                    event_type="staff.owner_upserted",
                    actor_user_id=user.id,
                    actor_staff_id=staff.id,
                    subject_user_id=user.id,
                    object_type="staff_member",
                    object_id=staff.id,
                    event_metadata={"telegram_id": telegram_id},
                    severity=AuditSeverity.INFO,
                    is_suspicious=False,
                )
            )
        return user.id, staff.id, changed

    async def export_configuration(self) -> dict[str, Any]:
        setting_rows = (
            await self._session.execute(
                select(AppSetting.key, AppSetting.value)
                .where(AppSetting.key != SEED_IDS_SETTING)
                .order_by(AppSetting.key)
            )
        ).all()
        app_settings: dict[str, Any] = {}
        for key, value in setting_rows:
            app_settings[str(key)] = value
        locations = list(
            (
                await self._session.scalars(select(Location).order_by(Location.sort_order))
            ).all()
        )
        loyalty = await self._session.scalar(
            select(LoyaltySettings).where(LoyaltySettings.singleton_key == "default")
        )
        rewards = list(
            (
                await self._session.scalars(
                    select(RewardTemplate).order_by(RewardTemplate.name, RewardTemplate.id)
                )
            ).all()
        )
        categories = list(
            (
                await self._session.scalars(
                    select(MenuCategory).order_by(MenuCategory.sort_order, MenuCategory.id)
                )
            ).all()
        )
        items = list(
            (
                await self._session.scalars(
                    select(MenuItem).order_by(MenuItem.sort_order, MenuItem.id)
                )
            ).all()
        )
        promotions = list(
            (
                await self._session.scalars(
                    select(Promotion).order_by(Promotion.created_at, Promotion.id)
                )
            ).all()
        )
        return {
            "schema_version": 1,
            "exported_at": datetime.now(UTC).isoformat(),
            "app_settings": app_settings,
            "locations": [_location_export(item) for item in locations],
            "loyalty_settings": _loyalty_export(loyalty),
            "reward_templates": [_reward_export(item) for item in rewards],
            "menu": {
                "categories": [_category_export(item) for item in categories],
                "items": [_item_export(item) for item in items],
            },
            "promotions": [_promotion_export(item) for item in promotions],
        }

    async def _upsert_user(
        self,
        *,
        telegram_id: int,
        first_name: str,
        replace_name: bool = False,
    ) -> User:
        set_values: dict[str, Any] = {"status": UserStatus.ACTIVE}
        if replace_name:
            set_values["first_name"] = first_name
        user_id = await self._session.scalar(
            pg_insert(User)
            .values(
                id=uuid4(),
                telegram_id=telegram_id,
                first_name=first_name,
                status=UserStatus.ACTIVE,
            )
            .on_conflict_do_update(
                index_elements=[User.telegram_id],
                set_=set_values,
            )
            .returning(User.id)
        )
        user = await self._session.get(User, user_id)
        if user is None:
            raise RuntimeError("User upsert did not return a row")
        return user


def _assign(target: object, values: Mapping[str, Any]) -> None:
    for key, value in values.items():
        setattr(target, key, value)


def _location_export(item: Location) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "slug": item.slug,
        "name": item.name,
        "description": item.description,
        "address": item.address,
        "latitude": float(item.latitude) if item.latitude is not None else None,
        "longitude": float(item.longitude) if item.longitude is not None else None,
        "timezone": item.timezone,
        "business_day_boundary_minutes": item.business_day_boundary_minutes,
        "phone": item.phone,
        "map_url": item.map_url,
        "opening_hours": item.opening_hours,
        "is_default": item.is_default,
        "is_active": item.is_active,
        "sort_order": item.sort_order,
    }


def _loyalty_export(item: LoyaltySettings | None) -> dict[str, Any] | None:
    if item is None:
        return None
    excluded = {"id", "created_at", "updated_at"}
    return {
        column.name: _json_value(getattr(item, column.name))
        for column in LoyaltySettings.__table__.columns
        if column.name not in excluded
    }


def _reward_export(item: RewardTemplate) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "name": item.name,
        "description": item.description,
        "reward_type": item.reward_type.value,
        "source_program": item.source_program.value,
        "value_int": item.value_int,
        "terms": item.terms,
        "validity_days": item.validity_days,
        "is_active": item.is_active,
    }


def _category_export(item: MenuCategory) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "name": item.name,
        "description": item.description,
        "sort_order": item.sort_order,
        "is_visible": item.is_visible,
    }


def _item_export(item: MenuItem) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "category_id": str(item.category_id),
        "name": item.name,
        "description": item.description,
        "price_minor": item.price_minor,
        "old_price_minor": item.old_price_minor,
        "composition": item.composition,
        "volume": item.volume,
        "labels": item.labels,
        "is_available": item.is_available,
        "is_visible": item.is_visible,
        "sort_order": item.sort_order,
    }


def _promotion_export(item: Promotion) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "title": item.title,
        "body": item.body,
        "button_label": item.button_label,
        "button_url": item.button_url,
        "status": item.status.value,
        "starts_at": _json_value(item.starts_at),
        "ends_at": _json_value(item.ends_at),
        "published_at": _json_value(item.published_at),
    }


def _json_value(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    return value
