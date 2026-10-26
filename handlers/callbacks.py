"""
Team JB Downloader Bot — Callback query handlers for the main menu.

Handles taps on the inline keyboard buttons defined in utils/keyboards.py.
Each callback is prefixed 'menu:' to keep future callback namespaces
(e.g. 'dl:', 'admin:') separate.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from utils.keyboards import back_to_menu_keyboard, main_menu_keyboard
from utils.messages import ABOUT_MESSAGE, HELP_MESSAGE, MAIN_MENU_MESSAGE

logger = logging.getLogger(__name__)

router = Router(name="callbacks")

# Placeholder content for menu entries whose full implementations arrive in
# later parts. Each message clearly tells the user the feature is coming.
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
    await call.message.edit_text(
        text=MAIN_MENU_MESSAGE,
        reply_markup=main_menu_keyboard(),
    )
    await call.answer()


@router.callback_query(F.data == "menu:help")
async def show_help(call: CallbackQuery) -> None:
    await call.message.edit_text(
        text=HELP_MESSAGE,
        reply_markup=back_to_menu_keyboard(),
        disable_web_page_preview=True,
    )
    await call.answer()


@router.callback_query(F.data == "menu:about")
async def show_about(call: CallbackQuery) -> None:
    await call.message.edit_text(
        text=ABOUT_MESSAGE,
        reply_markup=back_to_menu_keyboard(),
        disable_web_page_preview=True,
    )
    await call.answer()


@router.callback_query(F.data == "menu:howto")
async def show_howto(call: CallbackQuery) -> None:
    await call.message.edit_text(
        text=_HOWTO_TEXT,
        reply_markup=back_to_menu_keyboard(),
        disable_web_page_preview=True,
    )
    await call.answer()


@router.callback_query(F.data == "menu:premium")
async def show_premium(call: CallbackQuery) -> None:
    await call.message.edit_text(
        text=_PREMIUM_TEXT,
        reply_markup=back_to_menu_keyboard(),
        disable_web_page_preview=True,
    )
    await call.answer()


@router.callback_query(F.data == "menu:refer")
async def show_refer(call: CallbackQuery) -> None:
    await call.message.edit_text(
        text=_REFER_TEXT,
        reply_markup=back_to_menu_keyboard(),
        disable_web_page_preview=True,
    )
    await call.answer()
