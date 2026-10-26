"""
Team JB Downloader Bot — Force-subscribe middleware.

- Owner bypasses the check.
- Users who genuinely have not joined see a Join Required prompt.
- API errors are logged and treated as "not joined" so the prompt still shows.
- /start and /help are whitelisted so users can reach the Verify button.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import (
    CallbackQuery,
    ChatMemberAdministrator,
    ChatMemberBanned,
    ChatMemberLeft,
    ChatMemberMember,
    ChatMemberOwner,
    ChatMemberRestricted,
    InlineKeyboardButton,
    Message,
    TelegramObject,
    User,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import settings
from database import db

logger = logging.getLogger(__name__)


def _is_member_object(member) -> bool:
    """Return True only if the ChatMember object means the user is in the chat."""
    if isinstance(member, (ChatMemberOwner, ChatMemberAdministrator, ChatMemberMember)):
        return True
    if isinstance(member, ChatMemberRestricted):
        return member.is_member
    # ChatMemberLeft and ChatMemberBanned are not members
    return False


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

        # 1. Owner bypasses force-subscribe.
        if user.id == settings.owner_id:
            return await handler(event, data)

        # 2. Whitelisted updates (/start, /help, fsub: callbacks) pass through.
        if self._is_whitelisted(event):
            return await handler(event, data)

        # 3. Load active channels.
        try:
            channels = [doc async for doc in db.force_sub_channels.find({"is_active": True})]
        except Exception:
            logger.exception("Force-sub: failed to load channels from MongoDB")
            return await handler(event, data)

        if not channels:
            return await handler(event, data)

        # 4. Check each channel.
        missing = []
        for ch in channels:
            channel_id = ch.get("channel_id")
            try:
                member = await bot.get_chat_member(chat_id=channel_id, user_id=user.id)
                if not _is_member_object(member):
                    missing.append(ch)
            except Exception as exc:
                # API error (bot not admin, chat not found, etc.)
                # Log the full context for diagnosis, then treat as not joined
                # so the user still sees a usable prompt.
                logger.error(
                    "Force-sub CHECK FAILED | user=%d | channel=%s | error=%s: %s",
                    user.id, channel_id, type(exc).__name__, exc,
                )
                missing.append(ch)

        if not missing:
            return await handler(event, data)

        # 5. Block and show the join prompt.
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

    async def _send_join_prompt(self, event: TelegramObject, missing: list[dict]) -> None:
        builder = InlineKeyboardBuilder()
        for ch in missing:
            url = ch.get("invite_link")
            username = ch.get("channel_username")
            if not url and username:
                url = f"https://t.me/{username.lstrip('@')}"
            if not url:
                logger.error(
                    "Force-sub: no usable link for channel %s. Re-add with /addchannel.",
                    ch.get("channel_id"),
                )
                continue
            label = username or "Channel"
            builder.row(InlineKeyboardButton(text=f"📢 Join {label}", url=url))

        builder.row(InlineKeyboardButton(
            text="✅ I've Joined — Verify", callback_data="fsub:verify",
        ))

        text = (
            "🔒 <b>Join Required</b>\n\n"
            "To use Team JB Downloader, please join the channel(s) below, "
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
            await event.answer("Please join the channel first.", show_alert=True)
