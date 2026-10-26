"""
Team JB Downloader Bot — /start, /help, and premium command handlers.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import Router
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.types import Message

from database import db
from services.subscription import (
    PLANS,
    get_active_plan,
    get_active_subscription,
)
from utils.keyboards import (
    back_to_menu_keyboard,
    help_close_keyboard,
    main_menu_keyboard,
    plans_overview_keyboard,
)
from utils.messages import (
    GETPREMIUM_MESSAGE,
    HELP_MESSAGE,
    MYPLAN_FREE_MESSAGE,
    PLANS_OVERVIEW_MESSAGE,
    PREMIUM_BENEFITS_MESSAGE,
    WELCOME_MESSAGE,
)

logger = logging.getLogger(__name__)

router = Router(name="start")


# ── /start ────────────────────────────────────────────────────────────────

@router.message(CommandStart(deep_link=True))
async def start_with_deep_link(message: Message, command: CommandObject) -> None:
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
    await _send_welcome(message)


async def _send_welcome(message: Message) -> None:
    user = message.from_user
    display_name = user.first_name if user else "friend"
    text = f"Hi <b>{display_name}</b>!\n\n{WELCOME_MESSAGE}"
    await message.answer(
        text=text,
        reply_markup=main_menu_keyboard(),
        disable_web_page_preview=True,
    )


# ── /help ─────────────────────────────────────────────────────────────────

@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        text=HELP_MESSAGE,
        reply_markup=help_close_keyboard(),
        disable_web_page_preview=True,
    )


# ── /plans ────────────────────────────────────────────────────────────────

@router.message(Command("plans"))
async def cmd_plans(message: Message) -> None:
    await message.answer(
        text=PLANS_OVERVIEW_MESSAGE,
        reply_markup=plans_overview_keyboard(),
        disable_web_page_preview=True,
    )


# ── /premium ──────────────────────────────────────────────────────────────

@router.message(Command("premium"))
async def cmd_premium(message: Message) -> None:
    await message.answer(
        text=PREMIUM_BENEFITS_MESSAGE,
        reply_markup=plans_overview_keyboard(),
        disable_web_page_preview=True,
    )


# ── /getpremium ───────────────────────────────────────────────────────────

@router.message(Command("getpremium"))
async def cmd_getpremium(message: Message) -> None:
    await message.answer(
        text=GETPREMIUM_MESSAGE,
        reply_markup=back_to_menu_keyboard(),
        disable_web_page_preview=True,
    )


# ── /myplan ───────────────────────────────────────────────────────────────

@router.message(Command("myplan"))
async def cmd_myplan(message: Message) -> None:
    user = message.from_user
    if user is None:
        return

    plan = await get_active_plan(user.id)
    sub = await get_active_subscription(user.id)

    if sub is None:
        await message.answer(
            text=MYPLAN_FREE_MESSAGE,
            reply_markup=plans_overview_keyboard(),
            disable_web_page_preview=True,
        )
        return

    expires_at = sub.get("expires_at")
    if isinstance(expires_at, datetime):
        now = datetime.now(timezone.utc)
        days_left = max(0, (expires_at - now).days)
        expiry_text = expires_at.strftime("%Y-%m-%d %H:%M UTC")
    else:
        days_left = 0
        expiry_text = "unknown"

    text = (
        f"💎 <b>Your Plan</b>\n\n"
        f"Plan: <b>{plan.display_name}</b>\n"
        f"Status: <b>Active ✅</b>\n"
        f"Expires: <b>{expiry_text}</b>\n"
        f"Days remaining: <b>{days_left}</b>\n\n"
        f"<b>Limits</b>\n"
        f"• Max file size: <b>{plan.max_file_size_mb} MB</b>\n"
        f"• Daily downloads: <b>{plan.daily_downloads}</b>\n"
        f"• Concurrent downloads: <b>{plan.concurrent_downloads}</b>\n"
    )
    await message.answer(
        text=text,
        reply_markup=back_to_menu_keyboard(),
        disable_web_page_preview=True,
    )
