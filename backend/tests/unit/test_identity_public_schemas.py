from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.enums import (
    FeedbackCategory,
    LoyaltyOperationType,
    OperationStatus,
)
from app.models.loyalty import LoyaltyOperation
from app.repositories.identity import HistoryPageRecord
from app.schemas.identity import TelegramAuthRequest, history_response
from app.schemas.public import FeedbackRequest, contacts_response


def test_auth_request_forbids_frontend_identity_fields() -> None:
    with pytest.raises(ValidationError):
        TelegramAuthRequest.model_validate({})

    with pytest.raises(ValidationError):
        TelegramAuthRequest.model_validate(
            {
                "init_data": "signed",
                "telegram_id": 42,
                "role": "owner",
            }
        )


def test_feedback_normalizes_whitespace_and_rejects_excess_fields() -> None:
    request = FeedbackRequest(
        rating=5,
        category=FeedbackCategory.SERVICE,
        message="  Всё   отлично!  ",
        may_contact=True,
    )

    assert request.message == "Всё отлично!"
    with pytest.raises(ValidationError):
        FeedbackRequest.model_validate(
            {
                "rating": 5,
                "category": "service",
                "message": "Хорошо",
                "user_id": str(uuid4()),
            }
        )


def test_contacts_use_only_public_settings_with_neutral_fallbacks() -> None:
    response = contacts_response(
        {
            "brand": {"name": "Тестовая кофейня", "welcome_text": "Добро пожаловать"},
            "contacts": {"telegram": "https://t.me/example"},
        },
        [],
    )

    assert response.coffee_shop_name == "Тестовая кофейня"
    assert response.description == "Добро пожаловать"
    assert response.support_contact == "https://t.me/example"
    assert response.locations == []


@pytest.mark.parametrize("operation_type", list(LoyaltyOperationType))
def test_every_loyalty_operation_type_has_a_public_history_description(
    operation_type: LoyaltyOperationType,
) -> None:
    occurred_at = datetime(2026, 8, 1, 12, tzinfo=UTC)
    operation = LoyaltyOperation(
        id=uuid4(),
        user_id=uuid4(),
        operation_type=operation_type,
        status=OperationStatus.COMMITTED,
        idempotency_key=f"history-{operation_type.value}",
        request_hash="hash",
        points_delta=-100 if operation_type is LoyaltyOperationType.POINTS_PRODUCT_PURCHASE else 0,
        balance_after=200,
        occurred_at=occurred_at,
    )

    response = history_response(
        HistoryPageRecord(items=[operation], total=1),
        page=1,
        page_size=20,
    )

    assert response.items[0].description
    if operation_type is LoyaltyOperationType.POINTS_PRODUCT_PURCHASE:
        assert response.items[0].description == "Покупка за баллы"
