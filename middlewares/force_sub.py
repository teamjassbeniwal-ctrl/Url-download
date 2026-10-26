"""
Team JB Downloader Bot — Force-subscribe middleware.

Blocks updates from users who have not joined all active force-sub channels.

Exempt updates:
- Any /start or /help message (so users can recover and reach the Verify button)
- Any callback query with data starting with 'fsub:'
- Owner (by owner_id)
- Private channel join links (which are messages, not callbacks)

For blocked users, the handler is never called. Instead, the middleware replies
with a "Join Required" message that lists all active channels and includes a
Verify button.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message, TelegramObject, User
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import settings
from database import db

logger = logging.getLogger(__name__)

# Statuses that count as "joined" a channel.
_JOINED_STATUSES = {"member", "administrator", "creator"}


class ForceSubMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        bot = data.get("bot")

        if user is None or user.is_bot or bot is None:
            return await handler(event, data)

        # Owner bypasses force-sub entirely.
        if user.id == settings.owner_id:
            return await handler(event, data)

        # Whitelisted updates: allow through so the user can reach Verify.
        if self._is_whitelisted(event):
            return await handler(event, data)

        # Load active channels.
        try:
            channels = [
                doc async for doc in db.force_sub_channels.find({"is_active": True})
            ]
        except Exception:
            logger.exception("Force-sub: failed to load channels")
            return await handler(event, data)  # Do not block on DB failure.

        if not channels:
            return await handler(event, data)

        # Determine whether the user has joined every channel.
        missing = []
        for ch in channels:
            joined = await self._is_joined(bot, ch["channel_id"], user.id)
            if not joined:
                missing.append(ch)

        if not missing:
            return await handler(event, data)

        # Block the update and show the join prompt.
        await self._send_join_prompt(event, missing)
        return None

    @staticmethod
    def _is_whitelisted(event: TelegramObject) -> bool:
        """Allow /start, /help, and fsub: callbacks through the gate."""
        if isinstance(event, Message):
            text = (event.text or "").strip()
            if not text.startswith("/"):
                return False
            command = text.split()[0].split("@")[0].lower()
            return command in {"/start", "/help"}
        if isinstance(event, CallbackQuery):
            return (event.data or "").startswith("fsub:")
        return False

    @staticmethod
    async def _is_joined(bot, channel_id: int, user_id: int) -> bool:
        """Query Telegram for membership; treat any error as 'not joined'."""
        try:
            member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
            status = getattr(member, "status", None)
            if isinstance(status, str):
                return status in _JOINED_STATUSES
            # Some aiogram versions return an enum.
            return getattr(status, "value", None) in _JOINED_STATUSES
        except Exception:
            # If the bot cannot check (e.g. it is not admin), fail open on that
            # channel so misconfiguration does not lock users out permanently.
            logger.warning(
                "Force-sub: cannot check user %d in channel %s",
                user_id, channel_id,
            )
            return True

    async def _send_join_prompt(self, event: TelegramObject, missing: list[dict]) -> None:
        """Build and send the 'Join Required' message with per-channel buttons."""
        builder = InlineKeyboardBuilder()
        for ch in missing:
            link = self._channel_link(ch)
            if link is None:
                continue
            builder.row(InlineKeyboardButton(text=f"📢 Join {ch.get('channel_username') or 'Channel'}",
                                             url=link))
        builder.row(InlineKeyboardButton(text="✅ I've Joined — Verify",
                                         callback_data="fsub:verify"))

        text = (
            "🔒 <b>Join Required</b>\n\n"
            "To use Team JB Downloader, please join our required channels below, "
            "then tap <b>I've Joined</b>."
        )

        if isinstance(event, Message):
            await event.answer(text, reply_markup=builder.as_markup(),
                               disable_web_page_preview=True)
        elif isinstance(event, CallbackQuery):
            # Editing the same message avoids message spam on repeated taps.
            try:
                await event.message.edit_text(
                    text, reply_markup=builder.as_markup(),
                    disable_web_page_preview=True,
                )
            except Exception:
                await event.message.answer(
                    text, reply_markup=builder.as_markup(),
                    disable_web_page_preview=True,
                )
            await event.answer("Please join the channels first.", show_alert=True)

    @staticmethod
    def _channel_link(ch: dict) -> str | None:
        """Public channels use t.me/<username>; private use t.me/c/<id>/1."""
        username = ch.get("channel_username")
        if username:
            return f"https://t.me/{username.lstrip('@')}"
        channel_id = ch.get("channel_id")
        if isinstance(channel_id, int) and str(channel_id).startswith("-100"):
            # Private channel link format: t.me/c/<internal>/<message_id>
            internal = str(channel_id)[4:]  # Strip leading '-100'
            return f"https://t.me/c/{internal}/1"
        return None
