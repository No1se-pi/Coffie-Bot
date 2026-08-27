"""Privacy-minimized courier API contracts."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import OrderStatus
from app.services.couriers import CourierOption, CourierOrderView


class ApiSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CourierAssignRequest(ApiSchema):
    courier_staff_id: UUID


class CourierOptionResponse(ApiSchema):
    id: UUID
    display_name: str


class CourierOptionListResponse(ApiSchema):
    items: list[CourierOptionResponse]


def courier_option_response(value: CourierOption) -> CourierOptionResponse:
    return CourierOptionResponse(id=value.id, display_name=value.display_name)


class CourierOrderResponse(ApiSchema):
    id: UUID
    number: int
    status: OrderStatus
    status_version: int
    venue_names: list[str]
    delivery_zone_name: str | None
    desired_delivery_at: datetime | None
    created_at: datetime
    customer_name: str | None = None
    contact_phone: str | None = None
    delivery_address: str | None = None
    entrance: str | None = None
    apartment: str | None = None
    floor: str | None = None
    customer_comment: str | None = None


class CourierOrderListResponse(ApiSchema):
    items: list[CourierOrderResponse]


def courier_order_response(value: CourierOrderView) -> CourierOrderResponse:
    """Expose address and contact only after the order belongs to this courier."""

    order = value.order
    customer_name = None
    if value.customer is not None:
        customer_name = " ".join(
            part for part in (value.customer.first_name, value.customer.last_name) if part
        )
    private = value.customer is not None
    return CourierOrderResponse(
        id=order.id,
        number=order.number,
        status=order.status,
        status_version=order.status_version,
        venue_names=list(value.venue_names),
        delivery_zone_name=order.delivery_zone_name_snapshot,
        desired_delivery_at=order.desired_delivery_at,
        created_at=order.created_at,
        customer_name=customer_name,
        contact_phone=order.contact_phone if private else None,
        delivery_address=order.delivery_address if private else None,
        entrance=order.entrance if private else None,
        apartment=order.apartment if private else None,
        floor=order.floor if private else None,
        customer_comment=order.customer_comment if private else None,
    )
