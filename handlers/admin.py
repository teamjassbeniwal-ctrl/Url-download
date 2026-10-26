"""
Team JB Downloader Bot — Owner and admin handlers.

Implements:
- /owner    : inline dashboard
- /stats    : bot statistics from MongoDB
- /ban      : ban a user (reply or by ID)
- /unban    : unban a user
- /broadcast: send a message to all users
- /restart  : graceful restart of polling loop
"""

from __future__ import annotations

import asyncio
import logging
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
    """Collect live statistics from MongoDB."""
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
    except Exception:
        logger.exception("Failed to build stats")
        return "❌ Failed to load statistics from the database."

    return (
        "📊 <b>Team JB Downloader — Statistics</b>\n\n"
        f"👥 Total users: <b>{total_users}</b>\n"
        f"🚫 Banned users: <b>{banned_users}</b>\n"
        f"💎 Active premium: <b>{active_premium}</b>\n\n"
        f"📥 Total downloads: <b>{total_downloads}</b>\n"
        f"✅ Completed: <b>{completed_downloads}</b>\n"
        f"❌ Failed: <b>{failed_downloads}</b>\n\n"
        f"🕒 As of {now.strftime('%Y-%m-%d %H:%M UTC')}"
    )


# ── /ban and /unban ───────────────────────────────────────────────────────

def _extract_target_id(message: Message, command: CommandObject) -> int | None:
    """Return the Telegram ID of the user to act on, or None if not resolvable."""
    # Priority 1: reply to a message
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id

    # Priority 2: numeric argument
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
            "Usage:\n"
            "• Reply to a user's message with /ban\n"
            "• Or /ban 123456789"
        )
        return

    if target_id == settings.owner_id:
        await message.answer("🚫 You cannot ban yourself.")
        return

    result = await db.users.update_one(
        {"telegram_id": target_id},
        {"$set": {"is_banned": True}},
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
            "Usage:\n"
            "• Reply to a user's message with /unban\n"
            "• Or /unban 123456789"
        )
        return

    result = await db.users.update_one(
        {"telegram_id": target_id},
        {"$set": {"is_banned": False}},
    )
    if result.matched_count == 0:
        await message.answer(f"⚠️ No user found with ID {target_id}.")
        return

    logger.info("User %d unbanned by owner %d", target_id, message.from_user.id)
    await message.answer(f"✅ User <code>{target_id}</code> has been unbanned.")


# ── /broadcast ────────────────────────────────────────────────────────────

@router.message(Command("broadcast"), OwnerOnly())
async def cmd_broadcast(message: Message, command: CommandObject, bot: Bot) -> None:
    """
    Broadcast a message to all users.

    Usage: reply to any message with /broadcast, or use /broadcast <text>.
    Rate-limited to respect Telegram's ~30 messages/second global limit.
    """
    source_message = message.reply_to_message
    text = (command.args or "").strip() if command.args else ""

    if source_message is None and not text:
        await message.answer(
            "Usage:\n"
            "• Reply to any message (text, photo, video, document) with /broadcast\n"
            "• Or /broadcast your text message"
        )
        return

    await message.answer("📤 Broadcasting... This may take a while.")

    sent = 0
    failed = 0
    forbidden = 0

    # Stream through all users in batches to keep memory bounded.
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

        # Small sleep to avoid hitting the global rate limit.
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

    logger.info("Broadcast by owner: sent=%d failed=%d forbidden=%d", sent, failed, forbidden)
    await message.answer(
        f"✅ <b>Broadcast complete</b>\n\n"
        f"Sent: <b>{sent}</b>\n"
        f"Blocked by user: <b>{forbidden}</b>\n"
        f"Failed: <b>{failed}</b>"
    )


# ── /restart ──────────────────────────────────────────────────────────────

@router.message(Command("restart"), OwnerOnly())
async def cmd_restart(message: Message) -> None:
    """
    Gracefully restart the polling loop.

    Sets a flag that main.py's polling loop checks. If the container is
    managed by Koyeb (which restarts on exit), we simply exit cleanly so
    Koyeb relaunches the process. This avoids stale long-poll connections.
    """
    await message.answer("🔄 Restarting the bot process...")

    # The cleanest approach on Koyeb is to exit and let the platform restart.
    # A short delay gives the reply time to be delivered.
    await asyncio.sleep(1)
    logger.info("Owner requested restart; exiting process")
    import sys
    sys.exit(0)
