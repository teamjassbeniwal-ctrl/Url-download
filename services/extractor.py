"""
Team JB Downloader Bot — URL classification and yt-dlp extraction.

Determines whether a URL is a direct file, a yt-dlp-supported source, or
unsupported. All yt-dlp calls run in a thread pool to avoid blocking the
event loop.

YouTube cookies: if /app/cookies.txt exists, yt-dlp will use it. This is
optional and the bot degrades gracefully if the file is missing.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

import aiohttp
import yt_dlp

from utils.security import validate_url

logger = logging.getLogger(__name__)

COOKIE_FILE = "/app/cookies.txt"


@dataclass
class DirectFileInfo:
    url: str
    filename: str
    content_type: str
    size_bytes: Optional[int] = None


@dataclass
class YtdlpInfo:
    url: str
    title: str
    duration_seconds: Optional[int]
    thumbnail_url: Optional[str]
    formats: list[dict] = field(default_factory=list)


@dataclass
class ExtractionResult:
    kind: str  # "direct", "ytdlp", "unsupported"
    direct: Optional[DirectFileInfo] = None
    ytdlp: Optional[YtdlpInfo] = None
    reason: str = ""


# ── Direct file detection ─────────────────────────────────────────────────

_DIRECT_CONTENT_PREFIXES = (
    "application/",
    "video/",
    "audio/",
    "image/",
)
_DIRECT_CONTENT_EXACT = {
    "text/plain",
    "application/octet-stream",
    "binary/octet-stream",
}


async def _probe_direct_file(url: str, timeout: int = 15) -> Optional[DirectFileInfo]:
    """HEAD-request the URL to see if it is a direct file."""
    headers = {"User-Agent": "TeamJB-Downloader/1.0"}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.head(url, headers=headers, allow_redirects=True) as resp:
                if resp.status >= 400:
                    return None
                content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                content_length = resp.headers.get("Content-Length")
                filename = _filename_from_response(resp, url)
                if _is_direct_content_type(content_type):
                    return DirectFileInfo(
                        url=str(resp.url),
                        filename=filename,
                        content_type=content_type,
                        size_bytes=int(content_length) if content_length and content_length.isdigit() else None,
                    )
                return None
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return None


def _is_direct_content_type(content_type: str) -> bool:
    if not content_type:
        return False
    if content_type in _DIRECT_CONTENT_EXACT:
        return True
    return any(content_type.startswith(prefix) for prefix in _DIRECT_CONTENT_PREFIXES)


def _filename_from_response(resp: aiohttp.ClientResponse, fallback_url: str) -> str:
    cd = resp.headers.get("Content-Disposition", "")
    if "filename=" in cd:
        part = cd.split("filename=", 1)[1].strip().strip('"').strip("'")
        if part:
            return part
    path = urlparse(fallback_url).path
    return path.rsplit("/", 1)[-1] or "download.bin"


# ── yt-dlp extraction ─────────────────────────────────────────────────────

def _ytdlp_extract_sync(url: str) -> Optional[dict]:
    """Blocking yt-dlp extraction. Runs in a thread pool."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "extract_flat": False,
    }

    # Add cookies if the file exists.
    if os.path.isfile(COOKIE_FILE):
        opts["cookiefile"] = COOKIE_FILE

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info is None:
                return None
            return info
    except yt_dlp.utils.DownloadError as exc:
        logger.info("yt-dlp extract_info failed for %s: %s", url, exc)
        return None
    except Exception:
        logger.exception("yt-dlp extract_info unexpected error for %s", url)
        return None


def _build_formats(info: dict) -> list[dict]:
    formats = info.get("formats") or []
    result = []
    for f in formats:
        if not f.get("url"):
            continue
        if f.get("format_note") == "storyboard":
            continue
        result.append({
            "format_id": f.get("format_id"),
            "ext": f.get("ext"),
            "height": f.get("height"),
            "width": f.get("width"),
            "filesize": f.get("filesize") or f.get("filesize_approx"),
            "vcodec": f.get("vcodec"),
            "acodec": f.get("acodec"),
            "format_note": f.get("format_note"),
            "url": f.get("url"),
        })
    return result


async def _extract_with_ytdlp(url: str) -> Optional[YtdlpInfo]:
    loop = asyncio.get_running_loop()
    info = await loop.run_in_executor(None, _ytdlp_extract_sync, url)
    if info is None:
        return None
    return YtdlpInfo(
        url=url,
        title=info.get("title") or "Unknown title",
        duration_seconds=info.get("duration"),
        thumbnail_url=info.get("thumbnail"),
        formats=_build_formats(info),
    )


# ── Public entry point ────────────────────────────────────────────────────

async def extract(url: str) -> ExtractionResult:
    """Classify and extract metadata for a user-submitted URL."""
    try:
        validate_url(url)
    except Exception as exc:
        return ExtractionResult(kind="unsupported", reason=str(exc))

    direct = await _probe_direct_file(url)
    if direct is not None:
        return ExtractionResult(kind="direct", direct=direct)

    ytdlp_info = await _extract_with_ytdlp(url)
    if ytdlp_info is not None and ytdlp_info.formats:
        return ExtractionResult(kind="ytdlp", ytdlp=ytdlp_info)

    return ExtractionResult(
        kind="unsupported",
        reason="This URL is not a direct file and is not supported by yt-dlp.",
    )
