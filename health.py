"""
Team JB Downloader Bot — Health Endpoint.

Koyeb performs HTTP health checks and restarts services that do not respond.
A Telegram polling bot does not listen on HTTP by itself, so this module runs
a minimal aiohttp server alongside the bot.

The health server is started as an asyncio task from main.py. It is intentionally
thin: one route, one status code, no dependencies on the bot's internal state.
"""

from __future__ import annotations

import logging
from typing import Optional

from aiohttp import web

logger = logging.getLogger(__name__)


async def _health_handler(request: web.Request) -> web.Response:
    """Return 200 OK with a small JSON body."""
    return web.json_response({"status": "ok", "service": "team-jb-downloader"})


async def _root_handler(request: web.Request) -> web.Response:
    """Root returns the same payload; useful for manual checks."""
    return web.json_response({"status": "ok", "service": "team-jb-downloader"})


def create_health_app() -> web.Application:
    """Build the aiohttp application with health routes registered."""
    app = web.Application()
    app.router.add_get("/health", _health_handler)
    app.router.add_get("/", _root_handler)
    return app


async def start_health_server(port: int) -> web.AppRunner:
    """
    Start the health server on the given port.

    Returns the AppRunner so the caller can shut it down cleanly.
    The caller is responsible for awaiting runner.cleanup() on shutdown.
    """
    app = create_health_app()
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logger.info("Health server listening on 0.0.0.0:%d", port)
    return runner
