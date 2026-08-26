"""Admin modifier catalogue and promotion-rule API schemas."""

from __future__ import annotations

from datetime import date, datetime, time
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import PromotionActionType
from app.services.menu_pricing_admin import ModifierGroupView, PromotionRulesView


class ApiSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModifierOptionInput(ApiSchema):
    id: UUID | None = None
    name: str = Field(min_length=1, max_length=160)
    price_delta_minor: int = Field(default=0, ge=0, le=1_000_000_000)
    allows_quantity: bool = False
    max_quantity: int = Field(default=1, ge=1, le=100)
    enabled: bool = True
    sort_order: int = Field(default=0, ge=-100_000, le=100_000)


class ModifierGroupInput(ApiSchema):
    venue_id: UUID
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4_000)
    min_selections: int = Field(default=0, ge=0, le=100)
    max_selections: int = Field(default=1, ge=0, le=100)
    required: bool = False
    enabled: bool = True
    sort_order: int = Field(default=0, ge=-100_000, le=100_000)
    item_ids: list[UUID] = Field(default_factory=list, max_length=500)
    options: list[ModifierOptionInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_selection_range(self) -> ModifierGroupInput:
        if self.max_selections < self.min_selections:
            raise ValueError("max_selections must not be below min_selections")
        if self.required and self.min_selections == 0:
            raise ValueError("required group must have min_selections >= 1")
        return self


class ModifierOptionResponse(ApiSchema):
    id: UUID
    name: str
    price_delta_minor: int
    allows_quantity: bool
    max_quantity: int
    enabled: bool
    sort_order: int


class ModifierGroupResponse(ApiSchema):
    id: UUID
    venue_id: UUID
    name: str
    description: str | None
    min_selections: int
    max_selections: int
    required: bool
    enabled: bool
    sort_order: int
    archived_at: datetime | None
    item_ids: list[UUID]
    options: list[ModifierOptionResponse]


class ModifierGroupListResponse(ApiSchema):
    items: list[ModifierGroupResponse]


class PromotionRulesInput(ApiSchema):
    pricing_enabled: bool = False
    action_type: PromotionActionType | None = None
    discount_value: int | None = Field(default=None, gt=0, le=1_000_000_000)
    priority: int = Field(default=0, ge=-100_000, le=100_000)
    stackable: bool = False
    active_from_date: date | None = None
    active_to_date: date | None = None
    active_weekdays: list[int] = Field(default_factory=list, max_length=7)
    active_time_from: time | None = None
    active_time_to: time | None = None
    fulfillment_modes: list[str] = Field(default_factory=list, max_length=2)
    customer_birthday_only: bool = False
    minimum_order_minor: int = Field(default=0, ge=0, le=1_000_000_000)
    category_ids: list[UUID] = Field(default_factory=list, max_length=500)
    menu_item_ids: list[UUID] = Field(default_factory=list, max_length=2_000)


class PromotionRulesResponse(PromotionRulesInput):
    promotion_id: UUID
    venue_id: UUID


def modifier_group_response(view: ModifierGroupView) -> ModifierGroupResponse:
    group = view.group
    return ModifierGroupResponse(
        id=group.id,
        venue_id=group.venue_id,
        name=group.name,
        description=group.description,
        min_selections=group.min_selections,
        max_selections=group.max_selections,
        required=group.is_required,
        enabled=group.is_enabled,
        sort_order=group.sort_order,
        archived_at=group.archived_at,
        item_ids=sorted(view.item_ids, key=str),
        options=[
            ModifierOptionResponse(
                id=option.id,
                name=option.name,
                price_delta_minor=option.price_delta_minor,
                allows_quantity=option.allows_quantity,
                max_quantity=option.max_quantity,
                enabled=option.is_enabled,
                sort_order=option.sort_order,
            )
            for option in view.options
        ],
    )


def promotion_rules_response(view: PromotionRulesView) -> PromotionRulesResponse:
    promotion = view.promotion
    return PromotionRulesResponse(
        promotion_id=promotion.id,
        venue_id=promotion.venue_id,
        pricing_enabled=promotion.pricing_enabled,
        action_type=promotion.action_type,
        discount_value=promotion.discount_value,
        priority=promotion.priority,
        stackable=promotion.stackable,
        active_from_date=promotion.active_from_date,
        active_to_date=promotion.active_to_date,
        active_weekdays=[int(value) for value in promotion.active_weekdays],
        active_time_from=promotion.active_time_from,
        active_time_to=promotion.active_time_to,
        fulfillment_modes=[str(value) for value in promotion.fulfillment_modes],
        customer_birthday_only=promotion.customer_birthday_only,
        minimum_order_minor=promotion.minimum_order_minor,
        category_ids=sorted(view.category_ids, key=str),
        menu_item_ids=sorted(view.menu_item_ids, key=str),
    )
