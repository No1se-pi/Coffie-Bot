"""Customer/staff order API contracts and privacy-safe snapshot DTOs."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import FulfillmentMode, OrderStatus, PaymentMethod, PaymentStatus
from app.repositories.orders import OrderAggregate
from app.services.orders import OrderOptions


class ApiSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OrderModifierInput(ApiSchema):
    option_id: UUID
    quantity: int = Field(default=1, ge=1, le=99)


class OrderLineInput(ApiSchema):
    line_id: UUID = Field(default_factory=uuid4)
    menu_item_id: UUID
    quantity: int = Field(ge=1, le=99)
    modifiers: list[OrderModifierInput] = Field(default_factory=list, max_length=50)


class OrderPointRedemptionInput(ApiSchema):
    venue_id: UUID
    points: int = Field(gt=0, le=1_000_000_000)


class OrderCreateRequest(ApiSchema):
    fulfillment_mode: FulfillmentMode
    lines: list[OrderLineInput] = Field(min_length=1, max_length=100)
    point_redemptions: list[OrderPointRedemptionInput] = Field(default_factory=list, max_length=100)
    pickup_location_id: UUID | None = None
    delivery_zone_id: UUID | None = None
    contact_phone: str = Field(min_length=8, max_length=32)
    delivery_address: str | None = Field(default=None, max_length=1_000)
    entrance: str | None = Field(default=None, max_length=32)
    apartment: str | None = Field(default=None, max_length=32)
    floor: str | None = Field(default=None, max_length=32)
    customer_comment: str | None = Field(default=None, max_length=2_000)
    desired_delivery_at: datetime | None = None
    payment_method: PaymentMethod = PaymentMethod.CARD_ON_RECEIPT

    @model_validator(mode="after")
    def validate_mode_fields(self) -> OrderCreateRequest:
        line_ids = [value.line_id for value in self.lines]
        if len(line_ids) != len(set(line_ids)):
            raise ValueError("line_id values must be unique")
        venue_ids = [value.venue_id for value in self.point_redemptions]
        if len(venue_ids) != len(set(venue_ids)):
            raise ValueError("point redemption venue_id values must be unique")
        if self.fulfillment_mode is FulfillmentMode.PICKUP and self.delivery_zone_id:
            raise ValueError("pickup order cannot contain delivery_zone_id")
        if self.fulfillment_mode is FulfillmentMode.DELIVERY and self.pickup_location_id:
            raise ValueError("delivery order cannot contain pickup_location_id")
        return self


class OrderTransitionRequest(ApiSchema):
    status: OrderStatus
    reason: str | None = Field(default=None, max_length=256)
    comment: str | None = Field(default=None, max_length=2_000)


class OrderCancelRequest(ApiSchema):
    reason: str = Field(min_length=1, max_length=256)


class PickupLocationResponse(ApiSchema):
    id: UUID
    venue_id: UUID | None
    name: str
    address: str
    opening_hours: dict[str, object]
    comment: str | None
    preparation_minutes: int


class DeliveryZoneResponse(ApiSchema):
    id: UUID
    name: str
    description: str | None
    fee_minor: int
    minimum_order_minor: int | None


class OrderOptionsResponse(ApiSchema):
    delivery_enabled: bool
    minimum_order_minor: int
    fixed_fee_minor: int
    free_delivery_threshold_minor: int | None
    scheduling_allowed: bool
    earliest_preparation_minutes: int
    pickup_locations: list[PickupLocationResponse]
    delivery_zones: list[DeliveryZoneResponse]


class OrderModifierResponse(ApiSchema):
    id: UUID
    option_id: UUID | None
    group_name: str
    name: str
    quantity: int
    unit_price_delta_minor: int
    total_price_delta_minor: int


class OrderLineResponse(ApiSchema):
    id: UUID
    menu_item_id: UUID | None
    name: str
    quantity: int
    unit_base_price_minor: int
    unit_modifiers_price_minor: int
    subtotal_minor: int
    promotion_discount_minor: int
    points_discount_minor: int
    total_minor: int
    modifiers: list[OrderModifierResponse]


class OrderPromotionResponse(ApiSchema):
    id: UUID
    promotion_id: UUID | None
    title: str
    priority: int
    discount_minor: int


class OrderSuborderResponse(ApiSchema):
    id: UUID
    venue_id: UUID
    venue_name: str
    status: OrderStatus
    subtotal_minor: int
    promotion_discount_minor: int
    points_discount_minor: int
    total_minor: int
    lines: list[OrderLineResponse]
    promotions: list[OrderPromotionResponse]


class OrderEventResponse(ApiSchema):
    id: UUID
    suborder_id: UUID | None
    from_status: OrderStatus | None
    to_status: OrderStatus
    reason: str | None
    comment: str | None
    created_at: datetime


class OrderResponse(ApiSchema):
    id: UUID
    number: int
    fulfillment_mode: FulfillmentMode
    status: OrderStatus
    status_version: int
    contact_phone: str
    delivery_address: str | None
    entrance: str | None
    apartment: str | None
    floor: str | None
    customer_comment: str | None
    desired_delivery_at: datetime | None
    pickup_name: str | None
    pickup_address: str | None
    delivery_zone_name: str | None
    subtotal_minor: int
    promotion_discount_minor: int
    points_discount_minor: int
    delivery_fee_minor: int
    total_minor: int
    payment_method: PaymentMethod
    payment_status: PaymentStatus
    created_at: datetime
    updated_at: datetime
    idempotent_replay: bool = False
    suborders: list[OrderSuborderResponse]
    events: list[OrderEventResponse]


class OrderListResponse(ApiSchema):
    items: list[OrderResponse]


def order_options_response(value: OrderOptions) -> OrderOptionsResponse:
    """Serialize only customer-safe delivery and pickup configuration."""

    return OrderOptionsResponse(
        delivery_enabled=value.settings.delivery_enabled,
        minimum_order_minor=value.settings.minimum_order_minor,
        fixed_fee_minor=value.settings.fixed_fee_minor,
        free_delivery_threshold_minor=value.settings.free_delivery_threshold_minor,
        scheduling_allowed=value.settings.scheduling_allowed,
        earliest_preparation_minutes=value.settings.earliest_preparation_minutes,
        pickup_locations=[
            PickupLocationResponse(
                id=location.id,
                venue_id=location.venue_id,
                name=location.name,
                address=location.address,
                opening_hours=location.opening_hours,
                comment=location.pickup_comment,
                preparation_minutes=location.preparation_minutes,
            )
            for location in value.pickup_locations
        ],
        delivery_zones=[
            DeliveryZoneResponse(
                id=zone.id,
                name=zone.name,
                description=zone.description,
                fee_minor=zone.fee_minor,
                minimum_order_minor=zone.minimum_order_minor,
            )
            for zone in value.delivery_zones
        ],
    )


def order_response(
    aggregate: OrderAggregate,
    *,
    idempotent_replay: bool = False,
) -> OrderResponse:
    order = aggregate.order
    modifiers_by_line: dict[UUID, list[OrderModifierResponse]] = {}
    for modifier in aggregate.modifiers:
        modifiers_by_line.setdefault(modifier.order_line_id, []).append(
            OrderModifierResponse(
                id=modifier.id,
                option_id=modifier.modifier_option_id,
                group_name=modifier.group_name,
                name=modifier.option_name,
                quantity=modifier.quantity,
                unit_price_delta_minor=modifier.unit_price_delta_minor,
                total_price_delta_minor=modifier.total_price_delta_minor,
            )
        )
    lines_by_suborder: dict[UUID, list[OrderLineResponse]] = {}
    for line in aggregate.lines:
        lines_by_suborder.setdefault(line.suborder_id, []).append(
            OrderLineResponse(
                id=line.id,
                menu_item_id=line.menu_item_id,
                name=line.item_name,
                quantity=line.quantity,
                unit_base_price_minor=line.unit_base_price_minor,
                unit_modifiers_price_minor=line.unit_modifiers_price_minor,
                subtotal_minor=line.subtotal_minor,
                promotion_discount_minor=line.promotion_discount_minor,
                points_discount_minor=line.points_discount_minor,
                total_minor=line.total_minor,
                modifiers=modifiers_by_line.get(line.id, []),
            )
        )
    promotions_by_suborder: dict[UUID, list[OrderPromotionResponse]] = {}
    for promotion in aggregate.promotions:
        promotions_by_suborder.setdefault(promotion.suborder_id, []).append(
            OrderPromotionResponse(
                id=promotion.id,
                promotion_id=promotion.promotion_id,
                title=promotion.title,
                priority=promotion.priority,
                discount_minor=promotion.discount_minor,
            )
        )
    return OrderResponse(
        id=order.id,
        number=order.number,
        fulfillment_mode=order.fulfillment_mode,
        status=order.status,
        status_version=order.status_version,
        contact_phone=order.contact_phone,
        delivery_address=order.delivery_address,
        entrance=order.entrance,
        apartment=order.apartment,
        floor=order.floor,
        customer_comment=order.customer_comment,
        desired_delivery_at=order.desired_delivery_at,
        pickup_name=order.pickup_name_snapshot,
        pickup_address=order.pickup_address_snapshot,
        delivery_zone_name=order.delivery_zone_name_snapshot,
        subtotal_minor=order.subtotal_minor,
        promotion_discount_minor=order.promotion_discount_minor,
        points_discount_minor=order.points_discount_minor,
        delivery_fee_minor=order.delivery_fee_minor,
        total_minor=order.total_minor,
        payment_method=order.payment_method,
        payment_status=order.payment_status,
        created_at=order.created_at,
        updated_at=order.updated_at,
        idempotent_replay=idempotent_replay,
        suborders=[
            OrderSuborderResponse(
                id=suborder.id,
                venue_id=suborder.venue_id,
                venue_name=aggregate.venues[suborder.venue_id].name,
                status=suborder.status,
                subtotal_minor=suborder.subtotal_minor,
                promotion_discount_minor=suborder.promotion_discount_minor,
                points_discount_minor=suborder.points_discount_minor,
                total_minor=suborder.total_minor,
                lines=lines_by_suborder.get(suborder.id, []),
                promotions=promotions_by_suborder.get(suborder.id, []),
            )
            for suborder in aggregate.suborders
        ],
        events=[
            OrderEventResponse(
                id=value.id,
                suborder_id=value.suborder_id,
                from_status=value.from_status,
                to_status=value.to_status,
                reason=value.reason,
                comment=value.comment,
                created_at=value.created_at,
            )
            for value in aggregate.events
        ],
    )
