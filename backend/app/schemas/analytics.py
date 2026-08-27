"""Privacy-safe aggregate DTOs for the owner/admin web panel."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.services.analytics import AnalyticsView, DashboardView


class ApiSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AdminDashboardResponse(ApiSchema):
    generated_at: datetime
    orders_today: int
    active_orders: int
    customers: int
    new_customers_today: int
    loyalty_accrual_today: int
    loyalty_redemption_today: int
    manual_receipts_today: int
    suspicious_events: int
    active_promotions: int
    reviews_waiting_moderation: int
    courier_orders: int


class DailyOrderMetric(ApiSchema):
    day: date
    orders: int
    revenue_minor: int


class NamedMetric(ApiSchema):
    id: UUID | None = None
    name: str
    count: int
    amount_minor: int = 0


class LoyaltyAnalytics(ApiSchema):
    accrued_points: int
    redeemed_points: int


class CustomerAnalytics(ApiSchema):
    active_customers: int
    repeat_customers: int


class SubscriptionAnalytics(ApiSchema):
    issued: int
    uses: int
    active: int


class ReceiptAnalytics(ApiSchema):
    created: int
    amount_minor: int
    suspicious: int


class DeliveryAnalytics(ApiSchema):
    orders: int
    completed: int
    cancelled: int


class AdminAnalyticsResponse(ApiSchema):
    generated_at: datetime
    days: int = Field(ge=7, le=90)
    started_at: datetime
    ended_at: datetime
    orders_by_day: list[DailyOrderMetric]
    orders_by_venue: list[NamedMetric]
    popular_items: list[NamedMetric]
    promotion_usage: list[NamedMetric]
    employee_activity: list[NamedMetric]
    loyalty: LoyaltyAnalytics
    customers: CustomerAnalytics
    subscriptions: SubscriptionAnalytics
    receipts: ReceiptAnalytics
    delivery: DeliveryAnalytics


def dashboard_response(value: DashboardView) -> AdminDashboardResponse:
    return AdminDashboardResponse(generated_at=value.generated_at, **value.values)


def analytics_response(value: AnalyticsView) -> AdminAnalyticsResponse:
    return AdminAnalyticsResponse(
        generated_at=value.generated_at,
        days=value.days,
        started_at=value.started_at,
        ended_at=value.ended_at,
        orders_by_day=[DailyOrderMetric.model_validate(item) for item in value.orders_by_day],
        orders_by_venue=[
            NamedMetric.model_validate(item) for item in value.values["orders_by_venue"]
        ],
        popular_items=[NamedMetric.model_validate(item) for item in value.values["popular_items"]],
        promotion_usage=[
            NamedMetric.model_validate(item) for item in value.values["promotion_usage"]
        ],
        employee_activity=[
            NamedMetric.model_validate(item) for item in value.values["employee_activity"]
        ],
        loyalty=LoyaltyAnalytics.model_validate(value.values["loyalty"]),
        customers=CustomerAnalytics.model_validate(value.values["customers"]),
        subscriptions=SubscriptionAnalytics.model_validate(value.values["subscriptions"]),
        receipts=ReceiptAnalytics.model_validate(value.values["receipts"]),
        delivery=DeliveryAnalytics.model_validate(value.values["delivery"]),
    )
