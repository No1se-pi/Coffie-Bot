"""aiogram long-polling process for customer entry commands."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import Database, create_database
from app.repositories.identity import IdentityRepository
from app.security.telegram import TelegramUserData
from app.services.identity import IdentityService

logger = get_logger(__name__)
RegisterTelegramUser = Callable[[TelegramUserData], Awaitable[bool]]


@dataclass(frozen=True, slots=True)
class CommandReply:
    text: str
    show_mini_app: bool = False


class BotCommandService:
    """Transport-independent command copy and shared registration invocation."""

    def __init__(self, register_user: RegisterTelegramUser) -> None:
        self._register_user = register_user

    async def start(self, telegram_user: TelegramUserData) -> CommandReply:
        created = await self._register_user(telegram_user)
        if created:
            text = "Готово — карта лояльности создана. Откройте приложение, чтобы увидеть её."
        else:
            text = "С возвращением! Ваша карта лояльности доступна в приложении."
        return CommandReply(text=text, show_mini_app=True)

    def help(self) -> CommandReply:
        return CommandReply(
            text=(
                "Доступные команды:\n"
                "/start — зарегистрироваться или открыть карту\n"
                "/contact — посмотреть контакты организации\n"
                "/help — показать эту справку"
            ),
            show_mini_app=True,
        )

    def contact(self) -> CommandReply:
        return CommandReply(
            text="Контакты организации доступны в приложении.",
            show_mini_app=True,
        )


def build_dispatcher(
    command_service: BotCommandService,
    *,
    webapp_url: str | None,
) -> Dispatcher:
    router = Router(name="entry_commands")

    @router.message(CommandStart())
    async def start_handler(message: Message) -> None:
        if message.from_user is None:
            await message.answer("Не удалось определить пользователя Telegram. Попробуйте ещё раз.")
            return
        telegram_user = TelegramUserData(
            id=message.from_user.id,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            username=message.from_user.username,
            language_code=message.from_user.language_code,
            is_bot=message.from_user.is_bot,
            is_premium=bool(message.from_user.is_premium),
        )
        try:
            reply = await command_service.start(telegram_user)
        except Exception:
            logger.exception("bot_registration_failed")
            await message.answer("Не удалось завершить регистрацию. Попробуйте немного позже.")
            return
        await _answer(message, reply, webapp_url=webapp_url)

    @router.message(Command("help"))
    async def help_handler(message: Message) -> None:
        await _answer(message, command_service.help(), webapp_url=webapp_url)

    @router.message(Command("contact"))
    async def contact_handler(message: Message) -> None:
        await _answer(message, command_service.contact(), webapp_url=webapp_url)

    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher


async def run_bot(settings: Settings) -> None:
    token = settings.bot_token.get_secret_value() if settings.bot_token else None
    if not token:
        raise RuntimeError("BOT_TOKEN is required to run the bot")
    database = create_database(settings)
    bot = Bot(token=token)

    async def register_user(telegram_user: TelegramUserData) -> bool:
        return await _register_with_shared_service(database, settings, telegram_user)

    command_service = BotCommandService(register_user)
    dispatcher = build_dispatcher(
        command_service,
        webapp_url=settings.telegram_webapp_url,
    )
    try:
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Открыть карту лояльности"),
                BotCommand(command="contact", description="Контакты организации"),
                BotCommand(command="help", description="Справка"),
            ]
        )
        await bot.delete_webhook(drop_pending_updates=False)
        logger.info("bot_started")
        await dispatcher.start_polling(
            bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
    finally:
        await bot.session.close()
        await database.engine.dispose()
        logger.info("bot_stopped")


async def _register_with_shared_service(
    database: Database,
    settings: Settings,
    telegram_user: TelegramUserData,
) -> bool:
    async with database.session_factory() as session:
        result = await IdentityService(
            settings=settings,
            repository=IdentityRepository(session),
        ).register_telegram_user(telegram_user)
    return result.created


async def _answer(
    message: Message,
    reply: CommandReply,
    *,
    webapp_url: str | None,
) -> None:
    markup = None
    if reply.show_mini_app and webapp_url:
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Открыть приложение",
                        web_app=WebAppInfo(url=webapp_url),
                    )
                ]
            ]
        )
    await message.answer(reply.text, reply_markup=markup)


def main() -> int:
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.log_json)
    try:
        asyncio.run(run_bot(settings))
    except KeyboardInterrupt:
        return 130
    except Exception:
        get_logger(__name__).exception("bot_startup_failed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
