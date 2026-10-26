"""
Team JB Downloader Bot — Referral service.

Handles:
- Building unique referral links.
- Recording referrals when a new user starts with a ref payload.
- Preventing self-referrals, duplicates, and multi-level abuse.
- Granting rewards only after the referred user meets the configured criteria.
- Providing statistics for /refer and /referrals.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from pymongo.errors import DuplicateKeyError

from config import settings
from database import db
from services.subscription import PLANS

logger = logging.getLogger(__name__)


def build_referral_link(bot_username: str, referrer_id: int) -> str:
    """Build a Telegram deep link like https://t.me/MyBot?start=ref_123456."""
    return f"https://t.me/{bot_username}?start=ref_{referrer_id}"


def parse_referral_payload(payload: str) -> Optional[int]:
    """
    Extract the referrer ID from a /start payload.

    Returns None if the payload is not a referral payload.
    Format: ref_<telegram_id>
    """
    payload = (payload or "").strip()
    if not payload.startswith("ref_"):
        return None
    try:
        return int(payload[4:])
    except ValueError:
        return None


async def record_referral(referrer_id: int, referred_id: int) -> tuple[bool, str]:
    """
    Record a referral. Called when a new user /starts with a referral link.

    Anti-abuse checks:
    - Cannot be a self-referral.
    - Cannot be a duplicate (a user can only be referred once).
    - Referrer must exist and not be banned.
    - Referred user must not already be premium (they already qualified another way).

    Returns (success, message).
    """
    if referrer_id == referred_id:
        return False, "self_referral"

    # Referrer must exist and not be banned.
    referrer_doc = await db.users.find_one({"telegram_id": referrer_id})
    if referrer_doc is None:
        return False, "referrer_not_found"
    if referrer_doc.get("is_banned"):
        return False, "referrer_banned"

    # Referred user must not already have an active subscription.
    now = datetime.now(timezone.utc)
    existing_premium = await db.subscriptions.find_one({
        "user_id": referred_id,
        "is_active": True,
        "expires_at": {"$gt": now},
    })
    if existing_premium is not None:
        return False, "already_premium"

    try:
        await db.referrals.insert_one({
            "referrer_id": referrer_id,
            "referred_id": referred_id,
            "reward_granted": False,
            "created_at": now,
        })
    except DuplicateKeyError:
        return False, "already_referred"

    # Record on the referred user's document for quick lookup.
    await db.users.update_one(
        {"telegram_id": referred_id},
        {"$set": {"referred_by": referrer_id}},
    )

    logger.info("Recorded referral: referrer=%d referred=%d", referrer_id, referred_id)
    return True, "recorded"


async def maybe_grant_referral_reward(referred_id: int) -> Optional[int]:
    """
    Called after a qualifying event (download completion).

    Checks if the referred user has met the qualification threshold and, if
    so, grants the reward plan to the referrer. Returns the referrer ID on
    success, None otherwise.

    This function is idempotent: repeated calls for the same referred user
    after the reward has been granted are no-ops.
    """
    # Find the referral record.
    referral = await db.referrals.find_one({"referred_id": referred_id})
    if referral is None:
        return None
    if referral.get("reward_granted"):
        return None

    referrer_id = referral["referrer_id"]
    if referrer_id == referred_id:
        logger.warning("Referral row had self-referral: %d", referred_id)
        return None

    # Count completed downloads by the referred user.
    threshold = settings.referral_min_downloads_to_qualify
    completed = await db.downloads.count_documents({
        "user_id": referred_id,
        "status": "completed",
    })
    if completed < threshold:
        return None

    # Atomically flip reward_granted to prevent double-reward.
    updated = await db.referrals.find_one_and_update(
        {"referred_id": referred_id, "reward_granted": False},
        {"$set": {
            "reward_granted": True,
            "reward_granted_at": datetime.now(timezone.utc),
        }},
        return_document=True,
    )
    if updated is None:
        return None  # Another concurrent call already granted it.

    # Grant the reward plan.
    plan_name = settings.referral_reward_plan
    if plan_name not in PLANS or plan_name == "free":
        logger.error("Invalid referral_reward_plan configured: %s", plan_name)
        return None

    now = datetime.now(timezone.utc)
    existing = await db.subscriptions.find_one(
        {"user_id": referrer_id, "is_active": True, "expires_at": {"$gt": now}},
        sort=[("expires_at", -1)],
    )
    start_from = now
    if existing is not None:
        ex = existing.get("expires_at")
        if isinstance(ex, datetime) and ex > now:
            start_from = ex

    expires_at = start_from + timedelta(days=settings.referral_reward_days)
    await db.subscriptions.insert_one({
        "user_id": referrer_id,
        "plan_name": plan_name,
        "started_at": now,
        "expires_at": expires_at,
        "is_active": True,
        "granted_by": f"referral:{referred_id}",
    })
    await db.users.update_one(
        {"telegram_id": referrer_id},
        {"$set": {"referral_reward_granted": True}},
    )

    logger.info(
        "Referral reward granted: referrer=%d referred=%d plan=%s days=%d",
        referrer_id, referred_id, plan_name, settings.referral_reward_days,
    )
    return referrer_id


async def get_referral_stats(telegram_id: int) -> dict:
    """Return aggregate stats for /refer."""
    total = await db.referrals.count_documents({"referrer_id": telegram_id})
    rewarded = await db.referrals.count_documents(
        {"referrer_id": telegram_id, "reward_granted": True}
    )
    pending = total - rewarded
    return {
        "total": total,
        "rewarded": rewarded,
        "pending": pending,
    }


async def list_referrals(telegram_id: int, limit: int = 20) -> list[dict]:
    """Return recent referrals for /referrals."""
    cursor = (
        db.referrals
        .find({"referrer_id": telegram_id})
        .sort("created_at", -1)
        .limit(limit)
    )
    return [doc async for doc in cursor]
