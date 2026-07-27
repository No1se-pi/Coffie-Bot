"""Strict public-content and customer-feedback API schemas."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.content import Location, MenuCategory, MenuItem, Promotion
from app.models.enums import FeedbackCategory, FeedbackStatus, PromotionStatus
from app.models.staff import FeedbackItem
from app.repositories.public import PublicStaffProfileRecord


class ApiSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MenuCategoryResponse(ApiSchema):
    id: UUID
    name: str
    description: str | None
    icon_url: str | None = None
    sort_order: int
    visible: bool


class MenuCategoryListResponse(ApiSchema):
    items: list[MenuCategoryResponse]
    page: int = 1
    page_size: int
    total: int


class MenuItemResponse(ApiSchema):
    id: UUID
    category_id: UUID
    name: str
    description: str | None
    image_url: str | None = None
    price_minor: int
    old_price_minor: int | None
    points_price: int | None
    composition: str | None
    volume: str | None
    labels: list[str]
    available: bool
    visible: bool


class MenuItemListResponse(ApiSchema):
    items: list[MenuItemResponse]
    page: int = 1
    page_size: int
    total: int


class PromotionResponse(ApiSchema):
    id: UUID
    title: str
    text: str
    image_url: str | None = None
    button_label: str | None
    button_url: str | None
    starts_at: datetime | None
    ends_at: datetime | None
    status: PromotionStatus


class PromotionListResponse(ApiSchema):
    items: list[PromotionResponse]
    page: int = 1
    page_size: int
    total: int


class LocationResponse(ApiSchema):
    id: UUID
    name: str
    address: str
    hours: str
    phone: str | None
    map_url: str | None
    latitude: float | None
    longitude: float | None


class ContactsResponse(ApiSchema):
    coffee_shop_name: str
    description: str
    support_contact: str | None
    privacy_policy: str
    phone: str | None
    email: str | None
    website: str | None
    telegram: str | None
    locations: list[LocationResponse]


class StaffProfileResponse(ApiSchema):
    id: UUID
    display_name: str
    position: str
    bio: str | None
    photo_url: str | None = None
    tip_url: str | None
    tip_qr_url: str | None = None


class StaffProfileListResponse(ApiSchema):
    items: list[StaffProfileResponse]
    page: int = 1
    page_size: int
    total: int


class FeedbackRequest(ApiSchema):
    rating: int = Field(ge=1, le=5)
    category: FeedbackCategory
    message: str = Field(min_length=3, max_length=2_000)
    may_contact: bool = False

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 3:
            raise ValueError("message must contain at least three visible characters")
        return normalized


class FeedbackResponse(ApiSchema):
    id: UUID
    status: FeedbackStatus
    created_at: datetime


def menu_categories_response(
    items: list[MenuCategory],
) -> MenuCategoryListResponse:
    payload = [
        MenuCategoryResponse(
            id=item.id,
            name=item.name,
            description=item.description,
            icon_url=_media_url(item.icon_media_id),
            sort_order=item.sort_order,
            visible=item.is_visible,
        )
        for item in items
    ]
    return MenuCategoryListResponse(
        items=payload,
        page_size=len(payload),
        total=len(payload),
    )


def menu_items_response(items: list[MenuItem]) -> MenuItemListResponse:
    payload = [
        MenuItemResponse(
            id=item.id,
            category_id=item.category_id,
            name=item.name,
            description=item.description,
            image_url=_media_url(item.image_media_id),
            price_minor=item.price_minor,
            old_price_minor=item.old_price_minor,
            points_price=item.points_price,
            composition=item.composition,
            volume=item.volume,
            labels=item.labels,
            available=item.is_available,
            visible=item.is_visible,
        )
        for item in items
    ]
    return MenuItemListResponse(
        items=payload,
        page_size=len(payload),
        total=len(payload),
    )


def promotions_response(items: list[Promotion]) -> PromotionListResponse:
    payload = [
        PromotionResponse(
            id=item.id,
            title=item.title,
            text=item.body,
            image_url=_media_url(item.image_media_id),
            button_label=item.button_label,
            button_url=item.button_url,
            starts_at=item.starts_at,
            ends_at=item.ends_at,
            status=item.status,
        )
        for item in items
    ]
    return PromotionListResponse(
        items=payload,
        page_size=len(payload),
        total=len(payload),
    )


def contacts_response(
    settings: Mapping[str, Any],
    locations: list[Location],
) -> ContactsResponse:
    brand = _mapping(settings.get("brand"))
    contacts = _mapping(settings.get("contacts"))
    return ContactsResponse(
        coffee_shop_name=_text(brand.get("name")) or "Кофейня",
        description=_text(brand.get("description"))
        or _text(brand.get("welcome_text"))
        or "Программа лояльности кофейни",
        support_contact=_text(contacts.get("support_contact"))
        or _text(contacts.get("telegram"))
        or _text(contacts.get("email")),
        privacy_policy=_text(contacts.get("privacy_policy_text"))
        or _text(contacts.get("privacy_policy_url"))
        or "Политика конфиденциальности настраивается владельцем кофейни.",
        phone=_text(contacts.get("phone")),
        email=_text(contacts.get("email")),
        website=_text(contacts.get("website")),
        telegram=_text(contacts.get("telegram")),
        locations=[_location_response(item) for item in locations],
    )


def staff_profiles_response(
    records: list[PublicStaffProfileRecord],
) -> StaffProfileListResponse:
    items = [
        StaffProfileResponse(
            id=record.profile.id,
            display_name=record.profile.published_name
            or record.staff.display_name
            or record.user.first_name,
            position=record.staff.position or "Сотрудник",
            bio=record.profile.published_bio,
            photo_url=_media_url(record.profile.published_photo_media_id),
            tip_url=record.profile.published_tip_url,
            tip_qr_url=_media_url(record.profile.published_tip_qr_media_id),
        )
        for record in records
    ]
    return StaffProfileListResponse(
        items=items,
        page_size=len(items),
        total=len(items),
    )


def feedback_response(item: FeedbackItem) -> FeedbackResponse:
    return FeedbackResponse(id=item.id, status=item.status, created_at=item.created_at)


def _location_response(item: Location) -> LocationResponse:
    return LocationResponse(
        id=item.id,
        name=item.name,
        address=item.address,
        hours=_format_opening_hours(item.opening_hours),
        phone=item.phone,
        map_url=item.map_url,
        latitude=float(item.latitude) if item.latitude is not None else None,
        longitude=float(item.longitude) if item.longitude is not None else None,
    )


def _format_opening_hours(value: Mapping[str, Any]) -> str:
    labels = {
        "monday": "Пн",
        "tuesday": "Вт",
        "wednesday": "Ср",
        "thursday": "Чт",
        "friday": "Пт",
        "saturday": "Сб",
        "sunday": "Вс",
    }
    parts = [
        f"{label} {_text(value.get(day))}" for day, label in labels.items() if _text(value.get(day))
    ]
    return " · ".join(parts) if parts else "Часы работы уточняйте у кофейни"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _media_url(media_id: UUID | None) -> str | None:
    return f"/api/v1/media/{media_id}" if media_id is not None else None
