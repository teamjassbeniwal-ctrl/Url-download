"""
Team JB Downloader Bot — MongoDB connection and index management.

Uses PyMongo's native AsyncMongoClient (pymongo.asynchronous).
No Motor. No SQLAlchemy.

Responsibilities:
- Create and own the AsyncMongoClient singleton.
- Verify connectivity at startup (ping).
- Create all required indexes on startup.
- Provide typed accessors for collections.
- Close the client cleanly on shutdown.
"""

from __future__ import annotations

import logging
from typing import Optional

from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.asynchronous.mongo_client import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

from config import settings

logger = logging.getLogger(__name__)


class Database:
    """
    Owns the MongoDB client and database handle.

    Instantiate once during application startup, call `connect()` to verify
    and create indexes, and `close()` on shutdown.
    """

    def __init__(self) -> None:
        self._client: Optional[AsyncMongoClient] = None
        self._db: Optional[AsyncDatabase] = None

    async def connect(self) -> None:
        """
        Create the AsyncMongoClient, verify connectivity, and create indexes.

        Raises ConnectionFailure or ServerSelectionTimeoutError if the server
        is unreachable, which should abort application startup.
        """
        if self._client is not None:
            logger.warning("Database.connect() called twice; ignoring")
            return

        logger.info("Connecting to MongoDB: %s", settings.redacted_mongodb_uri)

        # Build connection kwargs. TLS is only passed when explicitly enabled;
        # mongodb+srv:// URIs negotiate TLS automatically.
        connection_kwargs: dict = {
            "serverSelectionTimeoutMS": settings.mongodb_server_selection_timeout_ms,
            "connectTimeoutMS": 10000,
        }
        if settings.mongodb_tls and settings.mongodb_uri.startswith("mongodb://"):
            connection_kwargs["tls"] = True

        self._client = AsyncMongoClient(
            settings.mongodb_uri,
            **connection_kwargs,
        )

        try:
            await self._client.admin.command("ping")
            logger.info("MongoDB ping successful")
        except (ConnectionFailure, ServerSelectionTimeoutError) as exc:
            logger.error("MongoDB connection failed: %s", exc)
            await self._client.close()
            self._client = None
            raise

        self._db = self._client[settings.mongodb_database]
        await self._ensure_indexes()
        logger.info("MongoDB database '%s' ready", settings.mongodb_database)

    async def _ensure_indexes(self) -> None:
        """
        Create all indexes. Safe to call on every startup — MongoDB ignores
        requests for indexes that already exist with identical specifications.
        """
        assert self._db is not None

        # ── users ─────────────────────────────────────────────────────────
        await self._db.users.create_indexes([
            IndexModel([("telegram_id", ASCENDING)], unique=True, name="uniq_telegram_id"),
            IndexModel([("created_at", DESCENDING)], name="idx_created_at"),
            IndexModel([("referred_by", ASCENDING)], sparse=True, name="idx_referred_by"),
        ])

        # ── subscriptions ─────────────────────────────────────────────────
        await self._db.subscriptions.create_indexes([
            IndexModel([("user_id", ASCENDING), ("is_active", ASCENDING)], name="idx_user_active"),
            IndexModel([("expires_at", ASCENDING)], name="idx_expires_at"),
        ])

        # ── coupons ───────────────────────────────────────────────────────
        await self._db.coupons.create_indexes([
            IndexModel([("code", ASCENDING)], unique=True, name="uniq_code"),
            IndexModel([("expires_at", ASCENDING)], name="idx_coupon_expires"),
        ])

        # ── coupon_redemptions ────────────────────────────────────────────
        await self._db.coupon_redemptions.create_indexes([
            IndexModel(
                [("coupon_code", ASCENDING), ("user_id", ASCENDING)],
                unique=True,
                name="uniq_coupon_user",
            ),
            IndexModel([("user_id", ASCENDING)], name="idx_redemption_user"),
        ])

        # ── referrals ─────────────────────────────────────────────────────
        await self._db.referrals.create_indexes([
            IndexModel([("referred_id", ASCENDING)], unique=True, name="uniq_referred"),
            IndexModel([("referrer_id", ASCENDING)], name="idx_referrer"),
        ])

        # ── force_sub_channels ────────────────────────────────────────────
        await self._db.force_sub_channels.create_indexes([
            IndexModel([("channel_id", ASCENDING)], unique=True, name="uniq_channel_id"),
            IndexModel([("is_active", ASCENDING)], name="idx_channel_active"),
        ])

        # ── downloads ─────────────────────────────────────────────────────
        await self._db.downloads.create_indexes([
            IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)], name="idx_user_downloads"),
            IndexModel([("status", ASCENDING)], name="idx_download_status"),
        ])

        # ── settings ──────────────────────────────────────────────────────
        # _id is the key; automatic unique index suffices.

        # ── broadcast_logs ────────────────────────────────────────────────
        await self._db.broadcast_logs.create_indexes([
            IndexModel([("created_at", DESCENDING)], name="idx_broadcast_created"),
        ])

        # ── download_queue ────────────────────────────────────────────────
        await self._db.download_queue.create_indexes([
            IndexModel(
                [("status", ASCENDING), ("priority", DESCENDING), ("created_at", ASCENDING)],
                name="idx_queue_pick",
            ),
            IndexModel([("user_id", ASCENDING), ("status", ASCENDING)], name="idx_queue_user"),
        ])

        logger.info("MongoDB indexes ensured")

    async def close(self) -> None:
        """Close the MongoDB client. Safe to call multiple times."""
        if self._client is not None:
            await self._client.close()
            self._client = None
            self._db = None
            logger.info("MongoDB client closed")

    # ── Collection accessors ──────────────────────────────────────────────
    # Handlers and services use these instead of touching _db directly.

    @property
    def users(self) -> AsyncCollection:
        assert self._db is not None, "Database not connected"
        return self._db.users

    @property
    def subscriptions(self) -> AsyncCollection:
        assert self._db is not None, "Database not connected"
        return self._db.subscriptions

    @property
    def coupons(self) -> AsyncCollection:
        assert self._db is not None, "Database not connected"
        return self._db.coupons

    @property
    def coupon_redemptions(self) -> AsyncCollection:
        assert self._db is not None, "Database not connected"
        return self._db.coupon_redemptions

    @property
    def referrals(self) -> AsyncCollection:
        assert self._db is not None, "Database not connected"
        return self._db.referrals

    @property
    def force_sub_channels(self) -> AsyncCollection:
        assert self._db is not None, "Database not connected"
        return self._db.force_sub_channels

    @property
    def downloads(self) -> AsyncCollection:
        assert self._db is not None, "Database not connected"
        return self._db.downloads

    @property
    def settings(self) -> AsyncCollection:
        assert self._db is not None, "Database not connected"
        return self._db.settings

    @property
    def broadcast_logs(self) -> AsyncCollection:
        assert self._db is not None, "Database not connected"
        return self._db.broadcast_logs

    @property
    def download_queue(self) -> AsyncCollection:
        assert self._db is not None, "Database not connected"
        return self._db.download_queue

    @property
    def client(self) -> AsyncMongoClient:
        assert self._client is not None, "Database not connected"
        return self._client


# Singleton instance. Imported by middleware and future services.
db = Database()
