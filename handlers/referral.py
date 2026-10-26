"""
Team JB Downloader Bot — Referral user commands.

Implements:
- /refer      : show referral link, stats, and reward info
- /referrals  : list recent successful referrals
"""

from __future__ import annotations

import logging
from datetime import datetime

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from config import settings
from database import db
from services.referral import (
    build_referral_link,
    get_referral_stats,
    list_referrals,
)
from services.subscription import PLANS
from utils.keyboards import back_to_menu_keyboard

logger = logging.getLogger(__name__)

router = Router(name="referral")


@router.message(Command("refer"))
async def cmd_refer(message: Message, bot: Bot) -> None:
    user = message.from_user
    if user is None:
        return

    me = await bot.get_me()
    link = build_referral_link(me.username or "", user.id)
    stats = await get_referral_stats(user.id)

    reward_plan = PLANS.get(settings.referral_reward_plan)
    reward_name = reward_plan.display_name if reward_plan else settings.referral_reward_plan
    reward_days = settings.referral_reward_days

    text = (
        "🎁 <b>Refer & Earn</b>\n\n"
        f"Share your personal referral link:\n"
        f"<code>{link}</code>\n\n"
        "For every friend who joins through your link <b>and completes "
        f"{settings.referral_min_downloads_to_qualify} download(s)</b>, "
        f"you receive <b>{reward_days} days of {reward_name}</b>.\n\n"
        f"📊 <b>Your stats</b>\n"
        f"• Total referrals: <b>{stats['total']}</b>\n"
        f"• Rewards earned: <b>{stats['rewarded']}</b>\n"
        f"• Pending: <b>{stats['pending']}</b>\n\n"
        "Use /referrals to see the full list.\n"
        "Use /myplan to check your active premium status."
    )
    await message.answer(
        text=text,
        reply_markup=back_to_menu_keyboard(),
        disable_web_page_preview=True,
    )


@router.message(Command("referrals"))
async def cmd_referrals(message: Message) -> None:
    user = message.from_user
    if user is None:
        return

    rows = await list_referrals(user.id, limit=20)
    if not rows:
        await message.answer(
            "You have no referrals yet.\n\n"
            "Use /refer to get your personal link.",
            reply_markup=back_to_menu_keyboard(),
        )
        return

    lines = ["🎁 <b>Your Referrals</b>\n"]
    for r in rows:
        referred_id = r.get("referred_id")
        created = r.get("created_at")
        rewarded = r.get("reward_granted", False)
        when = created.strftime("%Y-%m-%d") if isinstance(created, datetime) else "?"
        status = "✅ rewarded" if rewarded else "⏳ pending"
        lines.append(f"• <code>{referred_id}</code> — {when} — {status}")

    lines.append(f"\nShowing last {len(rows)} referrals.")
    await message.answer(
        "\n".join(lines),
        reply_markup=back_to_menu_keyboard(),
        disable_web_page_preview=True,
    )
