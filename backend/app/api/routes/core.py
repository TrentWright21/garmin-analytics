"""REST API (M6). The React dashboard consumes these in M7."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.analytics import engine as ax
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
    load = ax.daily_training_load(ax.load_activities(start, end))
    return {
        "acwr": ax.acwr(load).to_dicts(),
        "monotony": ax.monotony(load).to_dicts(),
    }


@router.get("/analytics/readiness")
def readiness() -> dict[str, Any]:
    start, end = _range(90)
    return ax.readiness_score(ax.load_daily(start, end))


@router.get("/insights")
def insights(days: int = Query(default=365, ge=30, le=3650)) -> dict[str, list[str]]:
    start, end = _range(days)
    daily = ax.load_daily(start, end)
    acts = ax.load_activities(start, end)
    return {"insights": ax.generate_insights(daily, acts)}


@router.post("/sync", dependencies=[Depends(rate_limiter(_sync_limiter))])
def trigger_sync(
    background: BackgroundTasks, days: int = Query(default=2, ge=1, le=365)
) -> dict[str, str]:
    """Kick a sync without blocking the request (the dashboard 'Sync now' button)."""

    def run() -> None:
        build_sync_engine(GarminConnectCollector(get_settings())).sync_recent(days=days)

    background.add_task(run)
    return {"status": "sync started", "days": str(days)}
