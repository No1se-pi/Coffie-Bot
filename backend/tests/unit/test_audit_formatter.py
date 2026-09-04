import pytest

from app.services.audit_formatter import format_audit_event, format_money_minor


def test_money_formatter_does_not_use_float() -> None:
    assert format_money_minor(46000) == "460 ₽"
    assert format_money_minor(123456) == "1\u00a0234,56 ₽"
    assert format_money_minor(-105) == "−1,05 ₽"


def test_points_accrual_is_human_readable() -> None:
    message = format_audit_event(
        "points.accrued",
        {
            "actor_name": "Екатерина",
            "customer_name": "Ярославу",
            "points": 46,
            "purchase_amount_minor": 46000,
        },
    )
    assert message == "Екатерина: Ярославу начислено 46 баллов за покупку на 460 ₽"


def test_reversal_contains_reason() -> None:
    message = format_audit_event(
        "operation.reversed",
        {"actor_name": "Администратор", "points": 46, "reason": "неверная сумма"},
    )
    assert "неверная сумма" in message


def test_unknown_event_has_safe_fallback() -> None:
    assert format_audit_event("future.event", {}) == "Системное событие [future.event]"


def test_order_transition_uses_russian_status_labels() -> None:
    assert (
        format_audit_event(
            "order.status_changed",
            {"from": "preparing", "to": "waiting_for_courier"},
        )
        == "Статус заказа изменён: «Готовится» → «Ожидает курьера»"
    )


def test_courier_and_subscription_events_have_human_labels() -> None:
    assert (
        format_audit_event("order.courier_status_changed", {"status": "in_transit"})
        == "Курьер изменил статус заказа: «В пути»"
    )
    assert (
        format_audit_event("subscription.purchase_confirmed", {})
        == "Покупка абонемента подтверждена сотрудником"
    )


def test_staff_role_change_uses_role_labels() -> None:
    assert (
        format_audit_event(
            "staff.role_changed",
            {"previous_role": "staff", "role": "courier"},
        )
        == "Роль сотрудника изменена: «Сотрудник» → «Курьер»"
    )


@pytest.mark.parametrize(
    ("event_type", "metadata", "expected_fragment"),
    [
        (
            "points.accrual_pending",
            {"points": 10, "purchase_amount_minor": 12_500},
            "ожидает подтверждения",
        ),
        ("points.redeemed", {"points": 20}, "списано 20 баллов"),
        ("points.adjusted", {"delta_points": -5}, "снято 5 баллов"),
        ("visit.marked", {"streak": 3}, "Текущая серия: 3"),
        ("stamp.added", {"stamps": 4}, "Всего штампов: 4"),
        ("reward.created", {"reward_name": "Кофе"}, "награду «Кофе»"),
        ("reward.redeemed", {"reward_name": "Кофе"}, "погашена награда «Кофе»"),
        (
            "reward.cancelled",
            {"reward_name": "Кофе", "reason": "ошибка"},
            "Причина: ошибка",
        ),
        ("card.blocked", {"reason": "проверка"}, "заблокирована"),
        ("card.unblocked", {}, "разблокирована"),
        ("card.reissued", {}, "QR-карта"),
        ("tip_profile.submitted", {}, "отправлены на проверку"),
        ("broadcast.created", {"title": "Новость"}, "рассылка «Новость»"),
        ("promotion.published", {"title": "Скидка"}, "акция «Скидка»"),
    ],
)
def test_specialized_audit_formatters(
    event_type: str,
    metadata: dict[str, object],
    expected_fragment: str,
) -> None:
    assert expected_fragment in format_audit_event(event_type, metadata)


def test_incomplete_status_metadata_has_readable_fallback() -> None:
    assert format_audit_event("order.status_changed", {}) == "Статус заказа изменён"
    assert format_audit_event("order.courier_status_changed", {}) == "Курьер изменил статус заказа"
    assert format_audit_event("staff.role_changed", {}) == "Роль сотрудника изменена"
