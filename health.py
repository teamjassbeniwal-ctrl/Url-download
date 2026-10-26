"""
Team JB Downloader Bot — Application Entry Point.

Part 2 additions:
- MongoDB connect/close lifecycle.
- FSM storage backed by MongoDB (PyMongoStorage).
- User registration middleware.
"""

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
from health import start_health_server
from middlewares.user_register import UserRegisterMiddleware

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
        session = AiohttpSession(
            api=TelegramAPIServer.from_base(settings.telegram_api_server),
        )
        logger.info("Local Bot API Server: %s (limit %d MB)",
                    settings.telegram_api_server, settings.effective_upload_limit_mb)
    else:
        session = AiohttpSession()
        logger.warning("Public API in use. Upload limit: %d MB.",
                       settings.effective_upload_limit_mb)

    return Bot(
        token=settings.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


async def run() -> None:
    configure_logging()
    settings.ensure_directories()

    logger.info("Starting Team JB Downloader Bot (Part 2)")
    logger.info("Owner ID: %d", settings.owner_id)
    logger.info("MongoDB URI: %s", settings.redacted_mongodb_uri)
    logger.info("MongoDB database: %s", settings.mongodb_database)

    # ── 1. Connect to MongoDB (aborts startup on failure) ─────────────────
    try:
        await db.connect()
    except Exception:
        logger.exception("Failed to connect to MongoDB. Aborting startup.")
        raise

    # ── 2. FSM storage backed by the same MongoDB client ──────────────────
    fsm_storage = PyMongoStorage(
        client=db.client,
        db_name=settings.mongodb_database,
        collection_name="fsm_states",
    )

    # ── 3. Health server (Koyeb requires this) ────────────────────────────
    health_runner = await start_health_server(settings.health_port)

    # ── 4. Bot and dispatcher ─────────────────────────────────────────────
    bot = build_bot()
    dp = Dispatcher(storage=fsm_storage)

    # Register user registration middleware for all updates.
    dp.update.outer_middleware(UserRegisterMiddleware())

    # Handler routers will be registered in Part 3 onward.

    # ── 5. Graceful shutdown wiring ───────────────────────────────────────
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

    # ── 6. Start polling ──────────────────────────────────────────────────
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
