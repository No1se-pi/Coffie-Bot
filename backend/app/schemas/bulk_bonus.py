"""Strict preview/confirm contracts for explainable bulk bonuses."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.services.bulk_bonus import BulkBonusOutcome, BulkBonusPreview


class ApiSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BulkBonusRequest(ApiSchema):
    # Empty means all currently eligible active customer profiles.
    customer_ids: set[UUID] = Field(default_factory=set, max_length=10000)
    points_per_user: int = Field(ge=1, le=1_000_000)
    reason: str = Field(min_length=3, max_length=2000)
    venue_id: UUID | None = None


class BulkBonusConfirmRequest(BulkBonusRequest):
    preview_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


class BulkBonusPreviewResponse(ApiSchema):
    customer_ids: list[UUID]
    recipient_count: int
    points_per_user: int
    total_points: int
    reason: str
    venue_id: UUID | None
    preview_hash: str


class BulkBonusItemResponse(ApiSchema):
    user_id: UUID
    operation_id: UUID
    points: int
    balance_before: int
    balance_after: int


class BulkBonusResponse(ApiSchema):
    id: UUID
    recipient_count: int
    points_per_user: int
    total_points: int
    reason: str
    venue_id: UUID | None
    created_at: datetime
    replay: bool
    items: list[BulkBonusItemResponse]


def preview_response(value: BulkBonusPreview) -> BulkBonusPreviewResponse:
    return BulkBonusPreviewResponse(
        customer_ids=list(value.customer_ids),
        recipient_count=value.recipient_count,
        points_per_user=value.points_per_user,
        total_points=value.total_points,
        reason=value.reason,
        venue_id=value.venue_id,
        preview_hash=value.preview_hash,
    )


def bulk_bonus_response(value: BulkBonusOutcome) -> BulkBonusResponse:
    return BulkBonusResponse(
        id=value.batch.id,
        recipient_count=value.batch.recipient_count,
        points_per_user=value.batch.points_per_user,
        total_points=value.batch.total_points,
        reason=value.batch.reason,
        venue_id=value.batch.venue_id,
        created_at=value.batch.created_at,
        replay=value.replay,
        items=[
            BulkBonusItemResponse(
                user_id=item.user_id,
                operation_id=item.operation_id,
                points=item.points,
                balance_before=item.balance_before,
                balance_after=item.balance_after,
            )
            for item in value.items
        ],
    )
