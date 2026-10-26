"""
Team JB Downloader Bot — Ban enforcement middleware.

Runs on every update. If the sender is a known banned user, the update is
silently dropped before any handler sees it.

The middleware trusts `db_user` injected by UserRegisterMiddleware; if that
is missing (e.g. middleware order changed), it falls back to a database query.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

from database import db

logger = logging.getLogger(__name__)


class BanCheckMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is None or user.is_bot:
            return await handler(event, data)

        db_user = data.get("db_user")
        if db_user is None:
            # Fallback: middleware order changed, or user was not registered.
            try:
                db_user = await db.users.find_one({"telegram_id": user.id})
            except Exception:
                logger.exception("Ban check failed to load user %d", user.id)
                return await handler(event, data)

        if db_user and db_user.get("is_banned"):
            logger.info("Dropped update from banned user %d", user.id)
            return None  # Silent drop — banned users get no reply.

        return await handler(event, data)
