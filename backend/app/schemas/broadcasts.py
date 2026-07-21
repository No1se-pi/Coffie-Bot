"""Strict request and response contracts for broadcast administration."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import BroadcastStatus
from app.repositories.admin_broadcasts import (
    BroadcastPageRecord,
    BroadcastRecord,
    BroadcastTransitionRecord,
)
from app.services.admin_broadcasts import BroadcastDraft


class ApiSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BroadcastAudience(ApiSchema):
    mode: Literal["all_active", "selected"] = "all_active"
    user_ids: list[UUID] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_selection(self) -> BroadcastAudience:
        if self.mode == "selected" and not self.user_ids:
            raise ValueError("user_ids is required for a selected audience")
        if self.mode == "all_active" and self.user_ids:
            raise ValueError("user_ids is only valid for a selected audience")
        if len(set(self.user_ids)) != len(self.user_ids):
            raise ValueError("user_ids must not contain duplicates")
        return self

    def storage_value(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "user_ids": [str(value) for value in self.user_ids],
        }


class BroadcastDraftRequest(ApiSchema):
    title: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=1024)
    image_media_id: UUID | None = None
    button_label: str | None = Field(default=None, min_length=1, max_length=80)
    button_url: str | None = Field(default=None, max_length=2048)
    audience: BroadcastAudience = Field(default_factory=BroadcastAudience)

    @field_validator("title", "message", "button_label")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_button(self) -> BroadcastDraftRequest:
        if bool(self.button_label) != bool(self.button_url):
            raise ValueError("button_label and button_url must be provided together")
        if self.button_url is not None:
            parsed = urlsplit(self.button_url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username:
                raise ValueError("button_url must be an absolute HTTPS URL")
        return self

    def as_draft(self) -> BroadcastDraft:
        return BroadcastDraft(
            title=self.title,
            message=self.message,
            image_media_id=self.image_media_id,
            button_label=self.button_label,
            button_url=self.button_url,
            audience_filter=self.audience.storage_value(),
        )


class BroadcastCancelRequest(ApiSchema):
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 3:
            raise ValueError("reason must contain at least 3 non-space characters")
        return normalized


class BroadcastPreviewResponse(ApiSchema):
    audience_count: int


class BroadcastResponse(ApiSchema):
    id: UUID
    title: str
    message: str
    image_media_id: UUID | None
    button_label: str | None
    button_url: str | None
    audience: BroadcastAudience
    status: BroadcastStatus
    success_count: int
    failure_count: int
    skipped_count: int
    created_at: datetime
    updated_at: datetime
    confirmed_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None


class BroadcastListResponse(ApiSchema):
    items: list[BroadcastResponse]
    page: int
    page_size: int
    total: int


class BroadcastTransitionResponse(ApiSchema):
    broadcast: BroadcastResponse
    recipient_count: int


def broadcast_response(record: BroadcastRecord) -> BroadcastResponse:
    return BroadcastResponse(
        id=record.id,
        title=record.title,
        message=record.message,
        image_media_id=record.image_media_id,
        button_label=record.button_label,
        button_url=record.button_url,
        audience=BroadcastAudience.model_validate(record.audience_filter),
        status=record.status,
        success_count=record.success_count,
        failure_count=record.failure_count,
        skipped_count=record.skipped_count,
        created_at=record.created_at,
        updated_at=record.updated_at,
        confirmed_at=record.confirmed_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
    )


def broadcast_page_response(
    record: BroadcastPageRecord,
    *,
    page: int,
    page_size: int,
) -> BroadcastListResponse:
    return BroadcastListResponse(
        items=[broadcast_response(item) for item in record.items],
        page=page,
        page_size=page_size,
        total=record.total,
    )


def broadcast_transition_response(
    record: BroadcastTransitionRecord,
) -> BroadcastTransitionResponse:
    return BroadcastTransitionResponse(
        broadcast=broadcast_response(record.broadcast),
        recipient_count=record.recipient_count,
    )
