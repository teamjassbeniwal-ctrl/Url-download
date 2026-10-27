"""
Team JB Downloader Bot — Progress bar rendering and throttled message editor.

Renders download progress as a Unicode progress bar with speed and ETA,
and throttles Telegram message edits to avoid rate limits.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from aiogram.types import Message

logger = logging.getLogger(__name__)

_BAR_WIDTH = 16
_FILL = "█"
_EMPTY = "░"

# Minimum seconds between Telegram message edits.
_THROTTLE_SECONDS = 3.0


def fmt_bytes(n: int) -> str:
    """Human-readable byte count."""
    if n is None or n < 0:
        return "?"
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.2f} GB"


def render_bar(percent: float) -> str:
    """Render a filled progress bar of width _BAR_WIDTH."""
    percent = max(0.0, min(100.0, percent))
    filled = int(_BAR_WIDTH * percent / 100.0)
    empty = _BAR_WIDTH - filled
    return f"[{_FILL * filled}{_EMPTY * empty}]"


def render_download_progress(
    downloaded: int,
    total: int,
    speed: Optional[float],
    source: str = "Downloading",
) -> str:
    """Format a download progress message with title, bar, and stats."""
    if total > 0:
        percent = downloaded * 100.0 / total
        bar = render_bar(percent)
        stats = f"📦 <b>{fmt_bytes(downloaded)}</b> / {fmt_bytes(total)}"
        pct_line = f"<b>{percent:.0f}%</b>"
    else:
        bar = render_bar(0)
        stats = f"📦 <b>{fmt_bytes(downloaded)}</b> downloaded"
        pct_line = "Calculating…"

    extra = []
    if speed and speed > 0:
        extra.append(f"⚡ {fmt_bytes(int(speed))}/s")
        if total > 0 and downloaded > 0:
            eta = int((total - downloaded) / speed)
            if eta > 0:
                extra.append(f"⏳ ETA {eta}s")
    speed_line = " — ".join(extra)

    return (
        f"📥 <b>{source}</b>\n\n"
        f"{bar} {pct_line}\n"
        f"{stats}\n"
        + (f"{speed_line}\n" if speed_line else "")
        + f"\n🧩 Status: <b>Downloading</b>"
    )


def render_upload_progress(percent: float, size: int) -> str:
    """Format an upload progress message (approximate — Telegram does not report upload progress)."""
    bar = render_bar(percent)
    return (
        f"📤 <b>Uploading to Telegram</b>\n\n"
        f"{bar} <b>{percent:.0f}%</b>\n"
        f"📦 <b>{fmt_bytes(size)}</b>\n"
        f"\n🧩 Status: <b>Uploading</b>"
    )


class ProgressEditor:
    """
    Throttled editor for a single progress message.

    Call `update(text, markup=None)` as often as needed. The editor will
    only send a Telegram edit if more than _THROTTLE_SECONDS have elapsed
    since the last edit. Call `flush(text)` to force an update.
    """

    def __init__(self, message: Message) -> None:
        self._message = message
        self._last_edit = 0.0

    async def update(self, text: str, markup=None) -> None:
        now = time.monotonic()
        if now - self._last_edit < _THROTTLE_SECONDS:
            return
        self._last_edit = now
        try:
            await self._message.edit_text(text, reply_markup=markup)
        except Exception:
            # Message edit failures are common (message too old, unchanged text).
            pass

    async def flush(self, text: str, markup=None) -> None:
        """Force an edit regardless of throttle."""
        self._last_edit = time.monotonic()
        try:
            await self._message.edit_text(text, reply_markup=markup)
        except Exception:
            pass
