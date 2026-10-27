"""
Team JB Downloader Bot — Active download manager.

Tracks running downloads by progress message ID so that callback handlers
(Cancel, etc.) can find and signal the right task.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class DownloadTask:
    message_id: int
    user_id: int
    url: str
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    extra: dict = field(default_factory=dict)


_active: dict[int, DownloadTask] = {}


def register(message_id: int, user_id: int, url: str, **extra) -> DownloadTask:
    """Create and register a new download task."""
    task = DownloadTask(message_id=message_id, user_id=user_id, url=url, extra=extra)
    _active[message_id] = task
    logger.info("Registered download task for message %d (user %d)", message_id, user_id)
    return task


def get(message_id: int) -> Optional[DownloadTask]:
    return _active.get(message_id)


def unregister(message_id: int) -> None:
    _active.pop(message_id, None)


def cancel(message_id: int) -> bool:
    """Signal cancellation. Returns True if a task was found and signalled."""
    task = _active.get(message_id)
    if task is None:
        return False
    task.cancel_event.set()
    return True


def active_count() -> int:
    return len(_active)
