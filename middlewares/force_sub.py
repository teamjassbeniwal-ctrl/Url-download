"""
Team JB Downloader Bot — Force-subscribe middleware. Corrected.
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

        if user.id == settings.owner_id:
            return await handler(event, data)

        if self._is_whitelisted(event):
            return await handler(event, data)

        try:
            channels = [doc async for doc in db.force_sub_channels.find({"is_active": True})]
        except Exception:
            logger.exception("Force-sub: failed to load channels")
            return await handler(event, data)

        if not channels:
            return await handler(event, data)

        missing = []
        for ch in channels:
            joined = await self._is_joined(bot, ch, user.id)
            if not joined:
                missing.append(ch)

        if not missing:
            return await handler(event, data)

        await self._send_join_prompt(event, missing)
        return None

    @staticmethod
    def _is_whitelisted(event: TelegramObject) -> bool:
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
    async def _is_joined(bot, channel: dict, user_id: int) -> bool:
        """
        Check membership. Logs the exact error instead of failing open silently.
        """
        channel_id = channel.get("channel_id")
        try:
            member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
            status = getattr(member, "status", None)
            if isinstance(status, str):
                return status in _JOINED_STATUSES
            return getattr(status, "value", None) in _JOINED_STATUSES
        except Exception as exc:
            # Log with the real exception so you can see WHY it failed.
            logger.error(
                "Force-sub CHECK FAILED for user %d in channel %s: %s: %s",
                user_id, channel_id, type(exc).__name__, exc,
            )
            # Do NOT fail open silently. Return False so the user sees the join prompt.
            # If the bot truly cannot check (e.g. not admin), the owner will see
            # repeated errors in logs and must fix the bot's admin rights.
            return False

    async def _send_join_prompt(self, event: TelegramObject, missing: list[dict]) -> None:
        builder = InlineKeyboardBuilder()
        for ch in missing:
            link = ch.get("invite_link")
            username = ch.get("channel_username")

            # Prefer a stored invite link; fall back to public username.
            url = None
            if link:
                url = link
            elif username:
                url = f"https://t.me/{username.lstrip('@')}"

            if not url:
                logger.error(
                    "Force-sub: no usable link for channel %s. "
                    "Re-add the channel with /addchannel so an invite link is stored.",
                    ch.get("channel_id"),
                )
                continue

            label = username or "Channel"
            builder.row(InlineKeyboardButton(
                text=f"📢 Join {label}", url=url,
            ))

        builder.row(InlineKeyboardButton(
            text="✅ I've Joined — Verify", callback_data="fsub:verify",
        ))

        text = (
            "🔒 <b>Join Required</b>\n\n"
            "To use Team JB Downloader, please join our required channels below, "
            "then tap <b>I've Joined</b>."
        )

        if isinstance(event, Message):
            await event.answer(text, reply_markup=builder.as_markup(),
                               disable_web_page_preview=True)
        elif isinstance(event, CallbackQuery):
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
