"""
Team JB Downloader Bot — URL handling and download orchestration.

Part 10:
- Format selection for yt-dlp sources
- Beautiful progress UI with bar, speed, ETA
- Cancel button on every active download
- Upload mode (auto / video / audio / document) from settings
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import settings
from database import db
from services import manager
from services.downloader import download_direct_file, download_via_ytdlp
from services.extractor import ExtractionResult, extract
from services.referral import maybe_grant_referral_reward
from services.subscription import get_active_plan
from utils.progress import (
    ProgressEditor,
    fmt_bytes,
    render_download_progress,
    render_upload_progress,
)
from utils.security import UnsafeURLError, is_probably_url, validate_url

logger = logging.getLogger(__name__)

router = Router(name="download")


class DownloadCancelled(Exception):
    """Raised inside a progress callback when the user taps Cancel."""


# ── Upload mode ───────────────────────────────────────────────────────────

async def _get_upload_mode() -> str:
    """Return the current upload mode from settings. Default 'auto'."""
    try:
        doc = await db.settings.find_one({"_id": "upload_mode"})
        if doc and isinstance(doc.get("value"), str):
            return doc["value"]
    except Exception:
        logger.exception("Failed to read upload_mode setting")
    return "auto"


# ── Daily limit ───────────────────────────────────────────────────────────

async def _check_daily_limit(user_id: int, plan_daily: int) -> bool:
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    count = await db.downloads.count_documents({
        "user_id": user_id,
        "created_at": {"$gte": today_start},
        "status": {"$in": ["completed", "downloading"]},
    })
    return count < plan_daily


# ── Main entry ────────────────────────────────────────────────────────────

@router.message(F.text & F.func(lambda m: is_probably_url(m.text or "")))
async def handle_url(message: Message, bot: Bot) -> None:
    user = message.from_user
    if user is None:
        return

    url = (message.text or "").strip()

    try:
        validate_url(url)
    except UnsafeURLError as exc:
        await message.answer(f"🚫 <b>Blocked</b>\n\n{exc}")
        return

    plan = await get_active_plan(user.id)
    if not await _check_daily_limit(user.id, plan.daily_downloads):
        await message.answer(
            f"📊 <b>Daily limit reached</b>\n\n"
            f"You have used all <b>{plan.daily_downloads}</b> downloads for today "
            f"on the <b>{plan.display_name}</b> plan.\n\n"
            f"Upgrade with /plans for higher limits."
        )
        return

    status_msg = await message.answer("🔍 Analyzing your link...")

    try:
        result = await extract(url)
    except Exception:
        logger.exception("extract failed for %s", url)
        await status_msg.edit_text("❌ Failed to analyze the link. Please try again.")
        return

    if result.kind == "unsupported":
        await status_msg.edit_text(
            f"❌ <b>Unsupported URL</b>\n\n{result.reason}\n\n"
            f"Supported: direct files, YouTube, Instagram, TikTok, Twitter/X, "
            f"Facebook, and other yt-dlp sources."
        )
        return

    if result.kind == "direct":
        await _start_direct_download(message, status_msg, bot, url, result, plan)
    else:
        await _show_format_menu(message, status_msg, result, plan)


# ── Direct download ───────────────────────────────────────────────────────

async def _start_direct_download(message: Message, status_msg, bot: Bot, url: str, result: ExtractionResult, plan) -> None:
    user_id = message.from_user.id
    dest_dir = settings.download_dir / str(user_id)
    dest_dir.mkdir(parents=True, exist_ok=True)

    task = manager.register(status_msg.message_id, user_id, url)
    editor = ProgressEditor(status_msg)

    record = await db.downloads.insert_one({
        "user_id": user_id,
        "url": url,
        "source_type": "direct",
        "status": "downloading",
        "created_at": datetime.now(timezone.utc),
    })
    download_id = record.inserted_id

    async def progress_cb(payload: dict) -> None:
        if task.cancel_event.is_set():
            raise DownloadCancelled()
        if payload.get("status") != "downloading":
            return
        text = render_download_progress(
            payload.get("downloaded", 0),
            payload.get("total", 0),
            speed=None,
            source="Downloading your file",
        )
        await editor.update(text, reply_markup=_cancel_keyboard(status_msg.message_id))

    try:
        await status_msg.edit_text(
            render_download_progress(0, 0, None, "Starting download…"),
            reply_markup=_cancel_keyboard(status_msg.message_id),
        )
        dl_result = await download_direct_file(url, dest_dir, progress_cb)
    except DownloadCancelled:
        await _finalize_cancel(status_msg, download_id)
        manager.unregister(status_msg.message_id)
        return
    except Exception as exc:
        logger.exception("Direct download failed")
        await db.downloads.update_one(
            {"_id": download_id},
            {"$set": {"status": "failed", "error": str(exc)[:500]}},
        )
        await status_msg.edit_text(f"❌ <b>Download failed</b>\n\n{exc}")
        manager.unregister(status_msg.message_id)
        return

    size_mb = dl_result.size_bytes / (1024 * 1024)
    if size_mb > plan.max_file_size_mb:
        dl_result.filepath.unlink(missing_ok=True)
        await db.downloads.update_one(
            {"_id": download_id},
            {"$set": {"status": "failed", "error": "file_too_large"}},
        )
        await status_msg.edit_text(
            f"❌ <b>File too large</b>\n\n{size_mb:.1f} MB exceeds "
            f"your plan limit of {plan.max_file_size_mb} MB."
        )
        manager.unregister(status_msg.message_id)
        return

    await _upload_and_finalize(
        message, status_msg, bot, dl_result, download_id, task, plan,
        title=dl_result.filepath.name,
    )


# ── Format menu for yt-dlp ────────────────────────────────────────────────

def _show_format_menu_kb(formats: list[dict], message_id: int) -> InlineKeyboardMarkup:
    """Build the format selection keyboard for the given yt-dlp formats."""
    builder = InlineKeyboardBuilder()

    # Sort video formats by height (descending), then pick the top 3.
    video = [
        f for f in formats
        if f.get("vcodec") not in (None, "none") and f.get("height")
    ]
    video.sort(key=lambda f: f["height"], reverse=True)
    seen_heights: set[int] = set()
    unique_video = []
    for f in video:
        if f["height"] in seen_heights:
            continue
        seen_heights.add(f["height"])
        unique_video.append(f)
        if len(unique_video) >= 3:
            break

    # Best audio-only format.
    audio = next(
        (f for f in formats if f.get("vcodec") in (None, "none") and f.get("acodec") not in (None, "none")),
        None,
    )

    for f in unique_video:
        label = f"🎬 {f['height']}p"
        builder.row(InlineKeyboardButton(
            text=label,
            callback_data=f"dl:fmt:{message_id}:{f['format_id']}",
        ))

    if audio:
        builder.row(InlineKeyboardButton(
            text="🎵 Audio (MP3)",
            callback_data=f"dl:fmt:{message_id}:{audio['format_id']}",
        ))

    builder.row(InlineKeyboardButton(
        text="📁 Document (best)",
        callback_data=f"dl:fmt:{message_id}:best",
    ))

    builder.row(InlineKeyboardButton(
        text="❌ Cancel",
        callback_data=f"dl:cancel:{message_id}",
    ))
    return builder.as_markup()


async def _show_format_menu(message: Message, status_msg, result: ExtractionResult, plan) -> None:
    info = result.ytdlp
    title = info.title[:120]
    duration = info.duration_seconds or 0
    duration_str = f"{duration // 60}m {duration % 60}s" if duration else "unknown"

    text = (
        f"🔍 <b>Analyzing your link…</b>\n\n"
        f"━━━━━━━━━━━━\n"
        f"🌐 Source: <b>Supported site</b>\n"
        f"🎬 Title: <b>{title}</b>\n"
        f"⏱ Duration: <b>{duration_str}</b>\n"
        f"📁 Available formats: <b>{len(info.formats)}</b>\n\n"
        f"Choose your preferred format below.\n"
        f"Max file size on your plan: <b>{plan.max_file_size_mb} MB</b>"
    )

    # Cache the formats so the callback does not need to re-extract.
    manager.register(
        status_msg.message_id,
        message.from_user.id,
        info.url,
        ytdlp_formats=info.formats,
        ytdlp_title=title,
    )

    await status_msg.edit_text(
        text,
        reply_markup=_show_format_menu_kb(info.formats, status_msg.message_id),
    )


@router.callback_query(F.data.startswith("dl:fmt:"))
async def on_format_selected(call: CallbackQuery, bot: Bot) -> None:
    """User tapped a format button."""
    parts = call.data.split(":", 3)
    if len(parts) != 4:
        await call.answer("Invalid selection.", show_alert=True)
        return
    _, _, message_id_str, format_id = parts
    try:
        message_id = int(message_id_str)
    except ValueError:
        await call.answer("Invalid message ID.", show_alert=True)
        return

    task = manager.get(message_id)
    if task is None or task.user_id != call.from_user.id:
        await call.answer("This download is no longer available.", show_alert=True)
        return

    await call.answer("Starting download…")
    plan = await get_active_plan(call.from_user.id)

    # Convert format_id to a yt-dlp format selector.
    if format_id == "best":
        selector = "best[ext=mp4]/best"
    else:
        selector = f"{format_id}+bestaudio/best"

    # Reuse the status message for progress.
    status_msg = call.message
    await _start_ytdlp_download(status_msg, bot, task, selector, plan)


# ── yt-dlp download ───────────────────────────────────────────────────────

async def _start_ytdlp_download(status_msg: Message, bot: Bot, task, selector: str, plan) -> None:
    user_id = task.user_id
    url = task.url
    dest_dir = settings.download_dir / str(user_id)
    dest_dir.mkdir(parents=True, exist_ok=True)

    title = task.extra.get("ytdlp_title", url)
    editor = ProgressEditor(status_msg)

    record = await db.downloads.insert_one({
        "user_id": user_id,
        "url": url,
        "source_type": "ytdlp",
        "status": "downloading",
        "title": title,
        "created_at": datetime.now(timezone.utc),
    })
    download_id = record.inserted_id

    async def progress_cb(payload: dict) -> None:
        if task.cancel_event.is_set():
            raise DownloadCancelled()
        if payload.get("status") != "downloading":
            return
        text = render_download_progress(
            payload.get("downloaded", 0),
            payload.get("total", 0),
            speed=payload.get("speed"),
            source=title,
        )
        await editor.update(text, reply_markup=_cancel_keyboard(status_msg.message_id))

    try:
        await status_msg.edit_text(
            render_download_progress(0, 0, None, title),
            reply_markup=_cancel_keyboard(status_msg.message_id),
        )
        dl_result = await download_via_ytdlp(url, selector, dest_dir, progress_cb)
    except DownloadCancelled:
        await _finalize_cancel(status_msg, download_id)
        manager.unregister(status_msg.message_id)
        return
    except Exception as exc:
        logger.exception("yt-dlp download failed")
        await db.downloads.update_one(
            {"_id": download_id},
            {"$set": {"status": "failed", "error": str(exc)[:500]}},
        )
        await status_msg.edit_text(f"❌ <b>Download failed</b>\n\n{exc}")
        manager.unregister(status_msg.message_id)
        return

    size_mb = dl_result.size_bytes / (1024 * 1024)
    if size_mb > plan.max_file_size_mb:
        dl_result.filepath.unlink(missing_ok=True)
        await db.downloads.update_one(
            {"_id": download_id},
            {"$set": {"status": "failed", "error": "file_too_large"}},
        )
        await status_msg.edit_text(
            f"❌ <b>File too large</b>\n\n{size_mb:.1f} MB exceeds "
            f"your plan limit of {plan.max_file_size_mb} MB."
        )
        manager.unregister(status_msg.message_id)
        return

    await _upload_and_finalize(
        None, status_msg, bot, dl_result, download_id, task, plan,
        title=title,
    )


# ── Upload ────────────────────────────────────────────────────────────────

async def _upload_and_finalize(
    original_msg,
    status_msg: Message,
    bot: Bot,
    dl_result,
    download_id,
    task,
    plan,
    title: str,
) -> None:
    chat_id = status_msg.chat.id
    user_id = task.user_id

    await status_msg.edit_text(
        render_upload_progress(0, dl_result.size_bytes),
        reply_markup=None,
    )

    # Choose upload method.
    mode = await _get_upload_mode()
    ext = dl_result.filepath.suffix.lower()
    file_input = FSInputFile(str(dl_result.filepath), filename=dl_result.filepath.name)

    try:
        if mode == "video" or (mode == "auto" and ext in {".mp4", ".mkv", ".webm"}):
            await bot.send_video(chat_id=chat_id, video=file_input, caption=title[:1024])
        elif mode == "audio" or (mode == "auto" and ext in {".mp3", ".m4a", ".opus", ".ogg"}):
            await bot.send_audio(chat_id=chat_id, audio=file_input, caption=title[:1024])
        else:
            await bot.send_document(chat_id=chat_id, document=file_input, caption=title[:1024])
    except Exception as exc:
        logger.exception("Upload failed")
        await db.downloads.update_one(
            {"_id": download_id},
            {"$set": {"status": "failed", "error": f"upload_failed: {exc}"[:500]}},
        )
        await status_msg.edit_text(f"❌ <b>Upload failed</b>\n\n{exc}")
        manager.unregister(status_msg.message_id)
        return

    await db.downloads.update_one(
        {"_id": download_id},
        {"$set": {
            "status": "completed",
            "file_size": dl_result.size_bytes,
            "completed_at": datetime.now(timezone.utc),
        }},
    )
    dl_result.filepath.unlink(missing_ok=True)
    await status_msg.edit_text(
        f"✅ <b>Done</b>\n\n"
        f"📦 Size: <b>{fmt_bytes(dl_result.size_bytes)}</b>\n"
        f"📄 Title: <b>{title[:100]}</b>"
    )
    manager.unregister(status_msg.message_id)
    await maybe_grant_referral_reward(user_id)


# ── Cancellation ──────────────────────────────────────────────────────────

def _cancel_keyboard(message_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="❌ Cancel",
        callback_data=f"dl:cancel:{message_id}",
    ))
    return builder.as_markup()


@router.callback_query(F.data.startswith("dl:cancel:"))
async def on_cancel(call: CallbackQuery) -> None:
    parts = call.data.split(":", 2)
    if len(parts) != 3:
        await call.answer("Invalid cancel.", show_alert=True)
        return
    try:
        message_id = int(parts[2])
    except ValueError:
        await call.answer("Invalid message ID.", show_alert=True)
        return

    if manager.cancel(message_id):
        await call.answer("Cancelling…")
    else:
        await call.answer("This download is not active.", show_alert=True)


async def _finalize_cancel(status_msg: Message, download_id) -> None:
    await db.downloads.update_one(
        {"_id": download_id},
        {"$set": {"status": "cancelled", "cancelled_at": datetime.now(timezone.utc)}},
    )
    try:
        await status_msg.edit_text("❌ <b>Cancelled</b>\n\nThe download was stopped.")
    except Exception:
        pass
