"""Application configuration.

Two sources, cleanly separated:

* ``.env``       -> secrets (Garmin credentials, DB URL). Never committed.
* ``config.yaml``-> non-secret behavior (sync schedule, units, log level).

Everything is validated by pydantic at startup, so a typo in config fails
loudly at boot instead of silently at 3 a.m. during a sync job.
"""

from __future__ import annotations

from datetime import date
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


class LocationConfig(BaseModel):
    """Home training location — used to fetch local weather (Open-Meteo).

    Defaults to Hartselle, AL. Weather needs a lat/lon; the name is only for
    display. Change these to move the weather feed to a different town.
    """

    name: str = "Hartselle, AL"
    latitude: float = Field(default=34.4426, ge=-90.0, le=90.0)
    longitude: float = Field(default=-86.9353, ge=-180.0, le=180.0)


class EventConfig(BaseModel):
    """A goal event to count down to. Deliberately generic — a summit hike, a
    marathon, a 5K, or anything with a date all fit.

    Only ``name`` and ``date`` are required. ``distance_m`` / ``goal_time`` are
    for actual races (they feed the pace planner); a climb leaves them null.
    """

    name: str
    date: date
    kind: Literal["race", "climb", "hike", "other"] = "other"
    distance_m: float | None = None
    goal_time: str | None = None  # "3:30:00" for a race target; null for a climb


class AppConfig(BaseModel):
    """Non-secret settings loaded from config/config.yaml."""

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = False  # True in Docker; pretty console output in dev
    timezone: str = "America/Chicago"
    units: Literal["imperial", "metric"] = "imperial"
    sync: SyncConfig = SyncConfig()
    location: LocationConfig = LocationConfig()
    # Optional: the athlete's next goal event. Absent -> no countdown surfaces.
    event: EventConfig | None = None

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

    # Shared secret for the watch feed (GA_WATCH_TOKEN). Optional, unset by
    # default: on localhost (the simulator) the feed needs no guard. Set it ONLY
    # if you expose the backend through a tunnel for a real watch, so the public
    # endpoint isn't wide open. When set, /api/watch/* requires a matching ?token=.
    watch_token: SecretStr | None = None

    database_url: str = f"sqlite:///{DEFAULT_DATA_DIR / 'garmin.db'}"

    environment: Literal["dev", "prod"] = "dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_app_config() -> AppConfig:
    return AppConfig.from_yaml()
