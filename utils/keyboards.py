"""
Team JB Downloader Bot — Inline keyboard factories.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_keyboard() -> InlineKeyboardMarkup:
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
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⬅️ Back to Menu", callback_data="menu:main"),
    )
    return builder.as_markup()


def help_close_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⬅️ Back to Menu", callback_data="menu:main"),
    )
    return builder.as_markup()


def owner_dashboard_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📊 Stats", callback_data="admin:stats"),
    )
    builder.row(
        InlineKeyboardButton(text="❌ Close", callback_data="admin:close"),
    )
    return builder.as_markup()
