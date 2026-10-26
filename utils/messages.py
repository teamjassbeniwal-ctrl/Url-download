"""
Team JB Downloader Bot — Message templates.
"""

from __future__ import annotations

from services.subscription import PLANS


WELCOME_MESSAGE = (
    "👋 <b>Welcome to Team JB Universal Downloader!</b>\n\n"
    "I can download videos, audio, documents, and archives from many "
    "supported websites.\n\n"
    "📎 <b>How to use:</b>\n"
    "Simply send me a URL and I will analyze it and offer download options.\n\n"
    "🔧 <b>Quick commands:</b>\n"
    "• /help — full command list\n"
    "• /plans — premium plans\n"
    "• /myplan — your current plan\n\n"
    "Choose an option below to continue."
)

HELP_MESSAGE = (
    "📖 <b>Team JB Downloader — Help</b>\n\n"
    "🔗 <b>Downloading</b>\n"
    "• Send a URL directly to download a file\n"
    "• Supported: direct files, YouTube, Instagram, TikTok, Twitter/X, "
    "Facebook, HLS/DASH streams, archives, Google Drive, and more\n\n"
    "📋 <b>Commands</b>\n"
    "• /start — restart the bot and show the main menu\n"
    "• /help — show this message\n"
    "• /plans — view premium plans\n"
    "• /myplan — your current plan\n"
    "• /premium — premium benefits\n"
    "• /getpremium — how to buy premium\n"
    "• /redeem — redeem a coupon code\n"
    "• /refer — your referral link (coming soon)\n"
    "• /referrals — your referral list (coming soon)\n\n"
    "👑 <b>Owner commands</b>\n"
    "• /owner, /stats, /ban, /unban, /broadcast, /restart\n"
    "• /addchannel, /removechannel, /channels\n"
    "• /addpremium, /removepremium, /premiumusers\n"
    "• /generatecoupon, /coupons, /deletecoupon\n"
    "• /expirenow\n\n"
    "🎟️ <b>Redeem a coupon</b>\n"
    "• /redeem CODE\n\n"
    "❓ If a URL fails, make sure it is public and not DRM-protected."
)

MAIN_MENU_MESSAGE = (
    "🏠 <b>Main Menu</b>\n\n"
    "Choose an option below, or send a URL to start downloading."
)

ABOUT_MESSAGE = (
    "ℹ️ <b>About Team JB Downloader</b>\n\n"
    "A universal media downloader built for Telegram.\n"
    "Features: video, audio, archives, Google Drive, HLS/DASH, and more.\n\n"
    "🔒 Authorized content only. No DRM circumvention.\n"
    "📩 Contact: @jassbeniwal (bot owner)"
)

BACK_TO_MENU_BUTTON = "⬅️ Back to Menu"

OWNER_DASHBOARD_MESSAGE = (
    "👑 <b>Owner Dashboard</b>\n\n"
    "Welcome back, boss. Use the buttons below for quick actions, "
    "or the commands listed in /help."
)


def _format_plans_lines() -> str:
    """Build a comparison table from the PLANS catalogue."""
    lines = []
    for plan_name in ("weekly", "monthly", "yearly"):
        p = PLANS[plan_name]
        lines.append(
            f"{p.display_name} — ₹{p.price_inr} / {p.duration_days}d\n"
            f"   • File size: {p.max_file_size_mb} MB\n"
            f"   • Daily downloads: {p.daily_downloads}\n"
            f"   • Concurrent: {p.concurrent_downloads}"
        )
    return "\n\n".join(lines)


PLANS_OVERVIEW_MESSAGE = (
    "💎 <b>Premium Plans</b>\n\n"
    f"🆓 <b>Free</b> — ₹0\n"
    f"   • File size: {PLANS['free'].max_file_size_mb} MB\n"
    f"   • Daily downloads: {PLANS['free'].daily_downloads}\n"
    f"   • Concurrent: {PLANS['free'].concurrent_downloads}\n\n"
    f"{_format_plans_lines()}\n\n"
    "Use /myplan to check your current plan."
)

PREMIUM_BENEFITS_MESSAGE = (
    "💎 <b>Why Go Premium?</b>\n\n"
    "• 📦 <b>Bigger files</b> — up to 2 GB per file\n"
    "• 🚀 <b>Priority queue</b> — skip the line\n"
    "• 📥 <b>More daily downloads</b> — up to 500/day\n"
    "• ⚡ <b>Higher concurrency</b> — download more at once\n"
    "• 🎁 <b>Referral bonuses</b> — earn premium days\n\n"
    "Ready to upgrade? Use /plans to see prices, or /getpremium for "
    "purchase instructions."
)

GETPREMIUM_MESSAGE = (
    "🛒 <b>How to Buy Premium</b>\n\n"
    "1. Contact the bot owner: @TeamJB_bot\n"
    "2. Choose your plan (/plans for options)\n"
    "3. Pay via UPI or another method agreed with the owner\n"
    "4. The owner activates your subscription manually\n"
    "5. Check your status with /myplan\n\n"
    "💡 <b>Tip:</b> Invite friends using /refer (coming soon) to earn "
    "free premium days."
)

MYPLAN_FREE_MESSAGE = (
    "🆓 <b>Your Plan: Free</b>\n\n"
    "You are currently on the Free plan.\n\n"
    "Use /plans to see premium options, or /getpremium for purchase steps."
)
