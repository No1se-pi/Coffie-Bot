"""Human-readable Russian presentation for structured audit events."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_ORDER_STATUS_LABELS = {
    "new": "Новый",
    "confirmed": "Подтверждён",
    "preparing": "Готовится",
    "ready": "Готов к выдаче",
    "waiting_for_courier": "Ожидает курьера",
    "courier_assigned": "Курьер назначен",
    "picked_up": "Забран курьером",
    "in_transit": "В пути",
    "delivered": "Доставлен",
    "cancelled": "Отменён",
}

_ROLE_LABELS = {
    "customer": "Клиент",
    "staff": "Сотрудник",
    "courier": "Курьер",
    "admin": "Администратор",
    "owner": "Владелец",
}

_EVENT_LABELS = {
    "auth.password_failed": "Неудачная попытка входа по паролю",
    "broadcast.cancelled": "Рассылка отменена",
    "broadcast.confirmed": "Рассылка запущена",
    "card.blocked_attempt": "Попытка использовать заблокированную карту",
    "customer.created.phone": "Создан профиль клиента по номеру телефона",
    "customer.internal_note_updated": "Изменена внутренняя заметка клиента",
    "customer.merged": "Профили клиентов объединены",
    "customer.phone_link.confirmed": "Номер телефона клиента подтверждён",
    "customer.phone_link.merge_required": "Для номера телефона требуется объединение профилей",
    "customer.phone_linked": "Номер телефона привязан к клиенту",
    "delivery.location_created": "Создана физическая точка",
    "delivery.location_updated": "Настройки физической точки изменены",
    "delivery.settings_updated": "Настройки доставки изменены",
    "delivery.zone_archived": "Зона доставки отправлена в архив",
    "delivery.zone_created": "Создана зона доставки",
    "delivery.zone_updated": "Зона доставки изменена",
    "feedback.created": "Клиент оставил отзыв",
    "feedback.deleted": "Отзыв удалён",
    "feedback.updated": "Статус отзыва изменён",
    "loyalty.settings_updated": "Основные настройки лояльности изменены",
    "loyalty.v2_settings_updated": "Расширенные настройки лояльности изменены",
    "media.uploaded": "Загружен медиафайл",
    "menu.category_created": "Создана категория меню",
    "menu.category_hidden": "Категория меню скрыта",
    "menu.category_updated": "Категория меню изменена",
    "menu.item_archived": "Позиция меню отправлена в архив",
    "menu.item_created": "Создана позиция меню",
    "menu.item_deleted": "Позиция меню удалена",
    "menu.item_restored": "Позиция меню восстановлена",
    "menu.item_updated": "Позиция меню изменена",
    "order.courier_claimed": "Курьер принял заказ",
    "order.courier_declined": "Курьер отказался от заказа",
    "order.courier_reassigned": "Для заказа изменён курьер",
    "order.courier_released": "Курьер снят с заказа",
    "order.courier_status_changed": "Курьер изменил статус заказа",
    "promotion.archived": "Акция отправлена в архив",
    "promotion.created": "Создана акция",
    "promotion.deleted": "Акция удалена",
    "promotion.restored": "Акция восстановлена",
    "promotion.updated": "Акция изменена",
    "review.moderated": "Отзыв прошёл модерацию",
    "staff.archived": "Сотрудник отправлен в архив",
    "staff.created": "Создан сотрудник",
    "staff.invite_created": "Создано приглашение сотрудника",
    "staff.restored": "Сотрудник восстановлен",
    "staff.sessions_revoked": "Сессии сотрудника завершены",
    "staff.updated": "Данные сотрудника изменены",
    "subscription.cancelled": "Абонемент клиента отменён",
    "subscription.issued": "Клиенту выдан абонемент",
    "subscription.purchase_confirmed": "Покупка абонемента подтверждена сотрудником",
    "subscription.purchase_created": "Клиент оформил покупку абонемента",
    "subscription.template_archived": "Абонемент отправлен в архив",
    "subscription.template_created": "Создан абонемент",
    "subscription.template_restored": "Абонемент восстановлен из архива",
    "subscription.template_updated": "Настройки абонемента изменены",
    "subscription.used": "Использование абонемента подтверждено",
    "tip_profile.approved": "Профиль чаевых одобрен",
    "tip_profile.hidden": "Профиль чаевых скрыт",
    "tip_profile.review_cancelled": "Проверка профиля чаевых отменена",
    "venue.archived": "Заведение отправлено в архив",
    "venue.created": "Создано заведение",
    "venue.restored": "Заведение восстановлено",
    "venue.updated": "Настройки заведения изменены",
}


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


def _status(metadata: Mapping[str, Any], key: str) -> str:
    value = _text(metadata, key, "")
    return _ORDER_STATUS_LABELS.get(value, value.replace("_", " "))


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
    if event_type == "order.status_changed":
        previous = _status(metadata, "from")
        current = _status(metadata, "to")
        if previous and current:
            return f"Статус заказа изменён: «{previous}» → «{current}»"
        return "Статус заказа изменён"
    if event_type == "order.courier_status_changed":
        current = _status(metadata, "status")
        return (
            f"Курьер изменил статус заказа: «{current}»"
            if current
            else "Курьер изменил статус заказа"
        )
    if event_type == "staff.role_changed":
        previous = _text(metadata, "previous_role", "")
        current = _text(metadata, "role", "")
        previous_label = _ROLE_LABELS.get(previous, previous)
        current_label = _ROLE_LABELS.get(current, current)
        if previous_label and current_label:
            return f"Роль сотрудника изменена: «{previous_label}» → «{current_label}»"
        return "Роль сотрудника изменена"

    known_label = _EVENT_LABELS.get(event_type)
    if known_label:
        return known_label

    label = _text(metadata, "label", "Системное событие")
    return f"{label} [{event_type}]"
