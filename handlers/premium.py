"""
Team JB Downloader Bot — Premium plan display commands.

Implements /plans, /myplan, /premium, /getpremium.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from services.subscription import (
    PLANS,
    get_active_plan,
    get_active_subscription,
)
from utils.keyboards import (
    back_to_menu_keyboard,
    plans_overview_keyboard,
)
from utils.messages import (
    GETPREMIUM_MESSAGE,
    MYPLAN_FREE_MESSAGE,
    PLANS_OVERVIEW_MESSAGE,
    PREMIUM_BENEFITS_MESSAGE,
)

logger = logging.getLogger(__name__)

router = Router(name="premium")


@router.message(Command("plans"))
async def cmd_plans(message: Message) -> None:
    await message.answer(
        text=PLANS_OVERVIEW_MESSAGE,
        reply_markup=plans_overview_keyboard(),
        disable_web_page_preview=True,
    )


@router.message(Command("premium"))
async def cmd_premium(message: Message) -> None:
    await message.answer(
        text=PREMIUM_BENEFITS_MESSAGE,
        reply_markup=plans_overview_keyboard(),
        disable_web_page_preview=True,
    )


@router.message(Command("getpremium"))
async def cmd_getpremium(message: Message) -> None:
    await message.answer(
        text=GETPREMIUM_MESSAGE,
        reply_markup=back_to_menu_keyboard(),
        disable_web_page_preview=True,
    )


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
