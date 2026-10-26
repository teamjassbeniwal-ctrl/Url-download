"""
Team JB Downloader Bot — Owner authentication middleware.

Owner is determined by the `owner_id` setting, not by database state. This
prevents a database compromise from promoting an attacker to owner.

Usage in handlers:
    @router.message(Command("owner"), OwnerOnly())
    async def owner_dashboard(message: Message): ...

Non-owner attempts are rejected with a short message and logged.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message, TelegramObject, User

from config import settings

logger = logging.getLogger(__name__)


class OwnerOnly(BaseFilter):
    """Filter that passes only if the sender is the configured owner."""

    async def __call__(self, event: TelegramObject) -> bool:
        user = getattr(event, "from_user", None)
        return user is not None and user.id == settings.owner_id


class OwnerRejectMiddleware(BaseMiddleware):
    """
    Optional middleware version — attaches owner status to `data`.

    Handlers using OwnerOnly() do not need this. Registered anyway so future
    parts can check `data["is_owner"]` without re-deriving it.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        data["is_owner"] = user is not None and user.id == settings.owner_id
        return await handler(event, data)


async def reject_not_owner(event: Message | CallbackQuery) -> None:
    """Standard rejection response for non-owner attempts."""
    text = "🚫 This command is restricted to the bot owner."
    if isinstance(event, CallbackQuery):
        await event.answer(text, show_alert=True)
    else:
        await event.answer(text)
