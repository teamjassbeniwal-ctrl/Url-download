"""
Team JB Downloader Bot — Owner and admin handlers.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from config import settings
from database import db
from middlewares.auth import OwnerOnly, reject_not_owner
from utils.keyboards import owner_dashboard_keyboard
from utils.messages import OWNER_DASHBOARD_MESSAGE

logger = logging.getLogger(__name__)

router = Router(name="admin")


# ── /owner ────────────────────────────────────────────────────────────────

@router.message(Command("owner"), OwnerOnly())
async def cmd_owner(message: Message) -> None:
    await message.answer(
        text=OWNER_DASHBOARD_MESSAGE,
        reply_markup=owner_dashboard_keyboard(),
    )


@router.message(Command("owner"))
async def cmd_owner_reject(message: Message) -> None:
    await reject_not_owner(message)


@router.callback_query(F.data == "admin:stats")
async def cb_stats(call: CallbackQuery) -> None:
    if call.from_user.id != settings.owner_id:
        await call.answer("🚫 Owner only.", show_alert=True)
        return
    await call.message.edit_text(await _build_stats_text())
    await call.answer("Refreshed")


@router.callback_query(F.data == "admin:close")
async def cb_close(call: CallbackQuery) -> None:
    if call.from_user.id != settings.owner_id:
        await call.answer("🚫 Owner only.", show_alert=True)
        return
    await call.message.delete()
    await call.answer()


# ── /stats ────────────────────────────────────────────────────────────────

@router.message(Command("stats"), OwnerOnly())
async def cmd_stats(message: Message) -> None:
    await message.answer(await _build_stats_text())


@router.message(Command("stats"))
async def cmd_stats_reject(message: Message) -> None:
    await reject_not_owner(message)


async def _build_stats_text() -> str:
    now = datetime.now(timezone.utc)
    try:
        total_users = await db.users.count_documents({})
        banned_users = await db.users.count_documents({"is_banned": True})
        active_premium = await db.subscriptions.count_documents({
            "is_active": True,
            "expires_at": {"$gt": now},
        })
        total_downloads = await db.downloads.count_documents({})
        completed_downloads = await db.downloads.count_documents({"status": "completed"})
        failed_downloads = await db.downloads.count_documents({"status": "failed"})
        active_channels = await db.force_sub_channels.count_documents({"is_active": True})
    except Exception:
        logger.exception("Failed to build stats")
        return "❌ Failed to load statistics from the database."

    return (
        "📊 <b>Team JB Downloader — Statistics</b>\n\n"
        f"👥 Total users: <b>{total_users}</b>\n"
        f"🚫 Banned users: <b>{banned_users}</b>\n"
        f"💎 Active premium: <b>{active_premium}</b>\n"
        f"📢 Force-sub channels: <b>{active_channels}</b>\n\n"
        f"📥 Total downloads: <b>{total_downloads}</b>\n"
        f"✅ Completed: <b>{completed_downloads}</b>\n"
        f"❌ Failed: <b>{failed_downloads}</b>\n\n"
        f"🕒 As of {now.strftime('%Y-%m-%d %H:%M UTC')}"
    )


# ── /ban and /unban ───────────────────────────────────────────────────────

def _extract_target_id(message: Message, command: CommandObject) -> int | None:
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id
    if command.args:
        token = command.args.split()[0]
        try:
            return int(token)
        except ValueError:
            return None
    return None


@router.message(Command("ban"), OwnerOnly())
async def cmd_ban(message: Message, command: CommandObject) -> None:
    target_id = _extract_target_id(message, command)
    if target_id is None:
        await message.answer(
            "Usage:\n• Reply to a user's message with /ban\n• Or /ban 123456789"
        )
        return
    if target_id == settings.owner_id:
        await message.answer("🚫 You cannot ban yourself.")
        return
    result = await db.users.update_one(
        {"telegram_id": target_id}, {"$set": {"is_banned": True}}
    )
    if result.matched_count == 0:
        await message.answer(f"⚠️ No user found with ID {target_id}.")
        return
    logger.info("User %d banned by owner %d", target_id, message.from_user.id)
    await message.answer(f"✅ User <code>{target_id}</code> has been banned.")


@router.message(Command("unban"), OwnerOnly())
async def cmd_unban(message: Message, command: CommandObject) -> None:
    target_id = _extract_target_id(message, command)
    if target_id is None:
        await message.answer(
            "Usage:\n• Reply to a user's message with /unban\n• Or /unban 123456789"
        )
        return
    result = await db.users.update_one(
        {"telegram_id": target_id}, {"$set": {"is_banned": False}}
    )
    if result.matched_count == 0:
        await message.answer(f"⚠️ No user found with ID {target_id}.")
        return
    logger.info("User %d unbanned by owner %d", target_id, message.from_user.id)
    await message.answer(f"✅ User <code>{target_id}</code> has been unbanned.")


# ── /broadcast ────────────────────────────────────────────────────────────

@router.message(Command("broadcast"), OwnerOnly())
async def cmd_broadcast(message: Message, command: CommandObject, bot: Bot) -> None:
    source_message = message.reply_to_message
    text = (command.args or "").strip() if command.args else ""
    if source_message is None and not text:
        await message.answer(
            "Usage:\n"
            "• Reply to any message with /broadcast\n"
            "• Or /broadcast your text message"
        )
        return

    await message.answer("📤 Broadcasting... This may take a while.")

    sent = failed = forbidden = 0
    cursor = db.users.find({"is_banned": False}, {"telegram_id": 1})
    async for user_doc in cursor:
        target_id = user_doc["telegram_id"]
        try:
            if source_message is not None:
                await source_message.copy_to(chat_id=target_id)
            else:
                await bot.send_message(chat_id=target_id, text=text)
            sent += 1
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
            try:
                if source_message is not None:
                    await source_message.copy_to(chat_id=target_id)
                else:
                    await bot.send_message(chat_id=target_id, text=text)
                sent += 1
            except Exception:
                failed += 1
        except TelegramForbiddenError:
            forbidden += 1
        except Exception:
            failed += 1
        if sent % 25 == 0:
            await asyncio.sleep(1)

    await db.broadcast_logs.insert_one({
        "admin_id": message.from_user.id,
        "message_text": text or "<media>",
        "sent_count": sent,
        "failed_count": failed,
        "forbidden_count": forbidden,
        "created_at": datetime.now(timezone.utc),
    })
    logger.info("Broadcast: sent=%d failed=%d forbidden=%d", sent, failed, forbidden)
    await message.answer(
        f"✅ <b>Broadcast complete</b>\n\n"
        f"Sent: <b>{sent}</b>\n"
        f"Blocked by user: <b>{forbidden}</b>\n"
        f"Failed: <b>{failed}</b>"
    )


# ── /restart ──────────────────────────────────────────────────────────────

@router.message(Command("restart"), OwnerOnly())
async def cmd_restart(message: Message) -> None:
    await message.answer("🔄 Restarting the bot process...")
    await asyncio.sleep(1)
    logger.info("Owner requested restart; exiting process")
    sys.exit(0)


# ── Force-subscribe channel management ────────────────────────────────────

@router.message(Command("addchannel"), OwnerOnly())
async def cmd_addchannel(message: Message, command: CommandObject) -> None:
    if not command.args:
        await message.answer(
            "Usage:\n"
            "• /addchannel @username\n"
            "• /addchannel -1001234567890   (bot must be admin)"
        )
        return

    raw = command.args.split()[0].strip()

    channel_id: int | None = None
    channel_username: str | None = None
    chat = None

    try:
        if raw.startswith("@"):
            chat = await message.bot.get_chat(raw)
        else:
            chat = await message.bot.get_chat(int(raw))
        channel_id = chat.id
        channel_username = chat.username
    except Exception as exc:
        await message.answer(
            f"❌ Could not resolve channel <code>{raw}</code>.\n"
            f"Make sure the bot is an admin in the channel.\n\n<i>{exc}</i>"
        )
        return

    # Verify bot can check membership.
    try:
        await message.bot.get_chat_member(channel_id, message.bot.id)
    except Exception as exc:
        await message.answer(
            "❌ The bot cannot check membership in this channel.\n"
            "Add the bot as an administrator (with 'View Members' permission) and try again.\n\n"
            f"<i>{exc}</i>"
        )
        return

    # For private channels, generate an invite link.
    invite_link: str | None = None
    if channel_username is None:
        try:
            link_obj = await message.bot.create_chat_invite_link(
                chat_id=channel_id,
                name="TeamJB Force-Sub",
                creates_join_request=False,
            )
            invite_link = link_obj.invite_link
        except Exception as exc:
            await message.answer(
                "❌ Could not create an invite link for this private channel.\n"
                "Make sure the bot has the 'Invite Users via Link' admin permission.\n\n"
                f"<i>{exc}</i>"
            )
            return

    result = await db.force_sub_channels.update_one(
        {"channel_id": channel_id},
        {
            "$set": {
                "channel_id": channel_id,
                "channel_username": channel_username,
                "invite_link": invite_link,
                "is_active": True,
                "added_by": message.from_user.id,
                "added_at": datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )
    action = "updated" if result.upserted_id is None else "added"

    link_display = invite_link if invite_link else f"https://t.me/{channel_username}"
    await message.answer(
        f"✅ Force-sub channel <b>{action}</b>:\n"
        f"ID: <code>{channel_id}</code>\n"
        f"Username: @{channel_username if channel_username else '(private)'}\n"
        f"Invite link: {link_display}"
    )


@router.message(Command("removechannel"), OwnerOnly())
async def cmd_removechannel(message: Message, command: CommandObject) -> None:
    """Remove a force-subscribe channel by username or ID."""
    if not command.args:
        await message.answer("Usage: /removechannel @username  or  /removechannel -1001234567890")
        return

    raw = command.args.split()[0].strip()
    query: dict = {}
    if raw.startswith("@"):
        query["channel_username"] = raw.lstrip("@")
    else:
        try:
            query["channel_id"] = int(raw)
        except ValueError:
            await message.answer("❌ Invalid channel identifier.")
            return

    result = await db.force_sub_channels.delete_one(query)
    if result.deleted_count == 0:
        await message.answer(f"⚠️ No channel found for {raw}.")
        return
    logger.info("Force-sub channel removed: %s", raw)
    await message.answer(f"✅ Channel <b>removed</b>: {raw}")


@router.message(Command("channels"), OwnerOnly())
async def cmd_channels(message: Message) -> None:
    """List all force-subscribe channels."""
    docs = [doc async for doc in db.force_sub_channels.find({})]
    if not docs:
        await message.answer(
            "📢 <b>Force-sub channels</b>\n\nNo channels configured.\n"
            "Add one with /addchannel @username"
        )
        return

    lines = ["📢 <b>Force-sub channels</b>\n"]
    for doc in docs:
        cid = doc.get("channel_id")
        uname = doc.get("channel_username")
        active = doc.get("is_active", False)
        marker = "✅" if active else "⏸️"
        if uname:
            lines.append(f"{marker} @{uname} — <code>{cid}</code>")
        else:
            lines.append(f"{marker} <code>{cid}</code> (private)")
    await message.answer("\n".join(lines))

# ── /expirenow ────────────────────────────────────────────────────────────

@router.message(Command("expirenow"), OwnerOnly())
async def cmd_expirenow(message: Message) -> None:
    """Manually run the subscription expiry cleanup."""
    from services.subscription import expire_subscriptions_once
    count = await expire_subscriptions_once()
    await message.answer(f"✅ Expired <b>{count}</b> subscription(s).")


@router.message(Command("expirenow"))
async def cmd_expirenow_reject(message: Message) -> None:
    await reject_not_owner(message)
