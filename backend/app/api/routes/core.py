"""REST API (M6). The React dashboard consumes these in M7."""

from __future__ import annotations

import threading
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.analytics import engine as ax
from app.collectors.base import CollectorAuthError, CollectorRateLimitError
from app.collectors.garmin_connect import GarminConnectCollector
from app.collectors.sync import build_sync_engine
from app.config import get_settings
from app.logging import get_logger
from app.ratelimit import RateLimiter, rate_limiter

log = get_logger(__name__)
router = APIRouter(prefix="/api")

# Protect the Garmin account: cap manual syncs so a stuck client or reload loop
# can't hammer Garmin into a 429 lockout. 5/min is far more than a human needs.
_sync_limiter = RateLimiter(max_calls=5, window_s=60.0)


def _range(days: int) -> tuple[date, date]:
    end = date.today()
    return end - timedelta(days=days - 1), end


@router.get("/metrics/daily")
def daily_metrics(days: int = Query(default=90, ge=1, le=3650)) -> list[dict[str, Any]]:
    start, end = _range(days)
    return ax.load_daily(start, end).to_dicts()


@router.get("/activities")
def activities(days: int = Query(default=90, ge=1, le=3650)) -> list[dict[str, Any]]:
    start, end = _range(days)
    return ax.load_activities(start, end).to_dicts()


@router.get("/analytics/trends")
def trends(days: int = Query(default=180, ge=14, le=3650)) -> list[dict[str, Any]]:
    start, end = _range(days)
    return ax.rolling_trends(ax.load_daily(start, end)).to_dicts()


@router.get("/analytics/weekly")
def weekly(days: int = Query(default=365, ge=14, le=3650)) -> list[dict[str, Any]]:
    start, end = _range(days)
    return ax.period_summary(ax.load_daily(start, end), every="1w").to_dicts()


@router.get("/analytics/training-load")
def training_load(days: int = Query(default=180, ge=28, le=3650)) -> dict[str, Any]:
    start, end = _range(days)
    load = ax.load_training_load(start, end)
    # monotony is a trailing-7d daily series; the chart wants weekly bars, so
    # sample one row every 7 days, anchored to the most recent day.
    mono = ax.monotony(load)
    if not mono.is_empty():
        mono = mono.reverse().gather_every(7).reverse()
    return {
        "acwr": ax.acwr(load).to_dicts(),
        "monotony": mono.to_dicts(),
    }


@router.get("/insights")
def insights(days: int = Query(default=365, ge=30, le=3650)) -> dict[str, list[str]]:
    start, end = _range(days)
    daily = ax.load_daily(start, end)
    acts = ax.load_activities(start, end)
    return {"insights": ax.generate_insights(daily, acts)}


# -- manual sync + its status -------------------------------------------------
# The POST returns immediately (a sync takes a minute or more; holding the
# request open would trip mobile/browser timeouts), so this tiny in-process
# tracker is how the dashboard learns when the background work actually
# finished. One dict + lock — deliberately not a job queue. It tracks the
# MANUAL button only; the 06:30 scheduler job doesn't pass through here.
_sync_status_lock = threading.Lock()
_sync_status: dict[str, Any] = {
    "state": "idle",  # idle | running | complete | error
    "started_at": None,
    "finished_at": None,
    "error": None,
    "stats": None,
}


def _set_sync_status(**updates: Any) -> None:
    with _sync_status_lock:
        _sync_status.update(updates)


def _friendly_sync_error(exc: Exception) -> str:
    """User-facing failure text. Never the raw exception — no tracebacks,
    no credentials, no Garmin response bodies."""
    if isinstance(exc, CollectorAuthError):
        return "Garmin login failed - check the credentials on the server."
    if isinstance(exc, CollectorRateLimitError):
        return "Garmin rate-limited the sync - wait a while and try again."
    return "Sync failed - check the server logs for details."


@router.post("/sync", dependencies=[Depends(rate_limiter(_sync_limiter))])
def trigger_sync(
    background: BackgroundTasks, days: int = Query(default=2, ge=1, le=365)
) -> dict[str, str]:
    """Kick a sync without blocking the request (the dashboard 'Sync now' button).

    Poll ``GET /api/sync/status`` to learn when it actually completed; a second
    POST while one is running is a no-op (the client just keeps polling).
    """
    with _sync_status_lock:
        if _sync_status["state"] == "running":
            return {"status": "already running", "days": str(days)}
        _sync_status.update(
            {
                "state": "running",
                "started_at": datetime.now(UTC).isoformat(),
                "finished_at": None,
                "error": None,
                "stats": None,
            }
        )

    def run() -> None:
        try:
            stats = build_sync_engine(GarminConnectCollector(get_settings())).sync_recent(days=days)
            _set_sync_status(
                state="complete", finished_at=datetime.now(UTC).isoformat(), stats=stats
            )
        except Exception as exc:
            log.warning("sync.manual_failed", err=type(exc).__name__)
            _set_sync_status(
                state="error",
                finished_at=datetime.now(UTC).isoformat(),
                error=_friendly_sync_error(exc),
            )

    background.add_task(run)
    return {"status": "sync started", "days": str(days)}


@router.get("/sync/status")
def sync_status() -> dict[str, Any]:
    """Where the manual sync stands: idle | running | complete | error."""
    with _sync_status_lock:
        return dict(_sync_status)
