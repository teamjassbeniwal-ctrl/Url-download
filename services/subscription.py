"""
Team JB Downloader Bot — Subscription helpers.

Central module for checking and managing user subscriptions. Any other
service or handler that needs to know "is this user premium, and what are
their limits?" should call get_active_plan().
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import settings
from database import db

logger = logging.getLogger(__name__)


# ── Plan catalogue ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Plan:
    name: str
    display_name: str
    duration_days: int
    price_inr: int
    max_file_size_mb: int
    daily_downloads: int
    concurrent_downloads: int


PLANS: dict[str, Plan] = {
    "free": Plan(
        name="free",
        display_name="🆓 Free",
        duration_days=0,
        price_inr=0,
        max_file_size_mb=settings.free_max_file_size_mb,
        daily_downloads=settings.free_daily_downloads,
        concurrent_downloads=settings.max_concurrent_downloads_free,
    ),
    "weekly": Plan(
        name="weekly",
        display_name="⭐ Weekly",
        duration_days=7,
        price_inr=49,
        max_file_size_mb=500,
        daily_downloads=30,
        concurrent_downloads=2,
    ),
    "monthly": Plan(
        name="monthly",
        display_name="💎 Monthly",
        duration_days=30,
        price_inr=149,
        max_file_size_mb=1000,
        daily_downloads=100,
        concurrent_downloads=3,
    ),
    "yearly": Plan(
        name="yearly",
        display_name="👑 Yearly",
        duration_days=365,
        price_inr=999,
        max_file_size_mb=2000,
        daily_downloads=500,
        concurrent_downloads=5,
    ),
}


# ── Active plan resolution ────────────────────────────────────────────────

async def get_active_plan(telegram_id: int) -> Plan:
    """
    Return the user's currently active plan, or the Free plan if none.

    Checks the subscriptions collection for an active, non-expired record.
    If multiple exist, the one with the latest expiry wins.
    """
    now = datetime.now(timezone.utc)
    try:
        doc = await db.subscriptions.find_one(
            {
                "user_id": telegram_id,
                "is_active": True,
                "expires_at": {"$gt": now},
            },
            sort=[("expires_at", -1)],
        )
    except Exception:
        logger.exception("get_active_plan: DB error for user %d", telegram_id)
        return PLANS["free"]

    if doc is None:
        return PLANS["free"]

    plan_name = doc.get("plan_name", "free")
    return PLANS.get(plan_name, PLANS["free"])


async def get_active_subscription(telegram_id: int) -> Optional[dict]:
    """
    Return the raw subscription document if active, else None.
    Used by /myplan to display the expiry date.
    """
    now = datetime.now(timezone.utc)
    try:
        return await db.subscriptions.find_one(
            {
                "user_id": telegram_id,
                "is_active": True,
                "expires_at": {"$gt": now},
            },
            sort=[("expires_at", -1)],
        )
    except Exception:
        logger.exception("get_active_subscription: DB error for user %d", telegram_id)
        return None


# ── Grant / revoke (used by Part 7 admin commands) ────────────────────────

async def grant_subscription(
    telegram_id: int,
    plan_name: str,
    granted_by: str,
) -> datetime:
    """
    Create a new active subscription.

    If the user already has an active subscription, the new one extends from
    the later of (now, existing expiry). Returns the new expiry date.
    """
    plan = PLANS.get(plan_name)
    if plan is None or plan.duration_days <= 0:
        raise ValueError(f"Invalid plan_name: {plan_name}")

    now = datetime.now(timezone.utc)
    existing = await get_active_subscription(telegram_id)
    start_from = now
    if existing is not None:
        existing_expiry = existing.get("expires_at")
        if isinstance(existing_expiry, datetime) and existing_expiry > now:
            start_from = existing_expiry

    expires_at = start_from + timedelta(days=plan.duration_days)

    await db.subscriptions.insert_one({
        "user_id": telegram_id,
        "plan_name": plan_name,
        "started_at": now,
        "expires_at": expires_at,
        "is_active": True,
        "granted_by": granted_by,
    })

    logger.info(
        "Granted plan=%s to user=%d until %s (by %s)",
        plan_name, telegram_id, expires_at.isoformat(), granted_by,
    )
    return expires_at


async def revoke_subscription(telegram_id: int) -> int:
    """Mark all active subscriptions for a user as inactive. Returns count."""
    result = await db.subscriptions.update_many(
        {"user_id": telegram_id, "is_active": True},
        {"$set": {"is_active": False, "revoked_at": datetime.now(timezone.utc)}},
    )
    if result.modified_count:
        logger.info("Revoked %d subscription(s) for user %d",
                    result.modified_count, telegram_id)
    return result.modified_count


# ── Expiry worker ─────────────────────────────────────────────────────────

async def expire_subscriptions_once() -> int:
    """
    Mark every expired-but-still-active subscription as inactive.

    Returns the number of subscriptions modified. Called by the hourly task
    in main.py and by an owner command in Part 7.
    """
    now = datetime.now(timezone.utc)
    result = await db.subscriptions.update_many(
        {"is_active": True, "expires_at": {"$lte": now}},
        {"$set": {"is_active": False, "expired_at": now}},
    )
    if result.modified_count:
        logger.info("Expired %d subscription(s)", result.modified_count)
    return result.modified_count


async def subscription_expiry_worker(interval_seconds: int = 3600) -> None:
    """
    Background task that expires subscriptions periodically.

    Runs forever until cancelled. On cancellation, logs and returns cleanly.
    """
    import asyncio

    logger.info("Subscription expiry worker started (interval=%ds)", interval_seconds)
    try:
        while True:
            try:
                await expire_subscriptions_once()
            except Exception:
                logger.exception("Subscription expiry worker: unexpected error")
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        logger.info("Subscription expiry worker stopped")
        raise
