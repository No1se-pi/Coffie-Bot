"""Strict API contracts for public reviews and moderation."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import ReviewStatus
from app.repositories.reviews import ReviewRecord


class ApiSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewCreateRequest(ApiSchema):
    venue_id: UUID
    order_id: UUID | None = None
    employee_staff_id: UUID | None = None
    rating: int = Field(ge=1, le=5)
    text: str = Field(min_length=3, max_length=4000)
    author_display_name: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("text", "author_display_name")
    @classmethod
    def normalize(cls, value: str | None) -> str | None:
        return " ".join(value.split()) if value is not None else None


class ReviewModerateRequest(ApiSchema):
    status: ReviewStatus
    moderation_note: str | None = Field(default=None, max_length=2000)


class ReviewResponse(ApiSchema):
    id: UUID
    venue_id: UUID
    venue_name: str
    order_id: UUID | None
    employee_staff_id: UUID | None
    employee_name: str | None
    rating: int
    text: str
    author_display_name: str
    status: ReviewStatus
    moderation_note: str | None = None
    created_at: datetime
    moderated_at: datetime | None = None


class ReviewListResponse(ApiSchema):
    items: list[ReviewResponse]


def review_response(record: ReviewRecord, *, include_moderation: bool) -> ReviewResponse:
    value = record.review
    return ReviewResponse(
        id=value.id,
        venue_id=value.venue_id,
        venue_name=record.venue_name,
        order_id=value.order_id,
        employee_staff_id=value.employee_staff_id,
        employee_name=record.employee_name,
        rating=value.rating,
        text=value.text,
        author_display_name=value.author_display_name,
        status=value.status,
        moderation_note=value.moderation_note if include_moderation else None,
        created_at=value.created_at,
        moderated_at=value.moderated_at if include_moderation else None,
    )
