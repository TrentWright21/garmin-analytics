"""Application configuration.

Two sources, cleanly separated:

* ``.env``       -> secrets (Garmin credentials, DB URL). Never committed.
* ``config.yaml``-> non-secret behavior (sync schedule, units, log level).

Everything is validated by pydantic at startup, so a typo in config fails
loudly at boot instead of silently at 3 a.m. during a sync job.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root = two levels up from this file (backend/app/config.py)
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_YAML = REPO_ROOT / "config" / "config.yaml"
DEFAULT_DATA_DIR = REPO_ROOT / "data"


class SyncConfig(BaseModel):
    """When and what the background sync collects."""

    hour: int = Field(default=6, ge=0, le=23, description="Local hour for daily sync")
    minute: int = Field(default=30, ge=0, le=59)
    backfill_days: int = Field(default=30, ge=1, description="Days fetched on first run")


class AppConfig(BaseModel):
    """Non-secret settings loaded from config/config.yaml."""

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = False  # True in Docker; pretty console output in dev
    timezone: str = "America/Chicago"
    units: Literal["imperial", "metric"] = "imperial"
    sync: SyncConfig = SyncConfig()

    @classmethod
    def from_yaml(cls, path: Path = DEFAULT_CONFIG_YAML) -> AppConfig:
        if not path.exists():
            return cls()  # sane defaults if the file is missing
        with path.open() as fh:
            raw = yaml.safe_load(fh) or {}
        return cls.model_validate(raw)


class Settings(BaseSettings):
    """Secrets and environment-specific values, loaded from env / .env."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        # utf-8-sig tolerates (and strips) a UTF-8 BOM if an editor or a
        # `Set-Content -Encoding utf8` write ever adds one; without this a BOM
        # gets glued onto the first key so GA_GARMIN_EMAIL silently goes unread.
        env_file_encoding="utf-8-sig",
        env_prefix="GA_",
        extra="ignore",
    )

    garmin_email: SecretStr | None = None
    garmin_password: SecretStr | None = None
    garmin_tokens_dir: Path = DEFAULT_DATA_DIR / "garmin_tokens"

    # Anthropic API key for the AI Coach (GA_ANTHROPIC_API_KEY). Optional:
    # without it the Coach endpoints report "not configured" and everything
    # else keeps working. SecretStr keeps it out of reprs and logs.
    anthropic_api_key: SecretStr | None = None

    database_url: str = f"sqlite:///{DEFAULT_DATA_DIR / 'garmin.db'}"

    environment: Literal["dev", "prod"] = "dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_app_config() -> AppConfig:
    return AppConfig.from_yaml()
