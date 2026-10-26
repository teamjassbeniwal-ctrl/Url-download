"""
Team JB Downloader Bot — Coupon helpers.

Atomic coupon redemption without MongoDB transactions.
Safe on standalone MongoDB and Atlas free tier.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from pymongo.errors import DuplicateKeyError

from database import db
from services.subscription import PLANS, grant_subscription

logger = logging.getLogger(__name__)


# Characters used for coupon codes. Avoids ambiguous chars (0/O, 1/I/L).
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _generate_code(length: int = 12, prefix: str = "JB") -> str:
    """Generate a random coupon code like JB-ABCD-EFGH-IJKL."""
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(length))
    groups = [raw[i:i + 4] for i in range(0, len(raw), 4)]
    return f"{prefix}-" + "-".join(groups)


async def create_coupon(
    plan_name: str,
    max_uses: int,
    duration_days: Optional[int],
    created_by: int,
) -> dict:
    """
    Create a new coupon.

    duration_days overrides the plan's default duration if set. Otherwise the
    coupon grants the plan's standard duration.

    Returns the inserted document (including the generated code).
    """
    if plan_name not in PLANS or plan_name == "free":
        raise ValueError(f"Invalid plan_name for coupon: {plan_name}")
    if max_uses < 1:
        raise ValueError("max_uses must be >= 1")

    code = _generate_code()
    # Extremely unlikely collision, but guard against it anyway.
    for _ in range(5):
        existing = await db.coupons.find_one({"code": code})
        if existing is None:
            break
        code = _generate_code()
    else:
        raise RuntimeError("Failed to generate a unique coupon code")

    now = datetime.now(timezone.utc)
    doc = {
        "code": code,
        "plan_name": plan_name,
        "duration_days": duration_days or PLANS[plan_name].duration_days,
        "max_uses": max_uses,
        "used_count": 0,
        "expires_at": None,
        "created_by": created_by,
        "created_at": now,
    }
    await db.coupons.insert_one(doc)
    logger.info("Created coupon %s (plan=%s, uses=%d) by %d",
                code, plan_name, max_uses, created_by)
    return doc


async def list_coupons(include_expired: bool = False) -> list[dict]:
    """Return all coupons sorted by creation date."""
    query: dict = {}
    if not include_expired:
        now = datetime.now(timezone.utc)
        query = {
            "$or": [
                {"expires_at": None},
                {"expires_at": {"$gt": now}},
            ]
        }
    cursor = db.coupons.find(query).sort("created_at", -1)
    return [doc async for doc in cursor]


async def delete_coupon(code: str) -> int:
    """Delete a coupon by code. Returns deleted count."""
    result = await db.coupons.delete_one({"code": code})
    return result.deleted_count


async def redeem_coupon(code: str, telegram_id: int) -> tuple[bool, str, Optional[datetime]]:
    """
    Redeem a coupon for the given user.

    Returns (success, message, expires_at).
    On failure, expires_at is None and message explains the reason.
    """
    code = code.strip().upper()
    if not code:
        return False, "Empty coupon code.", None

    now = datetime.now(timezone.utc)

    # 1. Atomically reserve a use.
    reserved = await db.coupons.find_one_and_update(
        {
            "code": code,
            "$or": [
                {"expires_at": None},
                {"expires_at": {"$gt": now}},
            ],
            "$expr": {"$lt": ["$used_count", "$max_uses"]},
        },
        {"$inc": {"used_count": 1}},
        return_document=True,
    )
    if reserved is None:
        # Distinguish "not found" / "expired" / "exhausted" for the user.
        doc = await db.coupons.find_one({"code": code})
        if doc is None:
            return False, "Coupon not found.", None
        expiry = doc.get("expires_at")
        if isinstance(expiry, datetime) and expiry <= now:
            return False, "Coupon has expired.", None
        return False, "Coupon has been fully redeemed.", None

    # 2. Record the redemption (unique on code+user).
    try:
        await db.coupon_redemptions.insert_one({
            "coupon_code": code,
            "user_id": telegram_id,
            "redeemed_at": now,
        })
    except DuplicateKeyError:
        # Same user already redeemed. Give back the use we just reserved.
        await db.coupons.update_one({"code": code}, {"$inc": {"used_count": -1}})
        return False, "You have already redeemed this coupon.", None

    # 3. Grant the subscription.
    plan_name = reserved["plan_name"]
    duration_days = reserved.get("duration_days") or PLANS[plan_name].duration_days

    try:
        # Inline grant to support custom durations (coupons can be shorter than
        # the plan's standard duration).
        from datetime import timedelta as _td
        existing = await db.subscriptions.find_one(
            {"user_id": telegram_id, "is_active": True, "expires_at": {"$gt": now}},
            sort=[("expires_at", -1)],
        )
        start_from = now
        if existing is not None:
            ex = existing.get("expires_at")
            if isinstance(ex, datetime) and ex > now:
                start_from = ex

        expires_at = start_from + _td(days=duration_days)
        await db.subscriptions.insert_one({
            "user_id": telegram_id,
            "plan_name": plan_name,
            "started_at": now,
            "expires_at": expires_at,
            "is_active": True,
            "granted_by": f"coupon:{code}",
        })
    except Exception:
        logger.exception("Coupon grant failed for %s user %d; rolling back",
                         code, telegram_id)
        # Roll back the reservation and the redemption record.
        await db.coupons.update_one({"code": code}, {"$inc": {"used_count": -1}})
        await db.coupon_redemptions.delete_one({
            "coupon_code": code, "user_id": telegram_id,
        })
        return False, "Failed to apply premium. Please try again or contact support.", None

    logger.info("Coupon %s redeemed by %d (plan=%s until %s)",
                code, telegram_id, plan_name, expires_at.isoformat())
    return True, f"Coupon redeemed! You now have {plan_name} until {expires_at.strftime('%Y-%m-%d')}.", expires_at
