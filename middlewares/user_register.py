"""
Team JB Downloader Bot — User registration middleware.

On every incoming update from a private chat, ensures the sender exists in
the `users` collection. New users are created with `is_banned=False` and
`is_admin=False`. Existing users get their `last_seen_at` and profile fields
refreshed.

Uses an upsert with $setOnInsert so concurrent updates from the same user
cannot create duplicates (enforced by the unique index on `telegram_id`).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

from database import db

logger = logging.getLogger(__name__)


class UserRegisterMiddleware(BaseMiddleware):
    """
    Register or refresh the user behind every update.

    Injects `db_user` into the handler data dict so handlers can access the
    MongoDB document without a second query.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")

        if user is None or user.is_bot:
            # No user (e.g. channel post) or bot sender — skip registration.
            return await handler(event, data)

        now = datetime.now(timezone.utc)

        try:
            # Upsert: insert on first sight, update last_seen on subsequent events.
            result = await db.users.find_one_and_update(
                filter={"telegram_id": user.id},
                update={
                    "$set": {
                        "username": user.username,
                        "first_name": user.first_name,
                        "last_seen_at": now,
                    },
                    "$setOnInsert": {
                        "telegram_id": user.id,
                        "is_banned": False,
                        "is_admin": False,
                        "referred_by": None,
                        "referral_reward_granted": False,
                        "created_at": now,
                    },
                },
                upsert=True,
                return_document=True,
            )
            data["db_user"] = result
        except Exception:
            # Never block the update because registration failed. Log and
            # continue; the handler may still respond.
            logger.exception("User registration failed for telegram_id=%d", user.id)

        return await handler(event, data)
