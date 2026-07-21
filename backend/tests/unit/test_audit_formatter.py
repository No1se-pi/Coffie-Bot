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
