"""Strict request/response contracts for previewed customer account merges."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import IdentityProvider, Role, UserStatus
from app.services.customer_merges import (
    CustomerMergePreview,
    CustomerMergeResult,
    MergeProfilePreview,
)


class ApiSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CustomerMergePreviewRequest(ApiSchema):
    source_user_id: UUID
    canonical_user_id: UUID


class CustomerMergeConfirmRequest(CustomerMergePreviewRequest):
    preview_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: str = Field(min_length=3, max_length=2_000)
    confirm: Literal[True]
    birthday_resolution: Literal["keep_canonical", "use_source"] | None = None

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 3:
            raise ValueError("reason must contain at least three visible characters")
        return normalized


class CustomerMergeProfileResponse(ApiSchema):
    user_id: UUID
    display_name: str
    status: UserStatus
    identity_providers: list[IdentityProvider]
    points_balance: int
    stamp_count: int
    visit_streak: int
    last_visit_business_date: date | None
    staff_role: Role | None
    birthday_set: bool


class CustomerMergePreviewResponse(ApiSchema):
    source: CustomerMergeProfileResponse
    canonical: CustomerMergeProfileResponse
    preview_hash: str
    points_to_transfer: int
    stamps_to_transfer: int
    visit_snapshot_from_user_id: UUID | None
    identities_to_move: int
    rewards_to_move: int
    sessions_to_revoke: int
    cards_to_revoke: int
    feedback_to_move: int
    source_staff_rebound: bool
    birthday_conflict: bool
    birthday_resolution_required: bool


class CustomerMergeConfirmResponse(ApiSchema):
    merge_id: UUID
    source_user_id: UUID
    canonical_user_id: UUID
    preview_hash: str
    completed_at: datetime
    points_transferred: int
    canonical_points_after: int
    stamps_transferred: int
    canonical_stamps_after: int
    visit_snapshot_from_user_id: UUID | None
    identities_moved: int
    rewards_moved: int
    sessions_revoked: int
    cards_revoked: int
    feedback_moved: int
    birthday_resolution: Literal["keep_canonical", "use_source"] | None
    source_staff_rebound: bool
    idempotent_replay: bool


def customer_merge_preview_response(
    preview: CustomerMergePreview,
) -> CustomerMergePreviewResponse:
    return CustomerMergePreviewResponse(
        source=_profile_response(preview.source),
        canonical=_profile_response(preview.canonical),
        preview_hash=preview.preview_hash,
        points_to_transfer=preview.points_to_transfer,
        stamps_to_transfer=preview.stamps_to_transfer,
        visit_snapshot_from_user_id=preview.visit_snapshot_from_user_id,
        identities_to_move=preview.identities_to_move,
        rewards_to_move=preview.rewards_to_move,
        sessions_to_revoke=preview.sessions_to_revoke,
        cards_to_revoke=preview.cards_to_revoke,
        feedback_to_move=preview.feedback_to_move,
        source_staff_rebound=preview.source_staff_rebound,
        birthday_conflict=preview.birthday_conflict,
        birthday_resolution_required=preview.birthday_resolution_required,
    )


def customer_merge_confirm_response(
    result: CustomerMergeResult,
) -> CustomerMergeConfirmResponse:
    merge = result.merge
    return CustomerMergeConfirmResponse(
        merge_id=merge.id,
        source_user_id=merge.source_user_id,
        canonical_user_id=merge.canonical_user_id,
        preview_hash=merge.preview_hash,
        completed_at=merge.completed_at,
        points_transferred=merge.points_transferred,
        canonical_points_after=merge.canonical_points_after,
        stamps_transferred=merge.stamps_transferred,
        canonical_stamps_after=merge.canonical_stamps_after,
        visit_snapshot_from_user_id=merge.visit_snapshot_from_user_id,
        identities_moved=merge.identities_moved,
        rewards_moved=merge.rewards_moved,
        sessions_revoked=merge.sessions_revoked,
        cards_revoked=merge.cards_revoked,
        feedback_moved=merge.feedback_moved,
        birthday_resolution=merge.birthday_resolution,
        source_staff_rebound=merge.source_staff_rebound,
        idempotent_replay=result.idempotent_replay,
    )


def _profile_response(profile: MergeProfilePreview) -> CustomerMergeProfileResponse:
    return CustomerMergeProfileResponse(
        user_id=profile.user_id,
        display_name=profile.display_name,
        status=profile.status,
        identity_providers=list(profile.identity_providers),
        points_balance=profile.points_balance,
        stamp_count=profile.stamp_count,
        visit_streak=profile.visit_streak,
        last_visit_business_date=profile.last_visit_business_date,
        staff_role=profile.staff_role,
        birthday_set=profile.birthday_set,
    )
