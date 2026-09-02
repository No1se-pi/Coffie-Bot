"""Administrative pickup and delivery configuration contracts."""

from __future__ import annotations

from datetime import time
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApiSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DeliverySettingsUpdate(ApiSchema):
    delivery_enabled: bool
    minimum_order_minor: int = Field(ge=0)
    fixed_fee_minor: int = Field(ge=0)
    free_delivery_threshold_minor: int | None = Field(default=None, ge=0)
    scheduling_allowed: bool
    earliest_preparation_minutes: int = Field(ge=0, le=1440)
    operating_hours: dict[str, Any] = Field(default_factory=dict)
    default_pickup_location_id: UUID | None
    consolidation_location_id: UUID | None

    @field_validator("operating_hours")
    @classmethod
    def validate_operating_hours(cls, value: dict[str, Any]) -> dict[str, Any]:
        allowed_days = {
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        }
        if set(value) - allowed_days:
            raise ValueError("operating_hours contains an unknown weekday")
        for interval in value.values():
            if not isinstance(interval, str):
                raise ValueError("operating_hours interval must be a string")
            if interval.strip().casefold() == "closed":
                continue
            try:
                start, end = (part.strip() for part in interval.split("-", maxsplit=1))
                time.fromisoformat(start)
                time.fromisoformat(end)
            except (TypeError, ValueError) as exc:
                raise ValueError("operating_hours interval must be HH:MM-HH:MM") from exc
        return value


class DeliverySettingsResponse(DeliverySettingsUpdate):
    id: UUID


class DeliveryZoneCreate(ApiSchema):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2_000)
    fee_minor: int = Field(ge=0)
    minimum_order_minor: int | None = Field(default=None, ge=0)
    location_id: UUID | None = None
    radius_meters: int | None = Field(default=None, ge=100, le=100_000)
    is_active: bool = True
    sort_order: int = Field(default=0, ge=0)


class DeliveryZoneUpdate(DeliveryZoneCreate):
    pass


class DeliveryZoneAdminResponse(DeliveryZoneCreate):
    id: UUID
    archived: bool


class DeliveryZoneListResponse(ApiSchema):
    items: list[DeliveryZoneAdminResponse]


class LocationFulfillmentUpdate(ApiSchema):
    pickup_enabled: bool
    consolidation_enabled: bool
    pickup_comment: str | None = Field(default=None, max_length=2_000)
    preparation_minutes: int = Field(ge=0, le=1440)
    venue_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=160)
    address: str | None = Field(default=None, min_length=1, max_length=2_000)
    phone: str | None = Field(default=None, max_length=64)
    map_url: str | None = Field(default=None, max_length=2_048)
    image_media_id: UUID | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    is_active: bool | None = None


class LocationCreate(ApiSchema):
    venue_id: UUID | None = None
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    name: str = Field(min_length=1, max_length=160)
    address: str = Field(min_length=1, max_length=2_000)
    phone: str | None = Field(default=None, max_length=64)
    map_url: str | None = Field(default=None, max_length=2_048)
    image_media_id: UUID | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    timezone: str = Field(default="Europe/Moscow", min_length=1, max_length=64)
    is_active: bool = True
    pickup_enabled: bool = True
    consolidation_enabled: bool = False
    pickup_comment: str | None = Field(default=None, max_length=2_000)
    preparation_minutes: int = Field(default=20, ge=0, le=1440)
    sort_order: int = Field(default=0, ge=-100_000, le=100_000)


class LocationFulfillmentResponse(LocationFulfillmentUpdate):
    id: UUID
    venue_id: UUID | None
    slug: str
    name: str
    address: str
    phone: str | None
    map_url: str | None
    image_media_id: UUID | None
    latitude: float | None
    longitude: float | None
    timezone: str
    is_active: bool


class LocationFulfillmentListResponse(ApiSchema):
    items: list[LocationFulfillmentResponse]
