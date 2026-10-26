"""
Team JB Downloader Bot — Inline keyboard factories.

Every keyboard is a fresh InlineKeyboardMarkup so it can be attached to
any message without shared state.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Main menu shown on /start and after 'Back to Menu' taps."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📥 How to Download", callback_data="menu:howto"),
    )
    builder.row(
        InlineKeyboardButton(text="💎 Premium Plans", callback_data="menu:premium"),
        InlineKeyboardButton(text="🎁 Refer & Earn", callback_data="menu:refer"),
    )
    builder.row(
        InlineKeyboardButton(text="ℹ️ About", callback_data="menu:about"),
        InlineKeyboardButton(text="📖 Help", callback_data="menu:help"),
    )
    return builder.as_markup()


def back_to_menu_keyboard() -> InlineKeyboardMarkup:
    """Single button used on all sub-screens to return to the main menu."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⬅️ Back to Menu", callback_data="menu:main"),
    )
    return builder.as_markup()


def help_close_keyboard() -> InlineKeyboardMarkup:
    """Close button attached to /help replies."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⬅️ Back to Menu", callback_data="menu:main"),
    )
    return builder.as_markup()
