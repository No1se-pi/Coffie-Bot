from __future__ import annotations

from app.bot.main import BotCommandService
from app.security.telegram import TelegramUserData


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
