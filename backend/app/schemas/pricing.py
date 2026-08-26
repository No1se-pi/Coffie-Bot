"""Cart pricing request and immutable snapshot-ready response schemas."""

from __future__ import annotations

from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.pricing import PricingResult


class ApiSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModifierSelectionRequest(ApiSchema):
    option_id: UUID
    quantity: int = Field(default=1, ge=1, le=99)


class CartLineRequest(ApiSchema):
    line_id: UUID = Field(default_factory=uuid4)
    menu_item_id: UUID
    quantity: int = Field(ge=1, le=99)
    modifiers: list[ModifierSelectionRequest] = Field(default_factory=list, max_length=50)


class CartPriceRequest(ApiSchema):
    fulfillment_mode: Literal["pickup", "delivery"]
    lines: list[CartLineRequest] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_line_ids(self) -> CartPriceRequest:
        line_ids = [line.line_id for line in self.lines]
        if len(line_ids) != len(set(line_ids)):
            raise ValueError("line_id values must be unique")
        return self


class PricedModifierResponse(ApiSchema):
    option_id: UUID
    group_id: UUID
    group_name: str
    name: str
    quantity: int
    unit_price_delta_minor: int
    total_price_delta_minor: int


class PricedLineResponse(ApiSchema):
    line_id: UUID
    menu_item_id: UUID
    venue_id: UUID
    category_id: UUID
    item_name: str
    quantity: int
    unit_base_price_minor: int
    unit_modifiers_price_minor: int
    subtotal_minor: int
    discount_minor: int
    total_minor: int
    modifiers: list[PricedModifierResponse]


class AppliedPromotionResponse(ApiSchema):
    promotion_id: UUID
    title: str
    priority: int
    discount_minor: int


class PricedVenueResponse(ApiSchema):
    venue_id: UUID
    subtotal_minor: int
    discount_minor: int
    total_minor: int
    lines: list[PricedLineResponse]
    promotions: list[AppliedPromotionResponse]


class CartPriceResponse(ApiSchema):
    subtotal_minor: int
    discount_minor: int
    total_minor: int
    venues: list[PricedVenueResponse]


def cart_price_response(result: PricingResult) -> CartPriceResponse:
    """Convert immutable domain records without recalculating any amount."""

    return CartPriceResponse.model_validate(
        {
            "subtotal_minor": result.subtotal_minor,
            "discount_minor": result.discount_minor,
            "total_minor": result.total_minor,
            "venues": [
                {
                    "venue_id": venue.venue_id,
                    "subtotal_minor": venue.subtotal_minor,
                    "discount_minor": venue.discount_minor,
                    "total_minor": venue.total_minor,
                    "lines": [
                        {
                            "line_id": line.line_id,
                            "menu_item_id": line.menu_item_id,
                            "venue_id": line.venue_id,
                            "category_id": line.category_id,
                            "item_name": line.item_name,
                            "quantity": line.quantity,
                            "unit_base_price_minor": line.unit_base_price_minor,
                            "unit_modifiers_price_minor": line.unit_modifiers_price_minor,
                            "subtotal_minor": line.subtotal_minor,
                            "discount_minor": line.discount_minor,
                            "total_minor": line.total_minor,
                            "modifiers": [
                                {
                                    "option_id": modifier.option_id,
                                    "group_id": modifier.group_id,
                                    "group_name": modifier.group_name,
                                    "name": modifier.name,
                                    "quantity": modifier.quantity,
                                    "unit_price_delta_minor": modifier.unit_price_delta_minor,
                                    "total_price_delta_minor": modifier.total_price_delta_minor,
                                }
                                for modifier in line.modifiers
                            ],
                        }
                        for line in venue.lines
                    ],
                    "promotions": [
                        {
                            "promotion_id": promotion.promotion_id,
                            "title": promotion.title,
                            "priority": promotion.priority,
                            "discount_minor": promotion.discount_minor,
                        }
                        for promotion in venue.promotions
                    ],
                }
                for venue in result.venues
            ],
        }
    )
