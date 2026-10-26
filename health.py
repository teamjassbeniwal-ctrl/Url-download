"""
Team JB Downloader Bot — Health endpoint.

Provides a minimal HTTP server used by Koyeb's health checks. This module
must not import anything from the bot itself (config, database, handlers)
to avoid circular imports. It only depends on aiohttp.

The exported function is `start_health_server`, which is imported by main.py.
"""

from __future__ import annotations

import logging

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

    Returns the AppRunner so the caller can shut it down cleanly with
    `await runner.cleanup()`.
    """
    app = create_health_app()
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logger.info("Health server listening on 0.0.0.0:%d", port)
    return runner
