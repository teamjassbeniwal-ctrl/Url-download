"""
Team JB Downloader Bot — URL handling and download orchestration.

Part 9 scope:
- Detect direct files and yt-dlp sources.
- Download with a simple progress message.
- Upload to Telegram.
- Record in MongoDB and enforce plan limits.
- Trigger referral reward hook after the first successful download.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.types import FSInputFile, Message

from config import settings
from database import db
from services.downloader import download_direct_file, download_via_ytdlp
from services.extractor import extract
from services.referral import maybe_grant_referral_reward
from services.subscription import get_active_plan
from utils.security import UnsafeURLError, is_probably_url, validate_url

logger = logging.getLogger(__name__)

router = Router(name="download")


# ── Daily limit check ─────────────────────────────────────────────────────

async def _check_daily_limit(user_id: int, plan_daily: int) -> bool:
    """Return True if the user is within their daily download limit."""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    count = await db.downloads.count_documents({
        "user_id": user_id,
        "created_at": {"$gte": today_start},
        "status": {"$in": ["completed", "downloading"]},
    })
    return count < plan_daily


# ── Main URL handler ──────────────────────────────────────────────────────

@router.message(F.text & F.func(lambda m: is_probably_url(m.text or "")))
async def handle_url(message: Message, bot: Bot) -> None:
    user = message.from_user
    if user is None:
        return

    url = (message.text or "").strip()

    # 1. Validate URL safety.
    try:
        validate_url(url)
    except UnsafeURLError as exc:
        await message.answer(f"🚫 <b>Blocked</b>\n\n{exc}")
        return

    # 2. Enforce daily limit.
    plan = await get_active_plan(user.id)
    if not await _check_daily_limit(user.id, plan.daily_downloads):
        await message.answer(
            f"📊 <b>Daily limit reached</b>\n\n"
            f"You have used all <b>{plan.daily_downloads}</b> downloads for today "
            f"on the <b>{plan.display_name}</b> plan.\n\n"
            f"Upgrade with /plans for higher limits."
        )
        return

    # 3. Classify the URL.
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

    # 4. Route to the correct download path.
    if result.kind == "direct":
        await _handle_direct(message, status_msg, bot, url, result.direct, plan)
    else:
        await _handle_ytdlp(message, status_msg, bot, url, result.ytdlp, plan)


async def _handle_direct(message: Message, status_msg, bot: Bot, url: str, direct, plan) -> None:
    """Download a direct file and upload it."""
    user_id = message.from_user.id
    dest_dir = settings.download_dir / str(user_id)
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Record the download attempt.
    record = await db.downloads.insert_one({
        "user_id": user_id,
        "url": url,
        "source_type": "direct",
        "status": "downloading",
        "created_at": datetime.now(timezone.utc),
    })
    download_id = record.inserted_id

    last_edit = 0.0

    async def progress_cb(payload: dict) -> None:
        nonlocal last_edit
        if payload.get("status") != "downloading":
            return
        now = asyncio.get_running_loop().time()
        if now - last_edit < 2.0:
            return
        last_edit = now
        downloaded = payload.get("downloaded", 0)
        total = payload.get("total", 0)
        if total > 0:
            pct = downloaded * 100 // total
            text = f"📥 <b>Downloading</b>\n\n{pct}% — {_fmt_bytes(downloaded)} / {_fmt_bytes(total)}"
        else:
            text = f"📥 <b>Downloading</b>\n\n{_fmt_bytes(downloaded)} downloaded"
        try:
            await status_msg.edit_text(text)
        except Exception:
            pass  # Message edit failures are not critical.

    try:
        result = await download_direct_file(url, dest_dir, progress_cb)
    except Exception as exc:
        logger.exception("Direct download failed for %s", url)
        await db.downloads.update_one(
            {"_id": download_id},
            {"$set": {"status": "failed", "error": str(exc)[:500]}},
        )
        await status_msg.edit_text(f"❌ <b>Download failed</b>\n\n{exc}")
        return

    # 5. Enforce file size limit.
    size_mb = result.size_bytes / (1024 * 1024)
    if size_mb > plan.max_file_size_mb:
        result.filepath.unlink(missing_ok=True)
        await db.downloads.update_one(
            {"_id": download_id},
            {"$set": {"status": "failed", "error": "file_too_large", "file_size": result.size_bytes}},
        )
        await status_msg.edit_text(
            f"❌ <b>File too large</b>\n\n"
            f"This file is <b>{size_mb:.1f} MB</b>, but your "
            f"<b>{plan.display_name}</b> plan allows up to "
            f"<b>{plan.max_file_size_mb} MB</b>.\n\n"
            f"Upgrade with /plans for larger files."
        )
        return

    # 6. Upload to Telegram.
    await status_msg.edit_text(f"📤 <b>Uploading</b> — {_fmt_bytes(result.size_bytes)}")
    try:
        await bot.send_document(
            chat_id=message.chat.id,
            document=FSInputFile(str(result.filepath), filename=result.filepath.name),
            caption=f"📄 {result.filepath.name}",
        )
    except Exception as exc:
        logger.exception("Upload failed for %s", result.filepath)
        await db.downloads.update_one(
            {"_id": download_id},
            {"$set": {"status": "failed", "error": f"upload_failed: {exc}"[:500]}},
        )
        await status_msg.edit_text(f"❌ <b>Upload failed</b>\n\n{exc}")
        return

    # 7. Success — record and clean up.
    await db.downloads.update_one(
        {"_id": download_id},
        {"$set": {
            "status": "completed",
            "file_size": result.size_bytes,
            "completed_at": datetime.now(timezone.utc),
        }},
    )
    result.filepath.unlink(missing_ok=True)
    await status_msg.edit_text(
        f"✅ <b>Done</b>\n\n{result.filepath.name} ({_fmt_bytes(result.size_bytes)})"
    )

    # 8. Referral hook (idempotent).
    await maybe_grant_referral_reward(user_id)


async def _handle_ytdlp(message: Message, status_msg, bot: Bot, url: str, ytdlp_info, plan) -> None:
    """Download via yt-dlp using the best format that fits the plan."""
    user_id = message.from_user.id
    dest_dir = settings.download_dir / str(user_id)
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Select a format. Prefer MP4 with both video and audio.
    # Part 10 will add user-selectable formats. For Part 9, pick a sensible default.
    format_selector = "best[ext=mp4]/best"

    # Show the title so the user knows what is being downloaded.
    title = ytdlp_info.title[:100]
    await status_msg.edit_text(f"📥 <b>Downloading</b>\n\n{title}")

    record = await db.downloads.insert_one({
        "user_id": user_id,
        "url": url,
        "source_type": "ytdlp",
        "status": "downloading",
        "title": title,
        "created_at": datetime.now(timezone.utc),
    })
    download_id = record.inserted_id

    last_edit = 0.0

    async def progress_cb(payload: dict) -> None:
        nonlocal last_edit
        if payload.get("status") != "downloading":
            return
        now = asyncio.get_running_loop().time()
        if now - last_edit < 2.0:
            return
        last_edit = now
        downloaded = payload.get("downloaded", 0)
        total = payload.get("total", 0)
        speed = payload.get("speed")
        if total > 0:
            pct = downloaded * 100 // total
            speed_str = f" — {_fmt_bytes(int(speed))}/s" if speed else ""
            text = f"📥 <b>Downloading</b>\n\n{title}\n\n{pct}% — {_fmt_bytes(downloaded)} / {_fmt_bytes(total)}{speed_str}"
        else:
            text = f"📥 <b>Downloading</b>\n\n{title}\n\n{_fmt_bytes(downloaded)} downloaded"
        try:
            await status_msg.edit_text(text)
        except Exception:
            pass

    try:
        result = await download_via_ytdlp(url, format_selector, dest_dir, progress_cb)
    except Exception as exc:
        logger.exception("yt-dlp download failed for %s", url)
        await db.downloads.update_one(
            {"_id": download_id},
            {"$set": {"status": "failed", "error": str(exc)[:500]}},
        )
        await status_msg.edit_text(f"❌ <b>Download failed</b>\n\n{exc}")
        return

    # Enforce size limit.
    size_mb = result.size_bytes / (1024 * 1024)
    if size_mb > plan.max_file_size_mb:
        result.filepath.unlink(missing_ok=True)
        await db.downloads.update_one(
            {"_id": download_id},
            {"$set": {"status": "failed", "error": "file_too_large", "file_size": result.size_bytes}},
        )
        await status_msg.edit_text(
            f"❌ <b>File too large</b>\n\n"
            f"This file is <b>{size_mb:.1f} MB</b>, but your plan allows "
            f"<b>{plan.max_file_size_mb} MB</b>.\n\nUpgrade with /plans."
        )
        return

    # Upload.
    await status_msg.edit_text(f"📤 <b>Uploading</b> — {_fmt_bytes(result.size_bytes)}")
    try:
        # Use send_video for MP4/MKV, send_audio for audio, send_document otherwise.
        ext = result.filepath.suffix.lower()
        file_input = FSInputFile(str(result.filepath), filename=result.filepath.name)
        if ext in {".mp4", ".mkv", ".webm"}:
            await bot.send_video(chat_id=message.chat.id, video=file_input, caption=title)
        elif ext in {".mp3", ".m4a", ".opus", ".ogg"}:
            await bot.send_audio(chat_id=message.chat.id, audio=file_input, caption=title)
        else:
            await bot.send_document(chat_id=message.chat.id, document=file_input, caption=title)
    except Exception as exc:
        logger.exception("Upload failed for %s", result.filepath)
        await db.downloads.update_one(
            {"_id": download_id},
            {"$set": {"status": "failed", "error": f"upload_failed: {exc}"[:500]}},
        )
        await status_msg.edit_text(f"❌ <b>Upload failed</b>\n\n{exc}")
        return

    await db.downloads.update_one(
        {"_id": download_id},
        {"$set": {
            "status": "completed",
            "file_size": result.size_bytes,
            "completed_at": datetime.now(timezone.utc),
        }},
    )
    result.filepath.unlink(missing_ok=True)
    await status_msg.edit_text(f"✅ <b>Done</b>\n\n{title} ({_fmt_bytes(result.size_bytes)})")

    # Referral hook.
    await maybe_grant_referral_reward(user_id)


# ── Helpers ───────────────────────────────────────────────────────────────

def _fmt_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.2f} GB"
