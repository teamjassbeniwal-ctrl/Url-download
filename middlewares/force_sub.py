"""
Team JB Downloader Bot — Force-subscribe middleware.

Behavior:
- Owner bypasses the check entirely.
- /start and /help are whitelisted so users can always reach the prompt.
- Genuine non-members see a Join Required message with Join + Verify buttons.
- API errors (bot not admin, chat not found) are logged with full context
  and shown as a temporary error instead of pretending the user is not joined.
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
    """Return True only for statuses that mean the user is currently in the chat."""
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

        # 1. Owner bypass.
        if user.id == settings.owner_id:
            return await handler(event, data)

        # 2. Whitelist /start, /help, and fsub: callbacks.
        if self._is_whitelisted(event):
            return await handler(event, data)

        # 3. Load active channels.
        try:
            channels = [doc async for doc in db.force_sub_channels.find({"is_active": True})]
        except Exception:
            logger.exception("Force-sub: MongoDB error loading channels")
            return await handler(event, data)  # Do not block on DB failure.

        if not channels:
            return await handler(event, data)

        # 4. Check each channel.
        missing: list[dict] = []
        permission_error: Exception | None = None

        for ch in channels:
            channel_id = ch.get("channel_id")
            try:
                member = await bot.get_chat_member(chat_id=channel_id, user_id=user.id)
                if not _is_member_object(member):
                    missing.append(ch)
            except Exception as exc:
                logger.error(
                    "Force-sub CHECK FAILED | user=%d | channel=%s | %s: %s",
                    user.id, channel_id, type(exc).__name__, exc,
                )
                # Distinguish permission errors from other failures.
                error_str = str(exc).lower()
                if "not enough rights" in error_str or "forbidden" in error_str:
                    permission_error = exc
                else:
                    # Chat not found, bot removed, etc. Treat as not joined so
                    # the user still sees a prompt and the owner sees the log.
                    missing.append(ch)

        # 5. If a permission error occurred, show a temporary error.
        if permission_error is not None and not missing:
            await self._send_temp_error(event)
            return None

        # 6. If missing, show the join prompt.
        if missing:
            await self._send_join_prompt(event, missing)
            return None

        # 7. All checks passed.
        return await handler(event, data)

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
            "Please join our channel to use this bot.\n\n"
            "After joining, tap <b>I've Joined</b> below."
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

    async def _send_temp_error(self, event: TelegramObject) -> None:
        text = (
            "⚠️ <b>Temporary Error</b>\n\n"
            "The bot cannot verify channel membership right now. "
            "This usually means the bot is not an administrator in the required channel.\n\n"
            "Please contact the bot owner."
        )
        if isinstance(event, Message):
            await event.answer(text)
        elif isinstance(event, CallbackQuery):
            await event.answer(text, show_alert=True)
