"""aiogram long-polling process for customer entry commands."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    MenuButtonWebApp,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    WebAppInfo,
)

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import Database, create_database
from app.repositories.customer_merges import CustomerMergeRepository
from app.repositories.customers import CustomerRepository
from app.repositories.identity import IdentityRepository
from app.security.telegram import TelegramUserData
from app.services.customer_merges import CustomerMergeService
from app.services.customers import (
    CustomerService,
    VerifiedPhoneLinkCoordinator,
    VerifiedPhoneLinkResult,
)
from app.services.identity import IdentityService

logger = get_logger(__name__)
RegisterTelegramUser = Callable[[TelegramUserData], Awaitable[bool]]
LinkVerifiedPhone = Callable[[int, int, str], Awaitable[VerifiedPhoneLinkResult]]


@dataclass(frozen=True, slots=True)
class CommandReply:
    text: str
    show_mini_app: bool = False


class BotCommandService:
    """Transport-independent command copy and shared registration invocation."""

    def __init__(
        self,
        register_user: RegisterTelegramUser,
        link_phone: LinkVerifiedPhone | None = None,
    ) -> None:
        self._register_user = register_user
        self._link_phone = link_phone

    async def start(self, telegram_user: TelegramUserData) -> CommandReply:
        created = await self._register_user(telegram_user)
        if created:
            text = "Готово — ваш QR создан. Откройте приложение, чтобы показать его."
        else:
            text = "С возвращением! Ваш QR доступен в приложении."
        return CommandReply(text=text, show_mini_app=True)

    def help(self) -> CommandReply:
        return CommandReply(
            text=(
                "Доступные команды:\n"
                "/start — зарегистрироваться или открыть мой QR\n"
                "/menu — открыть меню приложения\n"
                "/phone — подтвердить свой номер телефона\n"
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

    def menu(self) -> CommandReply:
        return CommandReply(
            text="Выберите нужный раздел приложения.",
            show_mini_app=True,
        )

    async def link_phone(
        self,
        *,
        telegram_id: int,
        contact_user_id: int,
        phone_number: str,
    ) -> CommandReply:
        if self._link_phone is None:
            return CommandReply("Привязка телефона временно недоступна.")
        result = await self._link_phone(telegram_id, contact_user_id, phone_number)
        if result.status == "merge_required":
            return CommandReply(
                "Этот номер уже относится к другой карте. Данные сохранены без изменений; "
                "обратитесь к администратору для безопасного объединения профилей."
            )
        if result.status == "merged":
            transferred = (
                f" Перенесено баллов: {result.points_transferred}."
                if result.points_transferred > 0
                else ""
            )
            return CommandReply(
                f"Номер {result.masked_phone} подтверждён. Профили и история объединены."
                f"{transferred}"
            )
        if result.status == "already_linked":
            return CommandReply(f"Номер {result.masked_phone} уже подтверждён.")
        return CommandReply(f"Номер {result.masked_phone} подтверждён и привязан.")


def build_dispatcher(
    command_service: BotCommandService,
    *,
    webapp_url: str | None,
) -> Dispatcher:
    router = Router(name="entry_commands")
    router.message.filter(F.chat.type == ChatType.PRIVATE)

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
    async def organization_contact_handler(message: Message) -> None:
        await _answer(message, command_service.contact(), webapp_url=webapp_url)

    @router.message(Command("menu"))
    async def menu_handler(message: Message) -> None:
        await _answer(message, command_service.menu(), webapp_url=webapp_url)

    @router.message(Command("phone"))
    async def phone_handler(message: Message) -> None:
        # Telegram fills this button with an authenticated Contact object; a
        # manually typed phone number never enters the verified linking flow.
        await message.answer(
            "Нажмите кнопку ниже, чтобы подтвердить собственный номер Telegram.",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="Подтвердить мой номер", request_contact=True)]],
                resize_keyboard=True,
                one_time_keyboard=True,
            ),
        )

    @router.message(F.contact)
    async def verified_contact_handler(message: Message) -> None:
        if message.from_user is None or message.contact is None:
            await message.answer(
                "Не удалось проверить контакт.",
                reply_markup=ReplyKeyboardRemove(),
            )
            return
        contact_user_id = message.contact.user_id
        if contact_user_id is None:
            await message.answer(
                "Отправьте номер именно кнопкой «Подтвердить мой номер».",
                reply_markup=ReplyKeyboardRemove(),
            )
            return
        try:
            reply = await command_service.link_phone(
                telegram_id=message.from_user.id,
                contact_user_id=contact_user_id,
                phone_number=message.contact.phone_number,
            )
        except Exception:
            logger.exception("bot_phone_link_failed")
            await message.answer(
                "Не удалось подтвердить номер. Попробуйте позже.",
                reply_markup=ReplyKeyboardRemove(),
            )
            return
        await message.answer(reply.text, reply_markup=ReplyKeyboardRemove())

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

    async def link_phone(
        telegram_id: int,
        contact_user_id: int,
        phone_number: str,
    ) -> VerifiedPhoneLinkResult:
        return await _link_phone_with_shared_service(
            database,
            telegram_id=telegram_id,
            contact_user_id=contact_user_id,
            phone_number=phone_number,
        )

    command_service = BotCommandService(register_user, link_phone)
    dispatcher = build_dispatcher(
        command_service,
        webapp_url=settings.telegram_webapp_url,
    )
    try:
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Открыть мой QR"),
                BotCommand(command="menu", description="Меню приложения"),
                BotCommand(command="phone", description="Подтвердить номер телефона"),
                BotCommand(command="contact", description="Контакты организации"),
                BotCommand(command="help", description="Справка"),
            ]
        )
        if settings.telegram_webapp_url:
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="Открыть приложение",
                    web_app=WebAppInfo(url=settings.telegram_webapp_url),
                )
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


async def _link_phone_with_shared_service(
    database: Database,
    *,
    telegram_id: int,
    contact_user_id: int,
    phone_number: str,
) -> VerifiedPhoneLinkResult:
    async with database.session_factory() as session:
        return await VerifiedPhoneLinkCoordinator(
            CustomerService(CustomerRepository(session)),
            CustomerMergeService(CustomerMergeRepository(session)),
        ).link(
            telegram_id=telegram_id,
            contact_user_id=contact_user_id,
            phone=phone_number,
        )


async def _answer(
    message: Message,
    reply: CommandReply,
    *,
    webapp_url: str | None,
) -> None:
    markup = None
    if reply.show_mini_app and webapp_url:
        markup = build_mini_app_keyboard(webapp_url)
    await message.answer(reply.text, reply_markup=markup)


def build_mini_app_keyboard(webapp_url: str) -> InlineKeyboardMarkup:
    """Build navigation where every link opens inside Telegram Mini Apps."""

    items = (
        (("🏠 Главная", "/"), ("📱 Мой QR", "/card")),
        (("☕ Меню", "/menu"), ("🎁 Награды", "/rewards")),
        (("🧾 История", "/history"), ("ℹ️ Контакты", "/more")),
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=label,
                    web_app=WebAppInfo(url=_mini_app_url(webapp_url, path)),
                )
                for label, path in row
            ]
            for row in items
        ]
    )


def _mini_app_url(base_url: str, path: str) -> str:
    base = urlsplit(base_url)
    joined_path = f"{base.path.rstrip('/')}{path}" or "/"
    return urlunsplit((base.scheme, base.netloc, joined_path, "", ""))


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
