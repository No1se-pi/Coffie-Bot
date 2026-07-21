from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.enums import FeedbackCategory
from app.schemas.identity import TelegramAuthRequest
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
