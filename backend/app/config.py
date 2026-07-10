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


class NotifyConfig(BaseModel):
    """Automated morning-message push (M9+ notifier).

    Off by default. When ``enabled`` and the channel's secrets are set (e.g.
    ``GA_TELEGRAM_BOT_TOKEN`` / ``GA_TELEGRAM_CHAT_ID``), a scheduled job sends
    the daily brief to your phone. ``ai_polish`` optionally rewrites the brief
    with Claude (costs one Anthropic call per morning; needs GA_ANTHROPIC_API_KEY).
    """

    enabled: bool = False
    hour: int = Field(default=6, ge=0, le=23, description="Local hour for the morning push")
    minute: int = Field(default=35, ge=0, le=59)
    ai_polish: bool = False


class GoalConfig(BaseModel):
    """The athlete's active training goal — shapes the morning workout rec.

    Deliberately not hardcoded: ``focus`` is a free label the coach reasons over
    (e.g. ``marathon``, ``half_marathon``, ``15k``, ``10k``, ``5k``,
    ``weight_loss``, ``general_fitness``, ``recovery``, ``strength``,
    ``endurance``, ``climb``). ``note`` is optional free text for extra context
    (a target date, a niggle to respect, "build aerobic base", etc.). Change
    these in ``config.yaml`` whenever the goal changes.
    """

    focus: str = "general_fitness"
    note: str | None = None


class LocationConfig(BaseModel):
    """Home training location — used to fetch local weather (Open-Meteo).

    Defaults to Hartselle, AL. Weather needs a lat/lon; the name is only for
    display. Change these to move the weather feed to a different town.
    """

    name: str = "Hartselle, AL"
    latitude: float = Field(default=34.4426, ge=-90.0, le=90.0)
    longitude: float = Field(default=-86.9353, ge=-180.0, le=180.0)


class AthleteConfig(BaseModel):
    """Physiological constants that sharpen HR-based analytics.

    Both optional. ``hr_max`` from a real max-effort test beats any estimate
    (otherwise the 99.5th percentile of observed maxes is used); ``hr_rest`` is
    a true resting HR for TRIMP's heart-rate-reserve math (otherwise a
    conservative population default applies to the rare sessions Garmin didn't
    attach a training load to).
    """

    hr_max: int | None = Field(default=None, ge=120, le=230)
    hr_rest: int | None = Field(default=None, ge=25, le=100)


class AiInsightConfig(BaseModel):
    """Tier-2/3 AI metric insights (redesign). **OFF by default** — the local
    Tier-1 engine always works without it. Only when ``enabled`` AND a
    ``GA_ANTHROPIC_API_KEY`` is set can the metric-detail view produce a cached,
    cost-capped natural-language summary, and only on an explicit button press.

    Every knob here is a cost control: a cheap model, a hard daily call cap, a
    reuse cache, a strict output-token ceiling, and a minimum-history gate.
    """

    enabled: bool = False
    model: str = "claude-haiku-4-5-20251001"  # cheap by design; not Opus
    max_output_tokens: int = Field(default=320, ge=64, le=1024)
    cache_hours: int = Field(default=18, ge=1, le=168)  # reuse before regenerating
    max_calls_per_day: int = Field(default=25, ge=0)  # hard ceiling; 0 disables
    min_days: int = Field(default=14, ge=1)  # refuse thin history


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
    vert_gain_ft: float | None = None  # summit-day elevation gain; anchors the
    # goal plan's weekly vert targets (e.g. Mount Whitney's ~6,100 ft day hike)


class AppConfig(BaseModel):
    """Non-secret settings loaded from config/config.yaml."""

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = False  # True in Docker; pretty console output in dev
    timezone: str = "America/Chicago"
    units: Literal["imperial", "metric"] = "imperial"
    sync: SyncConfig = SyncConfig()
    location: LocationConfig = LocationConfig()
    notify: NotifyConfig = NotifyConfig()
    goal: GoalConfig = GoalConfig()
    athlete: AthleteConfig = AthleteConfig()
    ai_insights: AiInsightConfig = AiInsightConfig()
    # Extra browser origins allowed to call the API cross-origin (prod). Empty is
    # the safe default for a same-origin deploy (dashboard served by FastAPI). The
    # Vite dev server origin is always allowed in dev; see main.py.
    cors_origins: list[str] = []
    # Hostnames the server answers to (TrustedHostMiddleware). Empty = allow any
    # (correct for Tailscale, where the tailnet name varies). Set to lock it down.
    allowed_hosts: list[str] = []
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

    # App login password (GA_APP_PASSWORD). When set, every /api/* endpoint (except
    # login and the separately-guarded watch feed) requires a session token minted
    # by POST /api/login. Unset = auth OFF (safe only on a trusted localhost). In
    # prod the app refuses to start without it (fail-closed; see main.py lifespan).
    # No separate signing key is needed: session tokens are HMAC-signed with a key
    # derived from this password, so rotating the password invalidates old sessions.
    app_password: SecretStr | None = None

    # Telegram morning-message channel (GA_TELEGRAM_BOT_TOKEN / GA_TELEGRAM_CHAT_ID).
    # Both must be set for the notifier to send; otherwise it reports "not configured".
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None

    database_url: str = f"sqlite:///{DEFAULT_DATA_DIR / 'garmin.db'}"

    environment: Literal["dev", "prod"] = "dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_app_config() -> AppConfig:
    return AppConfig.from_yaml()
