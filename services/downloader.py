"""
Team JB Downloader Bot — Download engine.

Provides:
- download_direct_file : HTTP streaming with progress callback
- download_via_ytdlp   : yt-dlp download bridged to asyncio with progress
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Optional

import aiofiles
import aiohttp
import yt_dlp

from config import settings
from utils.security import validate_url

logger = logging.getLogger(__name__)


ProgressCallback = Callable[[dict], Awaitable[None]]


@dataclass
class DownloadResult:
    filepath: Path
    size_bytes: int
    title: str = ""


# ── Direct file download ──────────────────────────────────────────────────

async def download_direct_file(
    url: str,
    dest_dir: Path,
    progress_cb: Optional[ProgressCallback] = None,
) -> DownloadResult:
    """
    Download a direct file with streaming and progress.

    progress_cb receives dicts like:
        {"status": "downloading", "downloaded": int, "total": int, "speed": float}
        {"status": "finished", "filepath": str}
    """
    validate_url(url)
    dest_dir.mkdir(parents=True, exist_ok=True)

    headers = {"User-Agent": "TeamJB-Downloader/1.0"}
    timeout = aiohttp.ClientTimeout(total=settings.download_timeout_seconds)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers=headers, allow_redirects=True) as resp:
            if resp.status >= 400:
                raise RuntimeError(f"HTTP {resp.status} while downloading")

            total = int(resp.headers.get("Content-Length") or 0)
            filename = _extract_filename(resp, url)
            filepath = _unique_path(dest_dir, filename)

            downloaded = 0
            last_report = 0.0
            async with aiofiles.open(filepath, "wb") as f:
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    await f.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb is not None:
                        now = asyncio.get_running_loop().time()
                        if now - last_report >= 1.0:
                            last_report = now
                            await progress_cb({
                                "status": "downloading",
                                "downloaded": downloaded,
                                "total": total,
                                "filename": filename,
                            })

            if progress_cb is not None:
                await progress_cb({
                    "status": "finished",
                    "filepath": str(filepath),
                    "downloaded": downloaded,
                    "total": total,
                })

    return DownloadResult(filepath=filepath, size_bytes=downloaded)


def _extract_filename(resp: aiohttp.ClientResponse, url: str) -> str:
    cd = resp.headers.get("Content-Disposition", "")
    if "filename=" in cd:
        part = cd.split("filename=", 1)[1].strip().strip('"').strip("'")
        if part:
            return part
    from urllib.parse import urlparse
    path = urlparse(url).path
    name = path.rsplit("/", 1)[-1] if path else ""
    return name or "download.bin"


def _unique_path(dest_dir: Path, filename: str) -> Path:
    candidate = dest_dir / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    for i in range(1, 1000):
        candidate = dest_dir / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError("Could not find a unique filename")


# ── yt-dlp download ───────────────────────────────────────────────────────

def _ytdlp_download_sync(
    url: str,
    format_selector: str,
    output_dir: Path,
    progress_hook: Callable[[dict], None],
) -> str:
    """Blocking yt-dlp download. Returns the final filepath."""
    opts = {
        "format": format_selector,
        "outtmpl": str(output_dir / "%(title).80s-%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "progress_hooks": [progress_hook],
        "restrictfilenames": True,
        "trim_file_name": 100,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if info is None:
            raise RuntimeError("yt-dlp returned no info")
        # requested_downloads contains the final path after post-processing.
        requested = info.get("requested_downloads") or []
        if requested:
            fp = requested[0].get("filepath")
            if fp:
                return fp
        # Fallback: prepare_filename
        return ydl.prepare_filename(info)


async def download_via_ytdlp(
    url: str,
    format_selector: str,
    dest_dir: Path,
    progress_cb: Optional[ProgressCallback] = None,
) -> DownloadResult:
    """
    Download using yt-dlp. Runs the blocking download in a thread pool and
    bridges progress hooks back to the asyncio loop.
    """
    validate_url(url)
    dest_dir.mkdir(parents=True, exist_ok=True)

    loop = asyncio.get_running_loop()

    def _bridge_hook(d: dict) -> None:
        """Called from the yt-dlp worker thread. Schedule the async callback."""
        if progress_cb is None:
            return
        if d.get("status") not in {"downloading", "finished"}:
            return
        payload = {
            "status": d.get("status"),
            "downloaded": d.get("downloaded_bytes") or 0,
            "total": d.get("total_bytes") or d.get("total_bytes_estimate") or 0,
            "speed": d.get("speed"),
            "eta": d.get("eta"),
        }
        asyncio.run_coroutine_threadsafe(progress_cb(payload), loop)

    filepath_str = await loop.run_in_executor(
        None, _ytdlp_download_sync, url, format_selector, dest_dir, _bridge_hook
    )

    filepath = Path(filepath_str)
    if not filepath.exists():
        raise RuntimeError(f"yt-dlp reported success but file not found: {filepath}")

    size = filepath.stat().st_size
    if progress_cb is not None:
        await progress_cb({"status": "finished", "filepath": str(filepath), "downloaded": size, "total": size})

    return DownloadResult(filepath=filepath, size_bytes=size)
