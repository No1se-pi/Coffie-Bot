"""Transport contracts for customer identities and phone-only registration."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import IdentityProvider
from app.services.customers import CustomerIdentityView, PhoneCustomerResult


class ApiSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PhoneCustomerCreate(ApiSchema):
    phone: str = Field(min_length=5, max_length=64)
    display_name: str | None = Field(default=None, max_length=128)
    venue_id: UUID | None = None

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None


class PhoneCustomerResponse(ApiSchema):
    user_id: UUID
    card_id: UUID
    display_name: str
    masked_phone: str
    short_code: str
    points_balance: int
    idempotent_replay: bool


class CustomerIdentityResponse(ApiSchema):
    id: UUID
    provider: IdentityProvider
    subject: str
    verified: bool
    verified_at: datetime | None


class CustomerIdentityListResponse(ApiSchema):
    items: list[CustomerIdentityResponse]


def phone_customer_response(value: PhoneCustomerResult) -> PhoneCustomerResponse:
    return PhoneCustomerResponse(
        user_id=value.user_id,
        card_id=value.card_id,
        display_name=value.display_name,
        masked_phone=value.masked_phone,
        short_code=value.short_code,
        points_balance=value.points_balance,
        idempotent_replay=value.idempotent_replay,
    )


def customer_identity_list_response(
    values: tuple[CustomerIdentityView, ...],
) -> CustomerIdentityListResponse:
    return CustomerIdentityListResponse(
        items=[
            CustomerIdentityResponse(
                id=value.id,
                provider=value.provider,
                subject=value.subject,
                verified=value.verified,
                verified_at=value.verified_at,
            )
            for value in values
        ]
    )
