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


def plans_overview_keyboard() -> InlineKeyboardMarkup:
    """Buttons shown alongside /plans, /premium, /myplan."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🛒 How to Buy", callback_data="menu:getpremium"),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Back to Menu", callback_data="menu:main"),
    )
    return builder.as_markup()

def plan_selection_keyboard(user_id: int, action: str) -> InlineKeyboardMarkup:
    """
    Show plan buttons for /addpremium.
    Callback data format: padmin:{action}:{plan}:{user_id}
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="⭐ Weekly (7d)",
            callback_data=f"padmin:{action}:weekly:{user_id}",
        ),
        InlineKeyboardButton(
            text="💎 Monthly (30d)",
            callback_data=f"padmin:{action}:monthly:{user_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="👑 Yearly (365d)",
            callback_data=f"padmin:{action}:yearly:{user_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(text="❌ Cancel", callback_data="admin:close"),
    )
    return builder.as_markup()


def confirm_coupon_plan_keyboard(max_uses: int) -> InlineKeyboardMarkup:
    """
    Plan buttons for /generatecoupon.
    Callback data format: padmin:coupon:{plan}:{max_uses}
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="⭐ Weekly",
            callback_data=f"padmin:coupon:weekly:{max_uses}",
        ),
        InlineKeyboardButton(
            text="💎 Monthly",
            callback_data=f"padmin:coupon:monthly:{max_uses}",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="👑 Yearly",
            callback_data=f"padmin:coupon:yearly:{max_uses}",
        ),
    )
    builder.row(
        InlineKeyboardButton(text="❌ Cancel", callback_data="admin:close"),
    )
    return builder.as_markup()
