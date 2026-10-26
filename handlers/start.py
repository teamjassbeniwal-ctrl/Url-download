"""
Team JB Downloader Bot — /start and /help command handlers.

Handles:
- /start (with optional deep-link payload, stored for future referral processing)
- /help
- The initial main menu and help replies.
"""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.types import Message

from database import db
from utils.keyboards import help_close_keyboard, main_menu_keyboard
from utils.messages import HELP_MESSAGE, WELCOME_MESSAGE

logger = logging.getLogger(__name__)

router = Router(name="start")


@router.message(CommandStart(deep_link=True))
async def start_with_deep_link(message: Message, command: CommandObject) -> None:
    """
    Handle /start with a payload like /start ref_12345.

    The payload is recorded on the user document for Part 8 (referrals) to
    process. Part 3 does not grant rewards yet; it only stores the payload.
    """
    payload = (command.args or "").strip()

    if payload and message.from_user is not None:
        try:
            await db.users.update_one(
                {"telegram_id": message.from_user.id},
                {"$set": {"start_payload": payload}},
            )
            logger.info("Recorded start payload '%s' for user %d",
                        payload, message.from_user.id)
        except Exception:
            logger.exception("Failed to store start payload for user %d",
                             message.from_user.id)

    await _send_welcome(message)


@router.message(CommandStart())
async def start_plain(message: Message) -> None:
    """Handle /start without a payload."""
    await _send_welcome(message)


async def _send_welcome(message: Message) -> None:
    """Common welcome reply used by both /start variants."""
    user = message.from_user
    display_name = user.first_name if user else "friend"
    text = f"Hi <b>{display_name}</b>!\n\n{WELCOME_MESSAGE}"

    await message.answer(
        text=text,
        reply_markup=main_menu_keyboard(),
        disable_web_page_preview=True,
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Handle /help."""
    await message.answer(
        text=HELP_MESSAGE,
        reply_markup=help_close_keyboard(),
        disable_web_page_preview=True,
    )
