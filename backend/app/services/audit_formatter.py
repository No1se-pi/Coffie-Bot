"""Human-readable Russian presentation for structured audit events."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _text(metadata: Mapping[str, Any], key: str, fallback: str) -> str:
    value = metadata.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def _integer(metadata: Mapping[str, Any], key: str, fallback: int = 0) -> int:
    value = metadata.get(key)
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int):
        return value
    return fallback


def format_money_minor(value: int, currency_symbol: str = "₽") -> str:
    """Format signed integer minor units without binary floating point."""

    sign = "−" if value < 0 else ""
    absolute = abs(value)
    major, minor = divmod(absolute, 100)
    grouped = f"{major:,}".replace(",", " ")
    amount = grouped if minor == 0 else f"{grouped},{minor:02d}"
    return f"{sign}{amount} {currency_symbol}"


def format_audit_event(event_type: str, metadata: Mapping[str, Any]) -> str:
    """Render known structured event types with a safe forward-compatible fallback."""

    actor = _text(metadata, "actor_name", "Сотрудник")
    customer = _text(metadata, "customer_name", "клиенту")
    reason = _text(metadata, "reason", "причина не указана")

    if event_type == "points.accrued":
        points = _integer(metadata, "points")
        purchase = format_money_minor(_integer(metadata, "purchase_amount_minor"))
        return f"{actor}: {customer} начислено {points} баллов за покупку на {purchase}"
    if event_type == "points.accrual_pending":
        points = _integer(metadata, "points")
        purchase = format_money_minor(_integer(metadata, "purchase_amount_minor"))
        return (
            f"{actor}: начисление {points} баллов для {customer} "
            f"за покупку на {purchase} ожидает подтверждения"
        )
    if event_type == "points.redeemed":
        points = _integer(metadata, "points")
        return f"{actor}: у пользователя {customer} списано {points} баллов"
    if event_type == "operation.reversed":
        points = abs(_integer(metadata, "points"))
        return f"{actor}: отменена операция на {points} баллов. Причина: {reason}"
    if event_type == "points.adjusted":
        delta = _integer(metadata, "delta_points")
        action = "добавлено" if delta >= 0 else "снято"
        return f"{actor}: пользователю {customer} {action} {abs(delta)} баллов. Причина: {reason}"
    if event_type == "visit.marked":
        streak = _integer(metadata, "streak")
        return f"{customer} получил(а) отметку посещения. Текущая серия: {streak}"
    if event_type == "stamp.added":
        stamps = _integer(metadata, "stamps")
        return f"{actor}: пользователю {customer} добавлен штамп. Всего штампов: {stamps}"
    if event_type == "reward.created":
        reward = _text(metadata, "reward_name", "Награда")
        return f"{customer} получил(а) награду «{reward}»"
    if event_type == "reward.redeemed":
        reward = _text(metadata, "reward_name", "Награда")
        return f"{actor}: для {customer} погашена награда «{reward}»"
    if event_type == "reward.cancelled":
        reward = _text(metadata, "reward_name", "Награда")
        return f"{actor}: для {customer} отменена награда «{reward}». Причина: {reason}"
    if event_type == "card.blocked":
        return f"{actor}: карта пользователя {customer} заблокирована. Причина: {reason}"
    if event_type == "card.unblocked":
        return f"{actor}: карта пользователя {customer} разблокирована"
    if event_type == "card.reissued":
        return f"{actor}: QR-карта пользователя {customer} перевыпущена"
    if event_type == "tip_profile.submitted":
        return f"{actor}: изменения профиля чаевых отправлены на проверку"
    if event_type == "broadcast.created":
        title = _text(metadata, "title", "Без названия")
        return f"{actor}: создана рассылка «{title}»"
    if event_type == "promotion.published":
        title = _text(metadata, "title", "Без названия")
        return f"{actor}: опубликована акция «{title}»"

    label = _text(metadata, "label", "Системное событие")
    return f"{label} [{event_type}]"
