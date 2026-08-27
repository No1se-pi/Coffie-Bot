"""Read-only PostgreSQL aggregates for the web admin dashboard and analytics."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class AnalyticsRepository:
    """Keep analytical SQL isolated from HTTP and presentation code."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def clock_settings(self) -> tuple[str, int]:
        row = (
            (
                await self._session.execute(
                    text(
                        """
                    SELECT timezone, business_day_boundary_minutes
                    FROM loyalty_settings
                    WHERE singleton_key = 'default'
                    """
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return "Europe/Moscow", 0
        return str(row["timezone"]), int(row["business_day_boundary_minutes"])

    async def dashboard(
        self,
        *,
        started_at: datetime,
        ended_at: datetime,
        current_time: datetime,
    ) -> Mapping[str, Any]:
        row = (
            (
                await self._session.execute(
                    text(
                        """
                    SELECT
                      (SELECT count(*) FROM customer_orders
                       WHERE created_at >= :started_at AND created_at < :ended_at) AS orders_today,
                      (SELECT count(*) FROM customer_orders
                       WHERE status NOT IN ('delivered', 'cancelled')) AS active_orders,
                      (SELECT count(*) FROM users WHERE status <> 'merged') AS customers,
                      (SELECT count(*) FROM users
                       WHERE created_at >= :started_at AND created_at < :ended_at
                         AND status <> 'merged') AS new_customers_today,
                      (SELECT coalesce(sum(delta), 0) FROM point_transactions
                       WHERE created_at >= :started_at AND created_at < :ended_at
                         AND delta > 0) AS loyalty_accrual_today,
                      (SELECT coalesce(sum(-delta), 0) FROM point_transactions
                       WHERE created_at >= :started_at AND created_at < :ended_at
                         AND delta < 0) AS loyalty_redemption_today,
                      (SELECT count(*) FROM receipts
                       WHERE created_at >= :started_at AND created_at < :ended_at
                         AND source = 'manual') AS manual_receipts_today,
                      (SELECT count(*) FROM audit_events WHERE is_suspicious) AS suspicious_events,
                      (SELECT count(*) FROM promotions
                       WHERE status = 'published'
                         AND (starts_at IS NULL OR starts_at <= :current_time)
                         AND (ends_at IS NULL OR ends_at > :current_time)) AS active_promotions,
                      (SELECT count(*) FROM public_reviews
                       WHERE status = 'pending') AS reviews_waiting_moderation,
                      (SELECT count(*) FROM customer_orders
                       WHERE fulfillment_mode = 'delivery'
                         AND status NOT IN ('delivered', 'cancelled')) AS courier_orders
                    """
                    ),
                    {
                        "started_at": started_at,
                        "ended_at": ended_at,
                        "current_time": current_time,
                    },
                )
            )
            .mappings()
            .one()
        )
        return dict(row)

    async def analytics(
        self,
        *,
        started_at: datetime,
        ended_at: datetime,
        timezone_name: str,
    ) -> dict[str, Any]:
        parameters = {
            "started_at": started_at,
            "ended_at": ended_at,
            "timezone_name": timezone_name,
        }
        queries = {
            "orders_by_day": """
                SELECT (created_at AT TIME ZONE :timezone_name)::date AS day,
                       count(*) AS orders,
                       coalesce(sum(total_minor) FILTER (WHERE status <> 'cancelled'), 0)
                         AS revenue_minor
                FROM customer_orders
                WHERE created_at >= :started_at AND created_at < :ended_at
                GROUP BY day ORDER BY day
            """,
            "orders_by_venue": """
                SELECT v.id, v.name, count(*) AS count,
                       coalesce(sum(os.total_minor) FILTER (WHERE os.status <> 'cancelled'), 0)
                         AS amount_minor
                FROM order_suborders os
                JOIN customer_orders o ON o.id = os.order_id
                JOIN venues v ON v.id = os.venue_id
                WHERE o.created_at >= :started_at AND o.created_at < :ended_at
                GROUP BY v.id, v.name ORDER BY count DESC, v.name LIMIT 12
            """,
            "popular_items": """
                SELECT ol.menu_item_id AS id, ol.item_name AS name,
                       coalesce(sum(ol.quantity), 0) AS count,
                       coalesce(sum(ol.total_minor), 0) AS amount_minor
                FROM order_lines ol
                JOIN order_suborders os ON os.id = ol.suborder_id
                JOIN customer_orders o ON o.id = os.order_id
                WHERE o.created_at >= :started_at AND o.created_at < :ended_at
                  AND o.status <> 'cancelled'
                GROUP BY ol.menu_item_id, ol.item_name
                ORDER BY count DESC, ol.item_name LIMIT 12
            """,
            "promotion_usage": """
                SELECT oap.promotion_id AS id, oap.title AS name,
                       count(*) AS count, coalesce(sum(oap.discount_minor), 0) AS amount_minor
                FROM order_applied_promotions oap
                JOIN order_suborders os ON os.id = oap.suborder_id
                JOIN customer_orders o ON o.id = os.order_id
                WHERE o.created_at >= :started_at AND o.created_at < :ended_at
                  AND o.status <> 'cancelled'
                GROUP BY oap.promotion_id, oap.title
                ORDER BY count DESC, oap.title LIMIT 12
            """,
            "employee_activity": """
                SELECT sm.id,
                       coalesce(sm.display_name, u.first_name, u.username, 'Сотрудник') AS name,
                       count(*) AS count, 0::bigint AS amount_minor
                FROM audit_events ae
                JOIN staff_members sm ON sm.id = ae.actor_staff_id
                JOIN users u ON u.id = sm.user_id
                WHERE ae.created_at >= :started_at AND ae.created_at < :ended_at
                GROUP BY sm.id, sm.display_name, u.first_name, u.username
                ORDER BY count DESC, name LIMIT 12
            """,
            "loyalty": """
                SELECT coalesce(sum(delta) FILTER (WHERE delta > 0), 0) AS accrued_points,
                       coalesce(sum(-delta) FILTER (WHERE delta < 0), 0) AS redeemed_points
                FROM point_transactions
                WHERE created_at >= :started_at AND created_at < :ended_at
            """,
            "customers": """
                WITH activity AS (
                  SELECT user_id, count(*) AS orders
                  FROM customer_orders
                  WHERE created_at >= :started_at AND created_at < :ended_at
                    AND status <> 'cancelled'
                  GROUP BY user_id
                )
                SELECT count(*) AS active_customers,
                       count(*) FILTER (WHERE orders > 1) AS repeat_customers
                FROM activity
            """,
            "subscriptions": """
                SELECT
                  (SELECT count(*) FROM customer_passes
                   WHERE issued_at >= :started_at AND issued_at < :ended_at) AS issued,
                  (SELECT count(*) FROM pass_usages
                   WHERE created_at >= :started_at AND created_at < :ended_at) AS uses,
                  (SELECT count(*) FROM customer_passes
                   WHERE status = 'active' AND expires_at > :ended_at) AS active
            """,
            "receipts": """
                SELECT count(*) AS created, coalesce(sum(r.amount_minor), 0) AS amount_minor,
                       count(*) FILTER (WHERE EXISTS (
                         SELECT 1 FROM receipt_risk_flags rf
                         WHERE rf.receipt_id = r.id AND rf.resolved_at IS NULL
                       )) AS suspicious
                FROM receipts r
                WHERE r.created_at >= :started_at AND r.created_at < :ended_at
            """,
            "delivery": """
                SELECT count(*) AS orders,
                       count(*) FILTER (WHERE status = 'delivered') AS completed,
                       count(*) FILTER (WHERE status = 'cancelled') AS cancelled
                FROM customer_orders
                WHERE created_at >= :started_at AND created_at < :ended_at
                  AND fulfillment_mode = 'delivery'
            """,
        }
        result: dict[str, Any] = {}
        for name, query in queries.items():
            rows = (await self._session.execute(text(query), parameters)).mappings()
            result[name] = (
                list(rows)
                if name
                in {
                    "orders_by_day",
                    "orders_by_venue",
                    "popular_items",
                    "promotion_usage",
                    "employee_activity",
                }
                else rows.one()
            )
        return result
