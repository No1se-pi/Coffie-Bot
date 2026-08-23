from __future__ import annotations

import pytest

from app.bot.main import BotCommandService, build_mini_app_keyboard
from app.security.telegram import TelegramUserData
from app.services.customers import VerifiedPhoneLinkResult

pytestmark = pytest.mark.asyncio


async def test_start_registers_through_injected_shared_use_case() -> None:
    calls: list[TelegramUserData] = []

    async def register(user: TelegramUserData) -> bool:
        calls.append(user)
        return True

    service = BotCommandService(register)
    user = TelegramUserData(id=123, first_name="Пользователь")

    reply = await service.start(user)

    assert calls == [user]
    assert "карта лояльности создана" in reply.text
    assert reply.show_mini_app is True


async def test_start_returns_existing_customer_copy() -> None:
    async def register(user: TelegramUserData) -> bool:
        assert user.id == 123
        return False

    reply = await BotCommandService(register).start(
        TelegramUserData(id=123, first_name="Пользователь")
    )

    assert reply.text.startswith("С возвращением!")
    assert BotCommandService(register).help().show_mini_app is True
    assert "Контакты" in BotCommandService(register).contact().text
    assert BotCommandService(register).menu().show_mini_app is True


async def test_human_menu_uses_only_mini_app_buttons_and_expected_routes() -> None:
    keyboard = build_mini_app_keyboard("https://coffee.example/")
    buttons = [button for row in keyboard.inline_keyboard for button in row]

    assert [button.text for button in buttons] == [
        "🏠 Главная",
        "💳 Моя карта",
        "☕ Меню",
        "🎁 Награды",
        "🧾 История",
        "ℹ️ Контакты",
    ]
    assert [button.web_app.url for button in buttons if button.web_app] == [
        "https://coffee.example/",
        "https://coffee.example/card",
        "https://coffee.example/menu",
        "https://coffee.example/rewards",
        "https://coffee.example/history",
        "https://coffee.example/more",
    ]
    assert all(button.url is None for button in buttons)


async def test_verified_phone_link_reply_does_not_expose_another_profile() -> None:
    async def register(_user: TelegramUserData) -> bool:
        return False

    async def link_phone(
        telegram_id: int,
        contact_user_id: int,
        phone_number: str,
    ) -> VerifiedPhoneLinkResult:
        assert (telegram_id, contact_user_id, phone_number) == (101, 101, "+79991234567")
        return VerifiedPhoneLinkResult(status="merge_required", masked_phone="+7*****4567")

    reply = await BotCommandService(register, link_phone).link_phone(
        telegram_id=101,
        contact_user_id=101,
        phone_number="+79991234567",
    )

    assert "без изменений" in reply.text
    assert "+79991234567" not in reply.text
