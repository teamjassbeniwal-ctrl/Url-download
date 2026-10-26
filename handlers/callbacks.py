"""
Team JB Downloader Bot — Callback query handlers.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    ChatMemberAdministrator,
    ChatMemberMember,
    ChatMemberOwner,
    ChatMemberRestricted,
)

from config import settings
from database import db
from utils.keyboards import back_to_menu_keyboard, main_menu_keyboard
from utils.messages import ABOUT_MESSAGE, HELP_MESSAGE, MAIN_MENU_MESSAGE

logger = logging.getLogger(__name__)

router = Router(name="callbacks")


def _is_member_object(member) -> bool:
    if isinstance(member, (ChatMemberOwner, ChatMemberAdministrator, ChatMemberMember)):
        return True
    if isinstance(member, ChatMemberRestricted):
        return member.is_member
    return False


_HOWTO_TEXT = (
    "📥 <b>How to Download</b>\n\n"
    "1. Copy a URL from any supported source.\n"
    "2. Paste it into this chat and send.\n"
    "3. The bot will analyze the link and show you available options.\n"
    "4. Choose a format (video, audio, or document).\n"
    "5. Wait for the upload to complete.\n\n"
    "<i>URL analysis and downloads will be activated in a later update.</i>"
)

_PREMIUM_TEXT = (
    "💎 <b>Premium Plans</b>\n\n"
    "Premium unlocks:\n"
    "• Higher daily download limits\n"
    "• Larger file sizes\n"
    "• Priority queue\n"
    "• More concurrent downloads\n\n"
    "<i>Plan details and subscription commands will be activated in a later update.</i>"
)

_REFER_TEXT = (
    "🎁 <b>Refer & Earn</b>\n\n"
    "Invite friends to Team JB Downloader and earn rewards when they "
    "join and start using the bot.\n\n"
    "<i>Your personal referral link will appear here in a later update.</i>"
)


@router.callback_query(F.data == "menu:main")
async def show_main_menu(call: CallbackQuery) -> None:
    await call.message.edit_text(text=MAIN_MENU_MESSAGE, reply_markup=main_menu_keyboard())
    await call.answer()


@router.callback_query(F.data == "menu:help")
async def show_help(call: CallbackQuery) -> None:
    await call.message.edit_text(
        text=HELP_MESSAGE, reply_markup=back_to_menu_keyboard(),
        disable_web_page_preview=True,
    )
    await call.answer()


@router.callback_query(F.data == "menu:about")
async def show_about(call: CallbackQuery) -> None:
    await call.message.edit_text(
        text=ABOUT_MESSAGE, reply_markup=back_to_menu_keyboard(),
        disable_web_page_preview=True,
    )
    await call.answer()


@router.callback_query(F.data == "menu:howto")
async def show_howto(call: CallbackQuery) -> None:
    await call.message.edit_text(
        text=_HOWTO_TEXT, reply_markup=back_to_menu_keyboard(),
        disable_web_page_preview=True,
    )
    await call.answer()


@router.callback_query(F.data == "menu:premium")
async def show_premium(call: CallbackQuery) -> None:
    await call.message.edit_text(
        text=_PREMIUM_TEXT, reply_markup=back_to_menu_keyboard(),
        disable_web_page_preview=True,
    )
    await call.answer()


@router.callback_query(F.data == "menu:refer")
async def show_refer(call: CallbackQuery) -> None:
    await call.message.edit_text(
        text=_REFER_TEXT, reply_markup=back_to_menu_keyboard(),
        disable_web_page_preview=True,
    )
    await call.answer()


@router.callback_query(F.data == "fsub:verify")
async def fsub_verify(call: CallbackQuery, bot) -> None:
    """Re-check membership after the user taps Verify."""
    channels = [doc async for doc in db.force_sub_channels.find({"is_active": True})]

    missing = []
    for ch in channels:
        try:
            member = await bot.get_chat_member(
                chat_id=ch["channel_id"], user_id=call.from_user.id
            )
            if not _is_member_object(member):
                missing.append(ch)
        except Exception as exc:
            logger.error(
                "fsub_verify CHECK FAILED | user=%d | channel=%s | %s: %s",
                call.from_user.id, ch["channel_id"], type(exc).__name__, exc,
            )
            missing.append(ch)

    if not missing:
        await call.message.edit_text(
            text=f"✅ Verification complete. Welcome, <b>{call.from_user.first_name}</b>!\n\n"
                 "Send a URL to start downloading, or use the menu below.",
            reply_markup=main_menu_keyboard(),
            disable_web_page_preview=True,
        )
        await call.answer("✅ Verified!")
        return

    await call.answer(
        f"❌ You have not joined {len(missing)} channel(s) yet.",
        show_alert=True,
    )
