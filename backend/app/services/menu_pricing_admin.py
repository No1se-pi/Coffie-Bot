"""Admin use cases for venue modifiers and practical promotion rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import NoReturn
from uuid import UUID, uuid4

from fastapi import status

from app.core.errors import AppError
from app.models.audit import AuditEvent
from app.models.content import ModifierGroup, ModifierOption, Promotion
from app.models.enums import AuditSeverity, PromotionActionType
from app.repositories.menu_pricing_admin import MenuPricingAdminRepository
from app.security.rbac import Actor


@dataclass(frozen=True, slots=True)
class RequestMetadata:
    ip_address: str | None = None
    user_agent: str | None = None


@dataclass(frozen=True, slots=True)
class ModifierOptionCommand:
    id: UUID | None
    name: str
    price_delta_minor: int
    allows_quantity: bool
    max_quantity: int
    is_enabled: bool
    sort_order: int


@dataclass(frozen=True, slots=True)
class ModifierGroupCommand:
    venue_id: UUID
    name: str
    description: str | None
    min_selections: int
    max_selections: int
    is_required: bool
    is_enabled: bool
    sort_order: int
    item_ids: frozenset[UUID]
    options: tuple[ModifierOptionCommand, ...]


@dataclass(frozen=True, slots=True)
class ModifierGroupView:
    group: ModifierGroup
    options: tuple[ModifierOption, ...]
    item_ids: frozenset[UUID]


@dataclass(frozen=True, slots=True)
class PromotionRulesCommand:
    pricing_enabled: bool
    action_type: PromotionActionType | None
    discount_value: int | None
    priority: int
    stackable: bool
    active_from_date: date | None
    active_to_date: date | None
    active_weekdays: frozenset[int]
    active_time_from: time | None
    active_time_to: time | None
    fulfillment_modes: frozenset[str]
    customer_birthday_only: bool
    minimum_order_minor: int
    category_ids: frozenset[UUID]
    menu_item_ids: frozenset[UUID]


@dataclass(frozen=True, slots=True)
class PromotionRulesView:
    promotion: Promotion
    category_ids: frozenset[UUID]
    menu_item_ids: frozenset[UUID]


class MenuPricingAdminService:
    def __init__(self, repository: MenuPricingAdminRepository) -> None:
        self._repository = repository

    async def list_modifier_groups(
        self, *, venue_id: UUID | None, include_archived: bool
    ) -> list[ModifierGroupView]:
        groups = await self._repository.list_groups(
            venue_id=venue_id, include_archived=include_archived
        )
        group_ids = {group.id for group in groups}
        options = await self._repository.list_options(group_ids)
        links = await self._repository.list_group_item_links(group_ids)
        options_by_group: dict[UUID, list[ModifierOption]] = {}
        for option in options:
            options_by_group.setdefault(option.group_id, []).append(option)
        items_by_group: dict[UUID, set[UUID]] = {}
        for group_id, item_id in links:
            items_by_group.setdefault(group_id, set()).add(item_id)
        return [
            ModifierGroupView(
                group=group,
                options=tuple(options_by_group.get(group.id, [])),
                item_ids=frozenset(items_by_group.get(group.id, set())),
            )
            for group in groups
        ]

    async def create_modifier_group(
        self,
        actor: Actor,
        command: ModifierGroupCommand,
        *,
        metadata: RequestMetadata,
    ) -> ModifierGroupView:
        self._validate_group(command)
        group = ModifierGroup(
            id=uuid4(),
            venue_id=command.venue_id,
            name=command.name,
            description=command.description,
            min_selections=command.min_selections,
            max_selections=command.max_selections,
            is_required=command.is_required,
            is_enabled=command.is_enabled,
            sort_order=command.sort_order,
        )
        async with self._repository.transaction():
            await self._require_active_venue(command.venue_id)
            await self._require_items(command.item_ids, venue_id=command.venue_id)
            self._repository.add(group)
            await self._repository.flush()
            options = self._materialize_options(group.id, command.options)
            self._repository.add_all([*options])
            await self._repository.replace_group_links(group, set(command.item_ids))
            self._audit(
                actor,
                event_type="menu.modifier_group_created",
                object_type="modifier_group",
                object_id=group.id,
                metadata=metadata,
                values={"venue_id": str(group.venue_id), "name": group.name},
            )
            await self._repository.flush()
        return ModifierGroupView(group=group, options=tuple(options), item_ids=command.item_ids)

    async def update_modifier_group(
        self,
        actor: Actor,
        group_id: UUID,
        command: ModifierGroupCommand,
        *,
        metadata: RequestMetadata,
    ) -> ModifierGroupView:
        self._validate_group(command)
        async with self._repository.transaction():
            group = await self._repository.get_group(group_id, for_update=True)
            if group is None:
                self._not_found("Modifier group was not found")
            if group.archived_at is not None:
                self._conflict("modifier_group_archived", "Archived modifier group cannot change")
            if command.venue_id != group.venue_id:
                self._conflict(
                    "modifier_group_venue_immutable",
                    "Modifier group cannot move to another venue",
                )
            await self._require_items(command.item_ids, venue_id=group.venue_id)
            group.name = command.name
            group.description = command.description
            group.min_selections = command.min_selections
            group.max_selections = command.max_selections
            group.is_required = command.is_required
            group.is_enabled = command.is_enabled
            group.sort_order = command.sort_order

            existing = {
                option.id: option for option in await self._repository.list_options({group.id})
            }
            options: list[ModifierOption] = []
            for value in command.options:
                option = existing.get(value.id) if value.id is not None else None
                if value.id is not None and option is None:
                    self._conflict(
                        "modifier_option_mismatch",
                        "Modifier option does not belong to this group",
                    )
                if option is None:
                    option = ModifierOption(id=uuid4(), group_id=group.id)
                    self._repository.add(option)
                option.name = value.name
                option.price_delta_minor = value.price_delta_minor
                option.allows_quantity = value.allows_quantity
                option.max_quantity = value.max_quantity
                option.is_enabled = value.is_enabled
                option.sort_order = value.sort_order
                options.append(option)
            await self._repository.delete_options_except(group.id, {item.id for item in options})
            await self._repository.replace_group_links(group, set(command.item_ids))
            self._audit(
                actor,
                event_type="menu.modifier_group_updated",
                object_type="modifier_group",
                object_id=group.id,
                metadata=metadata,
                values={"option_count": len(options), "item_count": len(command.item_ids)},
            )
            await self._repository.flush()
            return ModifierGroupView(
                group=group,
                options=tuple(options),
                item_ids=command.item_ids,
            )

    async def set_modifier_group_archived(
        self,
        actor: Actor,
        group_id: UUID,
        *,
        archived: bool,
        metadata: RequestMetadata,
        now: datetime | None = None,
    ) -> ModifierGroupView:
        current_time = now or datetime.now(UTC)
        async with self._repository.transaction():
            group = await self._repository.get_group(group_id, for_update=True)
            if group is None:
                self._not_found("Modifier group was not found")
            group.archived_at = current_time if archived else None
            group.is_enabled = not archived
            self._audit(
                actor,
                event_type=(
                    "menu.modifier_group_archived" if archived else "menu.modifier_group_restored"
                ),
                object_type="modifier_group",
                object_id=group.id,
                metadata=metadata,
                values={},
            )
            await self._repository.flush()
            views = await self.list_modifier_groups(venue_id=group.venue_id, include_archived=True)
            return next(view for view in views if view.group.id == group.id)

    async def get_promotion_rules(self, promotion_id: UUID) -> PromotionRulesView:
        promotion = await self._repository.get_promotion(promotion_id, for_update=False)
        if promotion is None:
            self._not_found("Promotion was not found")
        category_ids, item_ids = await self._repository.promotion_targets(promotion.id)
        return PromotionRulesView(
            promotion=promotion,
            category_ids=frozenset(category_ids),
            menu_item_ids=frozenset(item_ids),
        )

    async def update_promotion_rules(
        self,
        actor: Actor,
        promotion_id: UUID,
        command: PromotionRulesCommand,
        *,
        metadata: RequestMetadata,
    ) -> PromotionRulesView:
        self._validate_promotion(command)
        async with self._repository.transaction():
            promotion = await self._repository.get_promotion(promotion_id, for_update=True)
            if promotion is None:
                self._not_found("Promotion was not found")
            await self._require_categories(command.category_ids, venue_id=promotion.venue_id)
            await self._require_items(command.menu_item_ids, venue_id=promotion.venue_id)
            promotion.pricing_enabled = command.pricing_enabled
            promotion.action_type = command.action_type
            promotion.discount_value = command.discount_value
            promotion.priority = command.priority
            promotion.stackable = command.stackable
            promotion.active_from_date = command.active_from_date
            promotion.active_to_date = command.active_to_date
            promotion.active_weekdays = sorted(command.active_weekdays)
            promotion.active_time_from = command.active_time_from
            promotion.active_time_to = command.active_time_to
            promotion.fulfillment_modes = sorted(command.fulfillment_modes)
            promotion.customer_birthday_only = command.customer_birthday_only
            promotion.minimum_order_minor = command.minimum_order_minor
            await self._repository.replace_promotion_targets(
                promotion.id,
                venue_id=promotion.venue_id,
                category_ids=set(command.category_ids),
                item_ids=set(command.menu_item_ids),
            )
            self._audit(
                actor,
                event_type="promotion.pricing_rules_updated",
                object_type="promotion",
                object_id=promotion.id,
                metadata=metadata,
                values={
                    "pricing_enabled": command.pricing_enabled,
                    "action_type": (
                        command.action_type.value if command.action_type is not None else None
                    ),
                    "priority": command.priority,
                    "stackable": command.stackable,
                    "category_count": len(command.category_ids),
                    "item_count": len(command.menu_item_ids),
                },
            )
            await self._repository.flush()
            return PromotionRulesView(
                promotion=promotion,
                category_ids=command.category_ids,
                menu_item_ids=command.menu_item_ids,
            )

    async def _require_active_venue(self, venue_id: UUID) -> None:
        venue = await self._repository.get_venue(venue_id)
        if venue is None or not venue.is_active or venue.archived_at is not None:
            self._conflict("invalid_venue", "Venue is unavailable")

    async def _require_items(self, item_ids: frozenset[UUID], *, venue_id: UUID) -> None:
        items = await self._repository.get_items(set(item_ids))
        if len(items) != len(item_ids) or any(
            item.venue_id != venue_id or item.archived_at is not None for item in items
        ):
            self._conflict(
                "modifier_item_venue_mismatch",
                "All menu items must be active content of the same venue",
            )

    async def _require_categories(self, category_ids: frozenset[UUID], *, venue_id: UUID) -> None:
        categories = await self._repository.get_categories(set(category_ids))
        if len(categories) != len(category_ids) or any(
            item.venue_id != venue_id or item.archived_at is not None for item in categories
        ):
            self._conflict(
                "promotion_category_venue_mismatch",
                "All categories must belong to the promotion venue",
            )

    @staticmethod
    def _validate_group(command: ModifierGroupCommand) -> None:
        if command.is_required and command.min_selections < 1:
            MenuPricingAdminService._validation(
                "required_modifier_minimum",
                "Required modifier group must select at least one option",
            )
        if command.max_selections < command.min_selections:
            MenuPricingAdminService._validation(
                "invalid_modifier_range", "max_selections must not be below min_selections"
            )
        if not command.options:
            MenuPricingAdminService._validation(
                "modifier_options_required", "Modifier group must have at least one option"
            )
        normalized_names = [value.name.casefold().strip() for value in command.options]
        if len(normalized_names) != len(set(normalized_names)):
            MenuPricingAdminService._validation(
                "duplicate_modifier_option", "Modifier option names must be unique"
            )

    @staticmethod
    def _validate_promotion(command: PromotionRulesCommand) -> None:
        if command.pricing_enabled and (
            command.action_type is None or command.discount_value is None
        ):
            MenuPricingAdminService._validation(
                "promotion_action_required", "Enabled pricing requires an action and value"
            )
        if (
            command.action_type is PromotionActionType.PERCENT_DISCOUNT
            and command.discount_value is not None
            and command.discount_value > 10_000
        ):
            MenuPricingAdminService._validation(
                "invalid_percent_discount", "Percent discount must not exceed 100%"
            )
        if command.active_from_date and command.active_to_date:
            if command.active_to_date < command.active_from_date:
                MenuPricingAdminService._validation(
                    "invalid_promotion_date_window", "Promotion date window is invalid"
                )
        if not command.active_weekdays.issubset(set(range(7))):
            MenuPricingAdminService._validation(
                "invalid_promotion_weekday", "Weekdays must use values 0..6"
            )
        if not command.fulfillment_modes.issubset({"pickup", "delivery"}):
            MenuPricingAdminService._validation(
                "invalid_fulfillment_mode", "Unknown fulfillment mode"
            )

    @staticmethod
    def _materialize_options(
        group_id: UUID, commands: tuple[ModifierOptionCommand, ...]
    ) -> list[ModifierOption]:
        return [
            ModifierOption(
                id=value.id or uuid4(),
                group_id=group_id,
                name=value.name,
                price_delta_minor=value.price_delta_minor,
                allows_quantity=value.allows_quantity,
                max_quantity=value.max_quantity,
                is_enabled=value.is_enabled,
                sort_order=value.sort_order,
            )
            for value in commands
        ]

    def _audit(
        self,
        actor: Actor,
        *,
        event_type: str,
        object_type: str,
        object_id: UUID,
        metadata: RequestMetadata,
        values: dict[str, object],
    ) -> None:
        self._repository.add(
            AuditEvent(
                id=uuid4(),
                event_type=event_type,
                actor_user_id=actor.user_id,
                actor_staff_id=actor.staff_member_id,
                object_type=object_type,
                object_id=object_id,
                event_metadata=values,
                severity=AuditSeverity.INFO,
                is_suspicious=False,
                ip_address=metadata.ip_address,
                user_agent=metadata.user_agent,
            )
        )

    @staticmethod
    def _not_found(message: str) -> NoReturn:
        raise AppError(code="not_found", message=message, status_code=status.HTTP_404_NOT_FOUND)

    @staticmethod
    def _conflict(code: str, message: str) -> NoReturn:
        raise AppError(code=code, message=message, status_code=status.HTTP_409_CONFLICT)

    @staticmethod
    def _validation(code: str, message: str) -> NoReturn:
        raise AppError(
            code=code,
            message=message,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
