"""
Team JB Downloader Bot — Configuration Module.
Python 3.12 compatible. All values from environment variables.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Required ──────────────────────────────────────────────────────────
    bot_token: str = Field(..., description="Telegram bot token from @BotFather")
    owner_id: int = Field(..., description="Telegram numeric user ID of the owner")
    fernet_key: str = Field(..., description="Fernet key for encrypting sensitive data")
    mongodb_uri: str = Field(
        default="mongodb+srv://teamjassbeniwal_db_user:jassbeniwal2005@cluster0.pfxdcwy.mongodb.net/botdb?retryWrites=true&w=majority",
        description="MongoDB connection URI (mongodb:// or mongodb+srv://)",
    )
    mongodb_database: str = Field(
        default="teamjb_downloader",
        description="MongoDB database name",
    )

    # ── Optional Telegram ─────────────────────────────────────────────────
    telegram_api_id: Optional[int] = Field(default=None)
    telegram_api_hash: Optional[str] = Field(default=None)
    telegram_api_server: Optional[str] = Field(default=None)

    # ── Optional MongoDB ──────────────────────────────────────────────────
    mongodb_tls: bool = Field(default=False)
    mongodb_server_selection_timeout_ms: int = Field(default=5000, ge=1000, le=60000)

    # ── Optional services ─────────────────────────────────────────────────
    redis_url: Optional[str] = Field(default=None)
    gdrive_credentials_json: Optional[str] = Field(default=None)
    gdrive_service_account_email: Optional[str] = Field(default=None)

    # ── Limits ────────────────────────────────────────────────────────────
    free_max_file_size_mb: int = Field(default=50, ge=1, le=2000)
    premium_max_file_size_mb: int = Field(default=2000, ge=1, le=2000)
    free_daily_downloads: int = Field(default=5, ge=1)
    premium_daily_downloads: int = Field(default=100, ge=1)
    max_concurrent_downloads_free: int = Field(default=1, ge=1)
    max_concurrent_downloads_premium: int = Field(default=5, ge=1)
    download_timeout_seconds: int = Field(default=1800, ge=60)
    temp_cleanup_hours: int = Field(default=6, ge=1)

    # ── Paths & logging ───────────────────────────────────────────────────
    download_dir: Path = Field(default=Path("/app/data/downloads"))
    thumbnail_dir: Path = Field(default=Path("/app/data/thumbnails"))
    log_dir: Path = Field(default=Path("/app/logs"))
    log_level: str = Field(default="INFO")
    log_file: Optional[str] = Field(default=None)

    # ── Health ────────────────────────────────────────────────────────────
    health_port: int = Field(default=8080)

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {allowed}, got {v}")
        return upper

    @field_validator("telegram_api_server")
    @classmethod
    def _validate_api_server(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v.strip() == "":
            return None
        return v

    @field_validator("mongodb_uri")
    @classmethod
    def _validate_mongodb_uri(cls, v: str) -> str:
        if not (v.startswith("mongodb://") or v.startswith("mongodb+srv://")):
            raise ValueError(
                "mongodb_uri must start with 'mongodb://' or 'mongodb+srv://'."
            )
        return v

    def ensure_directories(self) -> None:
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.thumbnail_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    @property
    def uses_local_api(self) -> bool:
        return self.telegram_api_server is not None

    @property
    def effective_upload_limit_mb(self) -> int:
        return 2000 if self.uses_local_api else 50

    @property
    def redacted_mongodb_uri(self) -> str:
        try:
            scheme, rest = self.mongodb_uri.split("://", 1)
            if "@" in rest:
                credentials, host_part = rest.split("@", 1)
                if ":" in credentials:
                    user, _ = credentials.split(":", 1)
                    return f"{scheme}://{user}:***@{host_part}"
            return self.mongodb_uri
        except ValueError:
            return self.mongodb_uri


settings = Settings()  # type: ignore[call-arg]
