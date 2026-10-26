"""Team JB Downloader Bot — Application Entry Point. Part 6."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.fsm.storage.pymongo import PyMongoStorage

from config import settings
from database import db
from handlers import admin as admin_router
from handlers import callbacks as callbacks_router
from handlers import premium as premium_router
from handlers import start as start_router
from health import start_health_server
from middlewares.auth import OwnerRejectMiddleware
from middlewares.ban_check import BanCheckMiddleware
from middlewares.force_sub import ForceSubMiddleware
from middlewares.user_register import UserRegisterMiddleware
from services.subscription import subscription_expiry_worker

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if settings.log_file:
        fh = logging.FileHandler(settings.log_file, encoding="utf-8")
        fh.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        ))
        handlers.append(fh)

    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        handlers=handlers,
        force=True,
    )
    for noisy in ("aiogram.event", "aiohttp.access", "pymongo"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def build_bot() -> Bot:
    if settings.uses_local_api:
        session = AiohttpSession(api=TelegramAPIServer.from_base(settings.telegram_api_server))
        logger.info("Local Bot API Server: %s (limit %d MB)",
                    settings.telegram_api_server, settings.effective_upload_limit_mb)
    else:
        session = AiohttpSession()
        logger.warning("Public API in use. Upload limit: %d MB.", settings.effective_upload_limit_mb)

    return Bot(
        token=settings.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


async def run() -> None:
    configure_logging()
    settings.ensure_directories()

    logger.info("Starting Team JB Downloader Bot (Part 6)")
    logger.info("Owner ID: %d", settings.owner_id)
    logger.info("MongoDB URI: %s", settings.redacted_mongodb_uri)
    logger.info("MongoDB database: %s", settings.mongodb_database)

    try:
        await db.connect()
    except Exception:
        logger.exception("Failed to connect to MongoDB. Aborting startup.")
        raise

    fsm_storage = PyMongoStorage(
        client=db.client,
        db_name=settings.mongodb_database,
        collection_name="fsm_states",
    )

    health_runner = await start_health_server(settings.health_port)

    bot = build_bot()
    dp = Dispatcher(storage=fsm_storage)

    # Middlewares
    dp.update.outer_middleware(UserRegisterMiddleware())
    dp.update.outer_middleware(BanCheckMiddleware())
    dp.update.middleware(OwnerRejectMiddleware())

    force_sub = ForceSubMiddleware()
    dp.message.outer_middleware(force_sub)
    dp.callback_query.outer_middleware(force_sub)

    # Routers
    dp.include_router(start_router.router)
    dp.include_router(callbacks_router.router)
    dp.include_router(admin_router.router)
    dp.include_router(premium_router.router)

    # Background: subscription expiry
    expiry_task = asyncio.create_task(
        subscription_expiry_worker(3600),
        name="subscription-expiry",
    )

    # Graceful shutdown
    shutdown_event = asyncio.Event()

    def _request_shutdown(sig: int) -> None:
        logger.info("Received signal %s; shutting down", signal.Signals(sig).name)
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _request_shutdown, sig)
        except NotImplementedError:
            signal.signal(sig, lambda s, _: _request_shutdown(s))

    # Polling
    polling_task = asyncio.create_task(
        dp.start_polling(bot, handle_signals=False),
        name="aiogram-polling",
    )

    logger.info("Bot running. Health: http://0.0.0.0:%d/health", settings.health_port)

    try:
        await shutdown_event.wait()
    finally:
        logger.info("Stopping polling...")
        await dp.stop_polling()
        polling_task.cancel()
        try:
            await polling_task
        except asyncio.CancelledError:
            pass

        logger.info("Stopping expiry worker...")
        expiry_task.cancel()
        try:
            await expiry_task
        except asyncio.CancelledError:
            pass

        logger.info("Closing FSM storage...")
        await fsm_storage.close()
        logger.info("Closing MongoDB...")
        await db.close()
        logger.info("Closing bot session...")
        await bot.session.close()
        logger.info("Stopping health server...")
        await health_runner.cleanup()
        logger.info("Shutdown complete")


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
    except Exception:
        logging.getLogger(__name__).exception("Fatal error during startup")
        sys.exit(1)


if __name__ == "__main__":
    main()
