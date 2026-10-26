"""
Team JB Downloader Bot — Application Entry Point.

Responsibilities in Part 1:
    1. Configure logging.
    2. Ensure required directories exist.
    3. Start the aiohttp health server (required by Koyeb).
    4. Start the aiogram Bot and Dispatcher.
    5. Handle SIGTERM / SIGINT for graceful shutdown.

Later parts will register routers, middlewares, and services on the
Dispatcher created here. The foundation is intentionally minimal so that
each subsequent part can add its wiring without rewriting this file.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode

from config import settings
from health import start_health_server

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    """Set up root logging to stdout and optionally to a file."""
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    if settings.log_file:
        file_handler = logging.FileHandler(settings.log_file, encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
        )
        handlers.append(file_handler)

    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        handlers=handlers,
        force=True,
    )

    # Quiet down noisy third-party loggers at INFO level.
    for noisy in ("aiogram.event", "aiohttp.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def build_bot() -> Bot:
    """
    Construct the aiogram Bot, pointing at the Local Bot API Server if configured.

    If TELEGRAM_API_SERVER is set, all requests go through that server, which
    must already be running and authenticated with TELEGRAM_API_ID / TELEGRAM_API_HASH.
    Otherwise the public api.telegram.org is used (50 MB upload ceiling).
    """
    if settings.uses_local_api:
        session = AiohttpSession(
            api=TelegramAPIServer.from_base(settings.telegram_api_server),
        )
        logger.info(
            "Using Local Bot API Server at %s (upload limit: %d MB)",
            settings.telegram_api_server,
            settings.effective_upload_limit_mb,
        )
    else:
        session = AiohttpSession()
        logger.warning(
            "TELEGRAM_API_SERVER is not set. Using public api.telegram.org. "
            "Uploads are limited to %d MB. Files larger than this will fail.",
            settings.effective_upload_limit_mb,
        )

    return Bot(
        token=settings.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


async def run() -> None:
    """Main async entry point: start health server, then start polling."""
    configure_logging()
    settings.ensure_directories()

    logger.info("Starting Team JB Downloader Bot (Part 1 foundation)")
    logger.info("Owner ID: %d", settings.owner_id)
    logger.info("Download directory: %s", settings.download_dir)

    # ── 1. Health server (required by Koyeb) ──────────────────────────────
    health_runner = await start_health_server(settings.health_port)

    # ── 2. Bot and Dispatcher ─────────────────────────────────────────────
    bot = build_bot()
    dp = Dispatcher()

    # Routers and middlewares will be registered here in Parts 2–17.
    # For Part 1, the dispatcher has no handlers; polling will still run
    # and receive updates, which aiogram logs at DEBUG level.

    # ── 3. Graceful shutdown wiring ───────────────────────────────────────
    shutdown_event = asyncio.Event()

    def _request_shutdown(sig: int) -> None:
        logger.info("Received signal %s; shutting down", signal.Signals(sig).name)
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _request_shutdown, sig)
        except NotImplementedError:
            # Windows does not support add_signal_handler for all signals.
            signal.signal(sig, lambda s, _: _request_shutdown(s))

    # ── 4. Start polling ──────────────────────────────────────────────────
    polling_task = asyncio.create_task(
        dp.start_polling(bot, handle_signals=False),
        name="aiogram-polling",
    )

    logger.info("Bot is running. Send /start in Telegram once handlers are registered.")
    logger.info("Health check available at http://0.0.0.0:%d/health", settings.health_port)

    # ── 5. Wait for shutdown signal or unexpected polling exit ────────────
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

        logger.info("Closing bot session...")
        await bot.session.close()

        logger.info("Stopping health server...")
        await health_runner.cleanup()

        logger.info("Shutdown complete")


def main() -> None:
    """Synchronous wrapper with top-level exception logging."""
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
    except Exception:
        logging.getLogger(__name__).exception("Fatal error during startup")
        sys.exit(1)


if __name__ == "__main__":
    main()
