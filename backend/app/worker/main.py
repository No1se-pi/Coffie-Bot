"""Long-running PostgreSQL outbox and broadcast worker."""

from __future__ import annotations

import asyncio
import os
import signal
from dataclasses import dataclass
from datetime import timedelta

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import create_database
from app.repositories.delivery import DeliveryRepository
from app.services.broadcasts import BroadcastService
from app.services.notifications import (
    DeliveryError,
    MessageSender,
    NotificationService,
    OutboundMessage,
    RetryPolicy,
)

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class WorkerOptions:
    batch_size: int = 50
    poll_interval_seconds: float = 2.0
    lease_seconds: int = 60
    max_attempts: int = 7
    base_backoff_seconds: int = 10
    max_backoff_seconds: int = 3600

    @classmethod
    def from_environment(cls) -> WorkerOptions:
        return cls(
            batch_size=_environment_int("WORKER_BATCH_SIZE", 50, minimum=1, maximum=1000),
            poll_interval_seconds=_environment_float(
                "WORKER_POLL_INTERVAL_SECONDS",
                2.0,
                minimum=0.1,
                maximum=300.0,
            ),
            lease_seconds=_environment_int(
                "WORKER_LEASE_SECONDS", 60, minimum=5, maximum=3600
            ),
            max_attempts=_environment_int(
                "WORKER_MAX_ATTEMPTS", 7, minimum=1, maximum=100
            ),
            base_backoff_seconds=_environment_int(
                "WORKER_BASE_BACKOFF_SECONDS", 10, minimum=1, maximum=3600
            ),
            max_backoff_seconds=_environment_int(
                "WORKER_MAX_BACKOFF_SECONDS", 3600, minimum=1, maximum=86_400
            ),
        )

    def retry_policy(self) -> RetryPolicy:
        maximum = max(self.base_backoff_seconds, self.max_backoff_seconds)
        return RetryPolicy(
            max_attempts=self.max_attempts,
            base_delay=timedelta(seconds=self.base_backoff_seconds),
            max_delay=timedelta(seconds=maximum),
        )


class AiogramMessageSender(MessageSender):
    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def send(self, telegram_id: int, message: OutboundMessage) -> int:
        keyboard = _keyboard(message)
        try:
            if message.image_path is not None:
                result = await self._bot.send_photo(
                    chat_id=telegram_id,
                    photo=FSInputFile(message.image_path),
                    caption=message.text,
                    reply_markup=keyboard,
                )
            else:
                result = await self._bot.send_message(
                    chat_id=telegram_id,
                    text=message.text,
                    reply_markup=keyboard,
                )
        except TelegramRetryAfter as exc:
            raise DeliveryError(
                "telegram_retry_after",
                retry_after=timedelta(seconds=exc.retry_after),
            ) from exc
        except TelegramForbiddenError as exc:
            raise DeliveryError("telegram_forbidden", permanent=True) from exc
        except TelegramBadRequest as exc:
            raise DeliveryError("telegram_bad_request", permanent=True) from exc
        except TelegramNetworkError as exc:
            raise DeliveryError("telegram_network_error") from exc
        except TelegramAPIError as exc:
            raise DeliveryError("telegram_api_error") from exc
        return result.message_id


async def run_worker(
    settings: Settings,
    *,
    options: WorkerOptions | None = None,
    sender: MessageSender | None = None,
    stop_event: asyncio.Event | None = None,
) -> None:
    resolved_options = options or WorkerOptions.from_environment()
    token = settings.bot_token.get_secret_value() if settings.bot_token else None
    if sender is None and not token:
        raise RuntimeError("BOT_TOKEN is required to run the worker")

    database = create_database(settings)
    bot = Bot(token=token) if sender is None and token is not None else None
    resolved_sender = sender or AiogramMessageSender(_required_bot(bot))
    stop = stop_event or asyncio.Event()
    if stop_event is None:
        _install_signal_handlers(stop)
    retry_policy = resolved_options.retry_policy()
    lease_for = timedelta(seconds=resolved_options.lease_seconds)

    logger.info(
        "worker_started",
        batch_size=resolved_options.batch_size,
        lease_seconds=resolved_options.lease_seconds,
    )
    try:
        while not stop.is_set():
            processed = 0
            try:
                async with database.session_factory() as session:
                    repository = DeliveryRepository(session)
                    notifications = NotificationService(
                        repository=repository,
                        sender=resolved_sender,
                        retry_policy=retry_policy,
                        webapp_url=settings.telegram_webapp_url,
                    )
                    notification_result = await notifications.process_batch(
                        limit=resolved_options.batch_size,
                        lease_for=lease_for,
                    )
                    broadcasts = BroadcastService(
                        repository=repository,
                        sender=resolved_sender,
                        retry_policy=retry_policy,
                        media_root=settings.media_root,
                    )
                    broadcast_result = await broadcasts.process_batch(
                        limit=resolved_options.batch_size,
                        lease_for=lease_for,
                    )
                processed = notification_result.claimed + broadcast_result.claimed
                if processed:
                    logger.info(
                        "worker_batch_processed",
                        notifications=notification_result.claimed,
                        broadcasts=broadcast_result.claimed,
                        sent=notification_result.sent + broadcast_result.sent,
                        retried=notification_result.retried + broadcast_result.retried,
                        failed=notification_result.failed + broadcast_result.failed,
                        skipped=broadcast_result.skipped,
                    )
            except Exception:
                logger.exception("worker_batch_failed")

            if processed == 0 and not stop.is_set():
                await _wait_for_stop(stop, resolved_options.poll_interval_seconds)
    finally:
        if bot is not None:
            await bot.session.close()
        await database.engine.dispose()
        logger.info("worker_stopped")


def main() -> int:
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.log_json)
    try:
        asyncio.run(run_worker(settings))
    except KeyboardInterrupt:
        return 130
    except Exception:
        get_logger(__name__).exception("worker_startup_failed")
        return 1
    return 0


def _keyboard(message: OutboundMessage) -> InlineKeyboardMarkup | None:
    if not message.button_label or not message.button_url:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=message.button_label, url=message.button_url)]
        ]
    )


def _required_bot(bot: Bot | None) -> Bot:
    if bot is None:
        raise RuntimeError("Telegram bot was not initialized")
    return bot


def _install_signal_handlers(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_number, stop.set)
        except (NotImplementedError, RuntimeError):
            continue


async def _wait_for_stop(stop: asyncio.Event, delay_seconds: float) -> None:
    try:
        async with asyncio.timeout(delay_seconds):
            await stop.wait()
    except TimeoutError:
        pass


def _environment_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _environment_float(
    name: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
