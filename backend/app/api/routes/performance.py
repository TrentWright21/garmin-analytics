"""Performance API (M8): fitness model, readiness, risk, intensity, sessions.

Thin serialization layer over the pure analytics in ``app.analytics.*``. Loads
the normalized frames, estimates HR max once, and hands DataFrames to the pure
functions — the loaders here are the only DB access, keeping the analytics
testable in isolation.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.analytics import engine as ax
from app.analytics import fitness, readiness, session
from app.analytics.physiology import estimate_hr_max
from app.collectors.base import CollectorAuthError, CollectorError, CollectorRateLimitError
from app.collectors.garmin_connect import GarminConnectCollector
from app.config import get_app_config, get_settings
from app.db.engine import session_scope, store_raw
from app.db.models.core import RawApiData
from app.logging import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/api")


def _range(days: int) -> tuple[date, date]:
    end = date.today()
    return end - timedelta(days=days - 1), end


def _hr_max() -> float:
    """Best HR max: the configured athlete value, else a robust observed estimate."""
    configured = get_app_config().athlete.hr_max
    return estimate_hr_max(ax.load_activities(), ax.load_daily(), configured=configured)


@router.get("/analytics/fitness")
def fitness_pmc(days: int = Query(default=180, ge=28, le=3650)) -> dict[str, Any]:
    """Performance Management Chart: Fitness (CTL), Fatigue (ATL), Form (TSB)."""
    start, end = _range(days)
    load = ax.load_training_load(start, end)
    pmc = fitness.performance_management(load)
    return {
        "summary": fitness.fitness_summary(load),
        "series": pmc.select(
            [c for c in ("day", "load", "ctl", "atl", "tsb", "ramp_7d") if c in pmc.columns]
        ).to_dicts(),
    }


@router.get("/analytics/vo2max")
def vo2max() -> dict[str, Any]:
    """Smoothed VO2max, trend direction, and a confidence grade."""
    return fitness.vo2max_trend(ax.load_daily(*_range(365)))


@router.get("/analytics/intensity")
def intensity(days: int = Query(default=42, ge=7, le=3650)) -> dict[str, Any]:
    """Aerobic vs anaerobic distribution over the window (polarized-training view)."""
    start, end = _range(days)
    return fitness.intensity_distribution(ax.load_activities(start, end), _hr_max())


@router.get("/analytics/readiness-v2")
def readiness_v2() -> dict[str, Any]:
    """Composite Red/Yellow/Green readiness with ranked drivers."""
    start, end = _range(90)
    daily = ax.load_daily(start, end)
    load = ax.load_training_load(start, end)
    return readiness.daily_readiness(daily, load)


@router.get("/analytics/risk")
def risk() -> dict[str, Any]:
    """Overtraining / injury-risk flags with evidence and an overall band."""
    start, end = _range(90)
    daily = ax.load_daily(start, end)
    acts = ax.load_activities(start, end)
    load = ax.training_load_for(acts)
    return readiness.risk_flags(daily, acts, load)


@router.get("/sessions")
def sessions(days: int = Query(default=90, ge=1, le=3650)) -> list[dict[str, Any]]:
    """Per-session efficiency-factor list for the window (newest last)."""
    start, end = _range(days)
    return session.session_efficiency_series(ax.load_activities(start, end), _hr_max())


@router.get("/session/{activity_id}")
def session_detail(activity_id: int) -> dict[str, Any]:
    """Deep analysis of one workout: physiology, efficiency, baseline, decoupling."""
    activity = ax.load_activity(activity_id)
    if activity is None:
        raise HTTPException(status_code=404, detail="activity not found")
    history = ax.load_activities()
    splits = _load_splits(activity_id)
    return session.analyze_session(activity, history, _hr_max(), splits=splits)


@router.get("/session/{activity_id}/route")
def session_route(activity_id: int) -> dict[str, Any]:
    """GPS track for one activity, pace-colored. Fetched on demand, then cached.

    The first view of a given activity makes one Garmin ``details`` call and
    stores it in the append-only raw layer; every view after reads the cache
    (no Garmin call). Indoor activities with no GPS return ``{"has_gps": false}``.
    """
    activity = ax.load_activity(activity_id)
    if activity is None:
        raise HTTPException(status_code=404, detail="activity not found")

    payload = _load_activity_details(activity_id)
    if payload is None:
        try:
            payload = GarminConnectCollector(get_settings()).activity_details(activity_id)
        except CollectorRateLimitError as exc:
            raise HTTPException(
                status_code=502, detail="Garmin is rate-limiting right now; try again shortly."
            ) from exc
        except CollectorAuthError as exc:
            raise HTTPException(status_code=502, detail=f"Garmin login failed: {exc}") from exc
        except CollectorError as exc:
            raise HTTPException(status_code=502, detail=f"Could not reach Garmin: {exc}") from exc
        if isinstance(payload, dict) and payload:
            with session_scope() as s:
                store_raw(s, "activity_details", activity.get("day"), payload)

    return session.extract_route(payload if isinstance(payload, dict) else {})


def _load_activity_details(activity_id: int) -> dict[str, Any] | None:
    """Cached raw ``activity_details`` payload for THIS activity, or None.

    Scans stored detail payloads and matches on the activity id inside the JSON,
    so a payload is never attributed to the wrong workout.
    """
    with session_scope() as s:
        rows = (
            s.execute(
                select(RawApiData)
                .where(RawApiData.endpoint == "activity_details")
                .order_by(RawApiData.fetched_at.desc())
            )
            .scalars()
            .all()
        )
    for row in rows:
        try:
            payload = json.loads(row.payload_json)
        except (ValueError, TypeError):
            continue
        if isinstance(payload, dict) and _payload_activity_id(payload) == activity_id:
            return payload
    return None


def _payload_activity_id(payload: dict[str, Any]) -> int | None:
    """Activity id from a details payload (top-level or nested metadataDTO)."""
    for candidate in (
        payload.get("activityId"),
        (payload.get("metadataDTO") or {}).get("activityId"),
    ):
        if candidate is not None:
            try:
                return int(candidate)
            except (TypeError, ValueError):
                return None
    return None


def _load_splits(activity_id: int) -> list[dict[str, Any]] | None:
    """Best-effort per-lap splits for THIS activity from a cached detail payload.

    Returns None today (bulk sync stores summaries; the details payload has no
    ``laps``), but computes automatically if a payload with laps ever lands.
    """
    payload = _load_activity_details(activity_id)
    laps = payload.get("laps") or payload.get("splitSummaries") if payload else None
    if not isinstance(laps, list):
        return None
    out: list[dict[str, Any]] = []
    for lap in laps:
        if not isinstance(lap, dict):
            continue
        out.append(
            {
                "duration_s": lap.get("duration") or lap.get("elapsedDuration"),
                "distance_m": lap.get("distance"),
                "avg_hr": lap.get("averageHR") or lap.get("avgHR"),
            }
        )
    return out or None
    return None
