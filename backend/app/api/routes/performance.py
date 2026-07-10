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
from app.analytics import fitness, goal_plan, insight_engine, readiness, session
from app.analytics.physiology import estimate_hr_max
from app.collectors.base import CollectorAuthError, CollectorError, CollectorRateLimitError
from app.collectors.garmin_connect import GarminConnectCollector
from app.config import get_app_config, get_settings
from app.db.engine import latest_raw_any, session_scope, store_raw
from app.db.models.core import RawApiData
from app.logging import get_logger
from app.normalize.personal_records import parse_personal_records

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


@router.get("/analytics/training-summary")
def training_summary(weeks: int = Query(default=12, ge=4, le=52)) -> dict[str, Any]:
    """Weekly volume + zone-time bars, plus Garmin's Load Focus / status verdicts.

    Backs the Training page: Monday-anchored weekly miles / vert / hours / zone
    minutes from the activities, and Garmin's own Load Focus targets as a
    labeled cross-check beside our load model.
    """
    start, end = _range(weeks * 7)
    acts = ax.load_activities(start, end)
    # Load Focus / training status refresh daily; a recent month is plenty.
    daily = ax.load_daily(*_range(35))
    return {
        "weeks": ax.weekly_volume(acts).to_dicts(),
        "garmin": fitness.garmin_load_focus(daily),
    }


@router.get("/analytics/race-predictions")
def race_predictions(days: int = Query(default=365, ge=28, le=3650)) -> dict[str, Any]:
    """Garmin's daily race-time predictions: latest, ~30-day deltas, full series.

    Collected daily since Phase 1b; the Progress page charts the trend. Negative
    delta = the predicted time got faster.
    """
    start, end = _range(days)
    return fitness.race_prediction_trend(ax.load_race_predictions(start, end))


@router.get("/personal-records")
def personal_records() -> dict[str, Any]:
    """Garmin personal records, parsed from the latest stored snapshot.

    No Garmin call — the daily sync already snapshots these; unknown record
    types are omitted rather than mislabeled.
    """
    with session_scope() as s:
        payload = latest_raw_any(s, "personal_records")
    return {"records": parse_personal_records(payload)}


@router.get("/analytics/readiness-v2")
def readiness_v2() -> dict[str, Any]:
    """Composite Red/Yellow/Green readiness with ranked drivers."""
    start, end = _range(90)
    daily = ax.load_daily(start, end)
    load = ax.load_training_load(start, end)
    return readiness.daily_readiness(daily, load, today=end)


@router.get("/metric/{key}/detail")
def metric_detail(key: str, days: int = Query(default=90, ge=7, le=1825)) -> dict[str, Any]:
    """Local (Tier-1, no-AI) detail for one metric: value, status, change, range
    stats, the series, deterministic insights, and measured relationships.

    Loads enough history for a stable 30-day baseline even on short display
    ranges. Returns ``{"available": false}`` for unknown metrics or empty data.
    """
    end = date.today()
    daily = ax.load_daily(end - timedelta(days=max(days, 60) - 1), end)
    return insight_engine.metric_detail(daily, key, days=days)


@router.get("/metric/{key}/ai-insight")
def metric_ai_insight_get(key: str, days: int = Query(default=90, ge=7, le=1825)) -> dict[str, Any]:
    """Read a cached AI insight for this metric (never generates — no spend).

    On a page load the detail view calls this to show an existing summary and to
    learn whether the "Generate deeper analysis" button should be offered.
    """
    from app.ai import metric_insight

    end = date.today()
    daily = ax.load_daily(end - timedelta(days=max(days, 60) - 1), end)
    detail = insight_engine.metric_detail(daily, key, days=days)
    cfg = get_app_config().ai_insights
    return metric_insight.ai_insight(get_settings(), cfg, detail, generate=False)


@router.post("/metric/{key}/ai-insight")
def metric_ai_insight_post(
    key: str, days: int = Query(default=90, ge=7, le=1825)
) -> dict[str, Any]:
    """Explicit user request for a deeper AI summary (the button).

    The only path that may call the model, and only when enabled + under the
    daily cap + enough history; otherwise returns a reason and the UI keeps the
    free local insights.
    """
    from app.ai import metric_insight

    end = date.today()
    daily = ax.load_daily(end - timedelta(days=max(days, 60) - 1), end)
    detail = insight_engine.metric_detail(daily, key, days=days)
    cfg = get_app_config().ai_insights
    return metric_insight.ai_insight(get_settings(), cfg, detail, generate=True)


@router.get("/goal-plan")
def goal_plan_route() -> dict[str, Any]:
    """Event-anchored weekly plan (miles + vert + long effort) vs actual volume.

    Reads the configured goal event; returns ``{"available": false}`` when none
    is set. The plan window looks back far enough to overlay the athlete's real
    weekly volume for adherence.
    """
    event = get_app_config().event
    if event is None:
        return {"available": False}
    end = date.today()
    # A 16-week plan spans ~112 days; 200 covers it plus the baseline weeks.
    acts = ax.load_activities(end - timedelta(days=200), end)
    weekly = ax.weekly_volume(acts).to_dicts()
    return goal_plan.goal_plan(
        event_name=event.name,
        event_date=event.date,
        event_kind=event.kind,
        today=end,
        weekly_actual=weekly,
        event_vert_gain_ft=event.vert_gain_ft,
    )


@router.get("/analytics/readiness-history")
def readiness_history(days: int = Query(default=30, ge=7, le=120)) -> dict[str, Any]:
    """Band-colored readiness history: the headline score, replayed day by day."""
    # Load extra history beyond the window so the earliest charted days still
    # have their 60-day baselines behind them.
    start, end = _range(days + 90)
    daily = ax.load_daily(start, end)
    load = ax.load_training_load(start, end)
    return readiness.readiness_history(daily, load, days=days, today=end)


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
