"""
Team JB Downloader Bot — Premium admin commands.

Implements:
- /addpremium       : grant premium to a user (reply or by ID)
- /removepremium    : revoke all active subscriptions for a user
- /premiumusers     : list all active premium users
- /generatecoupon   : create a new coupon code
- /coupons          : list coupons
- /deletecoupon     : delete a coupon by code
- /redeem           : (user-facing) redeem a coupon
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from config import settings
from database import db
from middlewares.auth import OwnerOnly, reject_not_owner
from services.coupon import (
    create_coupon,
    delete_coupon,
    list_coupons,
    redeem_coupon,
)
from services.subscription import (
    PLANS,
    get_active_subscription,
    grant_subscription,
    revoke_subscription,
)
from utils.keyboards import (
    back_to_menu_keyboard,
    confirm_coupon_plan_keyboard,
    plan_selection_keyboard,
)

logger = logging.getLogger(__name__)

router = Router(name="premium_admin")


# ── Helpers ───────────────────────────────────────────────────────────────

def _extract_target_id(message: Message, command: CommandObject) -> int | None:
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id
    if command.args:
        try:
            return int(command.args.split()[0])
        except ValueError:
            return None
    return None


# ── /addpremium ───────────────────────────────────────────────────────────

@router.message(Command("addpremium"), OwnerOnly())
async def cmd_addpremium(message: Message, command: CommandObject) -> None:
    """
    Usage:
    • Reply to a user's message with /addpremium
    • Or /addpremium 123456789
    """
    target_id = _extract_target_id(message, command)
    if target_id is None:
        await message.answer(
            "Usage:\n"
            "• Reply to a user's message with /addpremium\n"
            "• Or /addpremium 123456789"
        )
        return
    if target_id == settings.owner_id:
        await message.answer("🚫 Owner already has full access.")
        return

    # Check the target user exists.
    user_doc = await db.users.find_one({"telegram_id": target_id})
    if user_doc is None:
        await message.answer(f"⚠️ No user found with ID {target_id}.")
        return

    await message.answer(
        f"Choose a plan for user <code>{target_id}</code>:\n\n"
        f"Target: <b>{user_doc.get('first_name', 'Unknown')}</b>",
        reply_markup=plan_selection_keyboard(target_id, action="grant"),
    )


@router.message(Command("addpremium"))
async def cmd_addpremium_reject(message: Message) -> None:
    await reject_not_owner(message)


@router.callback_query(F.data.startswith("padmin:grant:"))
async def cb_grant_plan(call: CallbackQuery) -> None:
    if call.from_user.id != settings.owner_id:
        await call.answer("🚫 Owner only.", show_alert=True)
        return

    # Format: padmin:grant:<plan>:<user_id>
    parts = call.data.split(":")
    if len(parts) != 4:
        await call.answer("Invalid callback.", show_alert=True)
        return
    plan_name = parts[2]
    try:
        target_id = int(parts[3])
    except ValueError:
        await call.answer("Invalid user ID.", show_alert=True)
        return

    if plan_name not in PLANS or plan_name == "free":
        await call.answer("Invalid plan.", show_alert=True)
        return

    try:
        expires_at = await grant_subscription(target_id, plan_name, f"owner:{call.from_user.id}")
    except Exception as exc:
        logger.exception("Grant failed: %s", exc)
        await call.answer("Failed to grant subscription. See logs.", show_alert=True)
        return

    await call.message.edit_text(
        f"✅ <b>Subscription granted</b>\n\n"
        f"User: <code>{target_id}</code>\n"
        f"Plan: <b>{PLANS[plan_name].display_name}</b>\n"
        f"Expires: <b>{expires_at.strftime('%Y-%m-%d %H:%M UTC')}</b>\n"
    )
    await call.answer("Granted!")


# ── /removepremium ────────────────────────────────────────────────────────

@router.message(Command("removepremium"), OwnerOnly())
async def cmd_removepremium(message: Message, command: CommandObject) -> None:
    target_id = _extract_target_id(message, command)
    if target_id is None:
        await message.answer(
            "Usage:\n"
            "• Reply to a user's message with /removepremium\n"
            "• Or /removepremium 123456789"
        )
        return
    if target_id == settings.owner_id:
        await message.answer("🚫 Cannot revoke owner's access.")
        return

    count = await revoke_subscription(target_id)
    if count == 0:
        await message.answer(f"⚠️ User <code>{target_id}</code> has no active subscription.")
        return
    await message.answer(
        f"✅ Revoked <b>{count}</b> active subscription(s) from <code>{target_id}</code>."
    )


@router.message(Command("removepremium"))
async def cmd_removepremium_reject(message: Message) -> None:
    await reject_not_owner(message)


# ── /premiumusers ─────────────────────────────────────────────────────────

@router.message(Command("premiumusers"), OwnerOnly())
async def cmd_premiumusers(message: Message) -> None:
    now = datetime.now(timezone.utc)
    cursor = db.subscriptions.find(
        {"is_active": True, "expires_at": {"$gt": now}}
    ).sort("expires_at", 1)

    lines = ["👑 <b>Active Premium Users</b>\n"]
    count = 0
    async for sub in cursor:
        count += 1
        expires = sub.get("expires_at")
        expiry_str = expires.strftime("%Y-%m-%d") if isinstance(expires, datetime) else "?"
        plan = sub.get("plan_name", "?")
        uid = sub.get("user_id")
        lines.append(f"• <code>{uid}</code> — {plan} until {expiry_str}")
        if count >= 50:
            lines.append("\n<i>(showing first 50)</i>")
            break

    if count == 0:
        await message.answer("No active premium users.")
        return

    await message.answer("\n".join(lines))


@router.message(Command("premiumusers"))
async def cmd_premiumusers_reject(message: Message) -> None:
    await reject_not_owner(message)


# ── /generatecoupon ───────────────────────────────────────────────────────

@router.message(Command("generatecoupon"), OwnerOnly())
async def cmd_generatecoupon(message: Message, command: CommandObject) -> None:
    """
    Usage: /generatecoupon <uses>
    Example: /generatecoupon 10
    Then pick the plan from inline buttons.
    """
    if not command.args:
        await message.answer(
            "Usage: /generatecoupon &lt;max_uses&gt;\n"
            "Example: /generatecoupon 10\n\n"
            "You will then pick a plan."
        )
        return
    try:
        max_uses = int(command.args.split()[0])
    except ValueError:
        await message.answer("❌ Max uses must be a number.")
        return
    if max_uses < 1 or max_uses > 10000:
        await message.answer("❌ Max uses must be between 1 and 10000.")
        return

    await message.answer(
        f"Choose the plan for this coupon ({max_uses} uses):",
        reply_markup=confirm_coupon_plan_keyboard(max_uses),
    )


@router.message(Command("generatecoupon"))
async def cmd_generatecoupon_reject(message: Message) -> None:
    await reject_not_owner(message)


@router.callback_query(F.data.startswith("padmin:coupon:"))
async def cb_generate_coupon(call: CallbackQuery) -> None:
    if call.from_user.id != settings.owner_id:
        await call.answer("🚫 Owner only.", show_alert=True)
        return

    # Format: padmin:coupon:<plan>:<max_uses>
    parts = call.data.split(":")
    if len(parts) != 4:
        await call.answer("Invalid callback.", show_alert=True)
        return
    plan_name = parts[2]
    try:
        max_uses = int(parts[3])
    except ValueError:
        await call.answer("Invalid uses.", show_alert=True)
        return

    try:
        doc = await create_coupon(
            plan_name=plan_name,
            max_uses=max_uses,
            duration_days=None,  # use plan default
            created_by=call.from_user.id,
        )
    except Exception as exc:
        logger.exception("Coupon creation failed: %s", exc)
        await call.answer("Failed to create coupon. See logs.", show_alert=True)
        return

    await call.message.edit_text(
        f"✅ <b>Coupon created</b>\n\n"
        f"Code: <code>{doc['code']}</code>\n"
        f"Plan: <b>{PLANS[plan_name].display_name}</b>\n"
        f"Max uses: <b>{max_uses}</b>\n"
        f"Duration: <b>{doc['duration_days']} days</b>\n\n"
        f"Share this code or use /redeem to test it."
    )
    await call.answer("Created!")


# ── /coupons ──────────────────────────────────────────────────────────────

@router.message(Command("coupons"), OwnerOnly())
async def cmd_coupons(message: Message) -> None:
    coupons = await list_coupons(include_expired=False)
    if not coupons:
        await message.answer("No active coupons.")
        return

    lines = ["🎟️ <b>Active Coupons</b>\n"]
    for c in coupons[:50]:
        lines.append(
            f"• <code>{c['code']}</code> — {c['plan_name']} "
            f"({c['used_count']}/{c['max_uses']} used)"
        )
    if len(coupons) > 50:
        lines.append(f"\n<i>… and {len(coupons) - 50} more</i>")
    await message.answer("\n".join(lines))


@router.message(Command("coupons"))
async def cmd_coupons_reject(message: Message) -> None:
    await reject_not_owner(message)


# ── /deletecoupon ─────────────────────────────────────────────────────────

@router.message(Command("deletecoupon"), OwnerOnly())
async def cmd_deletecoupon(message: Message, command: CommandObject) -> None:
    if not command.args:
        await message.answer("Usage: /deletecoupon JB-XXXX-XXXX-XXXX")
        return
    code = command.args.strip().upper()
    deleted = await delete_coupon(code)
    if deleted == 0:
        await message.answer(f"⚠️ No coupon found: <code>{code}</code>")
        return
    await message.answer(f"✅ Deleted coupon <code>{code}</code>.")


@router.message(Command("deletecoupon"))
async def cmd_deletecoupon_reject(message: Message) -> None:
    await reject_not_owner(message)


# ── /redeem (any user) ────────────────────────────────────────────────────

@router.message(Command("redeem"))
async def cmd_redeem(message: Message, command: CommandObject) -> None:
    if not command.args:
        await message.answer(
            "Usage: /redeem JB-XXXX-XXXX-XXXX"
        )
        return
    code = command.args.strip()
    success, msg, _ = await redeem_coupon(code, message.from_user.id)
    if success:
        await message.answer(f"✅ {msg}", reply_markup=back_to_menu_keyboard())
    else:
        await message.answer(f"❌ {msg}")
