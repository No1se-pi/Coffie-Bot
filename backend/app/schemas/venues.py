"""Strict public and administrative Venue API contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.content import Venue
from app.repositories.venues import VenuePage


class ApiSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VenuePublicResponse(ApiSchema):
    id: UUID
    slug: str
    name: str
    description: str | None
    phone: str | None
    email: str | None
    website: str | None
    telegram: str | None
    logo_url: str | None
    sort_order: int


class VenuePublicListResponse(ApiSchema):
    items: list[VenuePublicResponse]
    page: int = 1
    page_size: int
    total: int


class VenueAdminResponse(VenuePublicResponse):
    logo_media_id: UUID | None
    active: bool
    archived_at: datetime | None


class VenueAdminListResponse(ApiSchema):
    items: list[VenueAdminResponse]
    page: int
    page_size: int
    total: int


class VenueCreate(ApiSchema):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4_000)
    phone: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=254)
    website: str | None = Field(default=None, max_length=2_048)
    telegram: str | None = Field(default=None, max_length=2_048)
    logo_media_id: UUID | None = None
    active: bool = True
    sort_order: int = Field(default=0, ge=-100_000, le=100_000)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _required_text(value)

    @field_validator("description", "phone", "email", "website", "telegram")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return _optional_text(value)

    @field_validator("website")
    @classmethod
    def validate_website(cls, value: str | None) -> str | None:
        return _http_url(value)


class VenueUpdate(ApiSchema):
    slug: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4_000)
    phone: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=254)
    website: str | None = Field(default=None, max_length=2_048)
    telegram: str | None = Field(default=None, max_length=2_048)
    logo_media_id: UUID | None = None
    active: bool | None = None
    sort_order: int | None = Field(default=None, ge=-100_000, le=100_000)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        return None if value is None else _required_text(value)

    @field_validator("description", "phone", "email", "website", "telegram")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return _optional_text(value)

    @field_validator("website")
    @classmethod
    def validate_website(cls, value: str | None) -> str | None:
        return _http_url(value)

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one Venue field is required")
        required = {"slug", "name", "active", "sort_order"}
        invalid_nulls = sorted(
            field
            for field in required
            if field in self.model_fields_set and getattr(self, field) is None
        )
        if invalid_nulls:
            raise ValueError(f"fields may not be null: {', '.join(invalid_nulls)}")
        return self


def venue_public_response(item: Venue) -> VenuePublicResponse:
    return VenuePublicResponse(
        id=item.id,
        slug=item.slug,
        name=item.name,
        description=item.description,
        phone=item.phone,
        email=item.email,
        website=item.website,
        telegram=item.telegram,
        logo_url=_media_url(item.logo_media_id),
        sort_order=item.sort_order,
    )


def venue_public_list_response(items: list[Venue]) -> VenuePublicListResponse:
    payload = [venue_public_response(item) for item in items]
    return VenuePublicListResponse(items=payload, page_size=len(payload), total=len(payload))


def venue_admin_response(item: Venue) -> VenueAdminResponse:
    public = venue_public_response(item)
    return VenueAdminResponse(
        **public.model_dump(),
        logo_media_id=item.logo_media_id,
        active=item.is_active,
        archived_at=item.archived_at,
    )


def venue_admin_list_response(
    page_record: VenuePage,
    *,
    page: int,
    page_size: int,
) -> VenueAdminListResponse:
    return VenueAdminListResponse(
        items=[venue_admin_response(item) for item in page_record.items],
        page=page,
        page_size=page_size,
        total=page_record.total,
    )


def _required_text(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("value must contain visible characters")
    return normalized


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _http_url(value: str | None) -> str | None:
    if value is not None and not value.lower().startswith(("https://", "http://")):
        raise ValueError("URL must use http or https")
    return value


def _media_url(media_id: UUID | None) -> str | None:
    return f"/api/v1/media/{media_id}" if media_id is not None else None
