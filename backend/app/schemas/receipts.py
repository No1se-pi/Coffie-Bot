"""Strict staff receipt request/response contracts."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ReceiptSource, ReceiptStatus
from app.services.receipts import ReceiptView


class ApiSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReceiptCreateRequest(ApiSchema):
    user_id: UUID
    venue_id: UUID
    amount_minor: int = Field(gt=0, le=1_000_000_000)
    image_media_id: UUID
    receipt_number: str | None = Field(default=None, max_length=160)
    external_id: str | None = Field(default=None, max_length=160)
    fiscal_data: dict[str, Any] = Field(default_factory=dict)
    note: str | None = Field(default=None, max_length=2000)
    source: Literal[ReceiptSource.MANUAL] = ReceiptSource.MANUAL


class ReceiptEditRequest(ApiSchema):
    image_media_id: UUID | None
    receipt_number: str | None = Field(default=None, max_length=160)
    external_id: str | None = Field(default=None, max_length=160)
    fiscal_data: dict[str, Any] = Field(default_factory=dict)
    note: str | None = Field(default=None, max_length=2000)


class ReceiptRevisionResponse(ApiSchema):
    revision: int
    image_media_id: UUID | None
    receipt_number: str | None
    external_id: str | None
    fiscal_data: dict[str, Any]
    note: str | None
    changed_fields: list[str]
    created_at: datetime


class ReceiptRiskFlagResponse(ApiSchema):
    code: str
    details: dict[str, Any]
    created_at: datetime
    resolved_at: datetime | None


class ReceiptResponse(ApiSchema):
    id: UUID
    user_id: UUID
    customer_name: str
    venue_id: UUID
    venue_name: str
    amount_minor: int
    image_media_id: UUID | None
    source: ReceiptSource
    external_id: str | None
    receipt_number: str | None
    fiscal_data: dict[str, Any]
    note: str | None
    status: ReceiptStatus
    current_revision: int
    created_at: datetime
    updated_at: datetime
    idempotent_replay: bool
    revisions: list[ReceiptRevisionResponse]
    risk_flags: list[ReceiptRiskFlagResponse]


class ReceiptListResponse(ApiSchema):
    items: list[ReceiptResponse]


def receipt_response(value: ReceiptView) -> ReceiptResponse:
    item = value.receipt
    return ReceiptResponse(
        id=item.id,
        user_id=item.user_id,
        customer_name=value.customer_name,
        venue_id=item.venue_id,
        venue_name=value.venue_name,
        amount_minor=item.amount_minor,
        image_media_id=item.image_media_id,
        source=item.source,
        external_id=item.external_id,
        receipt_number=item.receipt_number,
        fiscal_data=item.fiscal_data,
        note=item.note,
        status=item.status,
        current_revision=item.current_revision,
        created_at=item.created_at,
        updated_at=item.updated_at,
        idempotent_replay=value.idempotent_replay,
        revisions=[
            ReceiptRevisionResponse(
                revision=revision.revision,
                image_media_id=revision.image_media_id,
                receipt_number=revision.receipt_number,
                external_id=revision.external_id,
                fiscal_data=revision.fiscal_data,
                note=revision.note,
                changed_fields=sorted(revision.change_summary),
                created_at=revision.created_at,
            )
            for revision in value.revisions
        ],
        risk_flags=[
            ReceiptRiskFlagResponse(
                code=flag.code,
                details=flag.details,
                created_at=flag.created_at,
                resolved_at=flag.resolved_at,
            )
            for flag in value.flags
        ],
    )
