"""Human-readable Russian presentation for structured audit events."""

from __future__ import annotations

from collections.abc import Callable, Mapping
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

_DEFAULT_REWARD_NAME = "Награда"

_EVENT_LABELS = {
    # This is a structured event name, not a credential stored in source.
    "auth.password_failed": "Неудачная попытка входа по паролю",  # NOSONAR
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


def _participants(metadata: Mapping[str, Any]) -> tuple[str, str, str]:
    actor = _text(metadata, "actor_name", "Сотрудник")
    customer = _text(metadata, "customer_name", "клиенту")
    reason = _text(metadata, "reason", "причина не указана")
    return actor, customer, reason


def _format_points_accrued(metadata: Mapping[str, Any]) -> str:
    actor, customer, _ = _participants(metadata)
    points = _integer(metadata, "points")
    purchase = format_money_minor(_integer(metadata, "purchase_amount_minor"))
    return f"{actor}: {customer} начислено {points} баллов за покупку на {purchase}"


def _format_points_pending(metadata: Mapping[str, Any]) -> str:
    actor, customer, _ = _participants(metadata)
    points = _integer(metadata, "points")
    purchase = format_money_minor(_integer(metadata, "purchase_amount_minor"))
    return (
        f"{actor}: начисление {points} баллов для {customer} "
        f"за покупку на {purchase} ожидает подтверждения"
    )


def _format_points_redeemed(metadata: Mapping[str, Any]) -> str:
    actor, customer, _ = _participants(metadata)
    return f"{actor}: у пользователя {customer} списано {_integer(metadata, 'points')} баллов"


def _format_operation_reversed(metadata: Mapping[str, Any]) -> str:
    actor, _, reason = _participants(metadata)
    points = abs(_integer(metadata, "points"))
    return f"{actor}: отменена операция на {points} баллов. Причина: {reason}"


def _format_points_adjusted(metadata: Mapping[str, Any]) -> str:
    actor, customer, reason = _participants(metadata)
    delta = _integer(metadata, "delta_points")
    action = "добавлено" if delta >= 0 else "снято"
    return f"{actor}: пользователю {customer} {action} {abs(delta)} баллов. Причина: {reason}"


def _format_visit(metadata: Mapping[str, Any]) -> str:
    _, customer, _ = _participants(metadata)
    return f"{customer} получил(а) отметку посещения. Текущая серия: {_integer(metadata, 'streak')}"


def _format_stamp(metadata: Mapping[str, Any]) -> str:
    actor, customer, _ = _participants(metadata)
    return (
        f"{actor}: пользователю {customer} добавлен штамп. "
        f"Всего штампов: {_integer(metadata, 'stamps')}"
    )


def _format_reward_created(metadata: Mapping[str, Any]) -> str:
    _, customer, _ = _participants(metadata)
    reward = _text(metadata, "reward_name", _DEFAULT_REWARD_NAME)
    return f"{customer} получил(а) награду «{reward}»"


def _format_reward_redeemed(metadata: Mapping[str, Any]) -> str:
    actor, customer, _ = _participants(metadata)
    reward = _text(metadata, "reward_name", _DEFAULT_REWARD_NAME)
    return f"{actor}: для {customer} погашена награда «{reward}»"


def _format_reward_cancelled(metadata: Mapping[str, Any]) -> str:
    actor, customer, reason = _participants(metadata)
    reward = _text(metadata, "reward_name", _DEFAULT_REWARD_NAME)
    return f"{actor}: для {customer} отменена награда «{reward}». Причина: {reason}"


def _format_card_blocked(metadata: Mapping[str, Any]) -> str:
    actor, customer, reason = _participants(metadata)
    return f"{actor}: карта пользователя {customer} заблокирована. Причина: {reason}"


def _format_card_unblocked(metadata: Mapping[str, Any]) -> str:
    actor, customer, _ = _participants(metadata)
    return f"{actor}: карта пользователя {customer} разблокирована"


def _format_card_reissued(metadata: Mapping[str, Any]) -> str:
    actor, customer, _ = _participants(metadata)
    return f"{actor}: QR-карта пользователя {customer} перевыпущена"


def _format_tip_submitted(metadata: Mapping[str, Any]) -> str:
    actor, _, _ = _participants(metadata)
    return f"{actor}: изменения профиля чаевых отправлены на проверку"


def _format_broadcast_created(metadata: Mapping[str, Any]) -> str:
    actor, _, _ = _participants(metadata)
    return f"{actor}: создана рассылка «{_text(metadata, 'title', 'Без названия')}»"


def _format_promotion_published(metadata: Mapping[str, Any]) -> str:
    actor, _, _ = _participants(metadata)
    return f"{actor}: опубликована акция «{_text(metadata, 'title', 'Без названия')}»"


def _format_order_status(metadata: Mapping[str, Any]) -> str:
    previous = _status(metadata, "from")
    current = _status(metadata, "to")
    if previous and current:
        return f"Статус заказа изменён: «{previous}» → «{current}»"
    return "Статус заказа изменён"


def _format_courier_status(metadata: Mapping[str, Any]) -> str:
    current = _status(metadata, "status")
    if current:
        return f"Курьер изменил статус заказа: «{current}»"
    return "Курьер изменил статус заказа"


def _format_staff_role(metadata: Mapping[str, Any]) -> str:
    previous = _text(metadata, "previous_role", "")
    current = _text(metadata, "role", "")
    previous_label = _ROLE_LABELS.get(previous, previous)
    current_label = _ROLE_LABELS.get(current, current)
    if previous_label and current_label:
        return f"Роль сотрудника изменена: «{previous_label}» → «{current_label}»"
    return "Роль сотрудника изменена"


_EVENT_FORMATTERS: dict[str, Callable[[Mapping[str, Any]], str]] = {
    "points.accrued": _format_points_accrued,
    "points.accrual_pending": _format_points_pending,
    "points.redeemed": _format_points_redeemed,
    "operation.reversed": _format_operation_reversed,
    "points.adjusted": _format_points_adjusted,
    "visit.marked": _format_visit,
    "stamp.added": _format_stamp,
    "reward.created": _format_reward_created,
    "reward.redeemed": _format_reward_redeemed,
    "reward.cancelled": _format_reward_cancelled,
    "card.blocked": _format_card_blocked,
    "card.unblocked": _format_card_unblocked,
    "card.reissued": _format_card_reissued,
    "tip_profile.submitted": _format_tip_submitted,
    "broadcast.created": _format_broadcast_created,
    "promotion.published": _format_promotion_published,
    "order.status_changed": _format_order_status,
    "order.courier_status_changed": _format_courier_status,
    "staff.role_changed": _format_staff_role,
}


def format_audit_event(event_type: str, metadata: Mapping[str, Any]) -> str:
    """Render known structured event types with a safe forward-compatible fallback."""

    formatter = _EVENT_FORMATTERS.get(event_type)
    if formatter is not None:
        return formatter(metadata)

    known_label = _EVENT_LABELS.get(event_type)
    if known_label:
        return known_label

    label = _text(metadata, "label", "Системное событие")
    return f"{label} [{event_type}]"
