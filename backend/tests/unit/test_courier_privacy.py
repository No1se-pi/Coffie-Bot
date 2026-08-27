"""Courier serialization must preserve the pre-claim privacy boundary."""

from datetime import UTC, datetime
from uuid import uuid4

from app.models.access import User
from app.models.enums import FulfillmentMode, OrderStatus, PaymentMethod, PaymentStatus, UserStatus
from app.models.orders import CustomerOrder
from app.schemas.couriers import courier_order_response
from app.services.couriers import CourierOrderView


def _order() -> CustomerOrder:
    return CustomerOrder(
        id=uuid4(),
        number=42,
        user_id=uuid4(),
        fulfillment_mode=FulfillmentMode.DELIVERY,
        status=OrderStatus.WAITING_FOR_COURIER,
        status_version=1,
        idempotency_key="privacy-test",
        request_hash="0" * 64,
        contact_phone="+79990000000",
        delivery_address="Секретный адрес",
        customer_comment="Позвонить",
        subtotal_minor=100,
        promotion_discount_minor=0,
        points_discount_minor=0,
        delivery_fee_minor=0,
        total_minor=100,
        payment_method=PaymentMethod.CASH,
        payment_status=PaymentStatus.UNPAID,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def test_available_order_hides_customer_fields() -> None:
    response = courier_order_response(
        CourierOrderView(order=_order(), customer=None, venue_names=("Кофейня",))
    )

    assert response.contact_phone is None
    assert response.delivery_address is None
    assert response.customer_name is None
    assert "telegram_id" not in response.model_dump()
    assert "internal_note" not in response.model_dump()


def test_assigned_order_exposes_only_delivery_contact() -> None:
    order = _order()
    customer = User(
        id=order.user_id,
        telegram_id=123456,
        first_name="Анна",
        internal_note="Никогда не показывать курьеру",
        birthday_month=1,
        birthday_day=1,
        birthday_set_at=datetime.now(UTC),
        status=UserStatus.ACTIVE,
    )
    dumped = courier_order_response(
        CourierOrderView(order=order, customer=customer, venue_names=("Кофейня",))
    ).model_dump()

    assert dumped["customer_name"] == "Анна"
    assert dumped["contact_phone"] == "+79990000000"
    assert "telegram_id" not in dumped
    assert "birthday_month" not in dumped
    assert "internal_note" not in dumped
