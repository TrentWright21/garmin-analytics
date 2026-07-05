"""Coach API (M7): sleep coach, pace/goal coach, and per-metric insights.

These endpoints back the dashboard's coaching pages. The analytics themselves
live in ``app.analytics.*`` as pure functions; this layer just loads data
(including a couple of raw snapshot payloads for fitness context) and serializes.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import polars as pl
from fastapi import APIRouter, Query
from sqlalchemy import select

from app.analytics import engine as ax
from app.analytics import metric_insights, pace_coach, sleep_coach
from app.db.engine import session_scope
from app.db.models.core import RawApiData
from app.logging import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/api/coach")


# -- helpers -----------------------------------------------------------------


def _latest_snapshot(endpoint: str) -> Any | None:
    """Most recently fetched payload for a snapshot endpoint (ignores date)."""
    import json

    with session_scope() as s:
        row = s.execute(
            select(RawApiData)
            .where(RawApiData.endpoint == endpoint)
            .order_by(RawApiData.fetched_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        return json.loads(row.payload_json) if row else None


def _weekly_running_miles(days: int = 28) -> float:
    end = date.today()
    acts = ax.load_activities(end - timedelta(days=days - 1), end)
    if acts.is_empty() or "activity_type" not in acts.columns:
        return 0.0
    runs = acts.filter(pl.col("activity_type").str.contains("running").fill_null(False))
    if runs.is_empty():
        return 0.0
    total_m = runs["distance_m"].fill_null(0).sum()
    return round(float(total_m) / pace_coach.M_PER_MILE / (days / 7), 1)


def _acclimation() -> dict[str, float | None]:
    ts = _latest_snapshot("training_status")
    out: dict[str, float | None] = {"heat_pct": None, "altitude_pct": None}
    if isinstance(ts, dict):
        acc = (ts.get("mostRecentVO2Max") or {}).get("heatAltitudeAcclimation") or {}
        out["heat_pct"] = acc.get("heatAcclimationPercentage")
        out["altitude_pct"] = acc.get("altitudeAcclimation")
    return out


def _current_fitness() -> dict[str, Any]:
    """Derive current VDOT and Garmin race predictions from raw snapshots."""
    preds = _latest_snapshot("race_predictions") or {}
    garmin_predictions: dict[str, Any] = {}
    current_vdot = 0.0
    key_map = {
        "5K": ("time5K", 5000.0),
        "10K": ("time10K", 10000.0),
        "Half Marathon": ("timeHalfMarathon", 21097.5),
        "Marathon": ("timeMarathon", 42195.0),
    }
    for name, (field, dist) in key_map.items():
        secs = preds.get(field) if isinstance(preds, dict) else None
        if secs:
            garmin_predictions[name] = {
                "seconds": int(secs),
                "time": pace_coach.fmt_time(float(secs)),
                "vdot": pace_coach.vdot_from_performance(dist, float(secs)),
            }
    # Anchor current fitness on the 5K prediction (most sensitive), else 10K.
    for name in ("5K", "10K", "Half Marathon"):
        if name in garmin_predictions:
            current_vdot = garmin_predictions[name]["vdot"]
            break

    # VO2max as an independent "potential" reference.
    daily = ax.load_daily(date.today() - timedelta(days=30), date.today())
    vo2 = None
    if not daily.is_empty() and "vo2max_running" in daily.columns:
        s = daily["vo2max_running"].drop_nulls()
        vo2 = float(s[-1]) if s.len() else None

    return {
        "current_vdot": current_vdot or (vo2 or 40.0),
        "vo2max": vo2,
        "garmin_predictions": garmin_predictions,
        "weekly_miles": _weekly_running_miles(),
        "acclimation": _acclimation(),
    }


# -- routes ------------------------------------------------------------------


@router.get("/sleep")
def sleep(days: int = Query(default=120, ge=7, le=3650)) -> dict[str, Any]:
    """Full sleep-coach report: personal need, regularity, stages, debt, plan."""
    end = date.today()
    daily = ax.load_daily(end - timedelta(days=days - 1), end)
    return sleep_coach.coach_report(daily)


@router.get("/metrics")
def metrics(days: int = Query(default=90, ge=7, le=3650)) -> dict[str, Any]:
    """An analytical card for every tracked metric."""
    end = date.today()
    daily = ax.load_daily(end - timedelta(days=days - 1), end)
    return {"cards": metric_insights.metric_cards(daily)}


@router.get("/fitness")
def fitness() -> dict[str, Any]:
    """Current running fitness: VDOT, race predictions, paces, heat & altitude."""
    ctx = _current_fitness()
    vdot = float(ctx["current_vdot"])
    paces = pace_coach.training_paces(vdot)
    threshold_mi = paces.get("threshold", {}).get("sec_per_mile")
    predictions = {
        name: {"time": pace_coach.fmt_time(pace_coach.predict_time(vdot, dist)), "distance_m": dist}
        for name, dist in pace_coach.RACES.items()
    }
    return {
        "current_vdot": vdot,
        "vo2max": ctx["vo2max"],
        "weekly_miles": ctx["weekly_miles"],
        "garmin_predictions": ctx["garmin_predictions"],
        "model_predictions": predictions,
        "paces": paces,
        "heat_table": pace_coach.heat_table(float(threshold_mi)) if threshold_mi else [],
        "altitude_note": pace_coach.altitude_note(ctx["acclimation"]["altitude_pct"]),
        "heat_acclimation_pct": ctx["acclimation"]["heat_pct"],
    }


@router.get("/pace")
def pace(
    race: str = Query(default="Half Marathon"),
    goal_seconds: int | None = Query(default=None, ge=60, le=60 * 60 * 8),
    weeks: int = Query(default=12, ge=4, le=30),
    weekly_miles: float | None = Query(default=None, ge=0, le=200),
) -> dict[str, Any]:
    """Build a goal + week-by-week plan to reach a target race time."""
    ctx = _current_fitness()
    distance_m = pace_coach.RACES.get(race, pace_coach.RACES["Half Marathon"])
    miles = weekly_miles if weekly_miles is not None else ctx["weekly_miles"]
    plan = pace_coach.build_plan(
        current_vdot=float(ctx["current_vdot"]),
        goal_distance_m=distance_m,
        goal_time_s=float(goal_seconds) if goal_seconds else None,
        weeks=weeks,
        current_weekly_miles=float(miles),
        goal_key=race,
    )
    plan["race"] = race
    plan["distance_m"] = distance_m
    plan["current_paces"] = pace_coach.training_paces(float(ctx["current_vdot"]))
    plan["races_available"] = list(pace_coach.RACES.keys())
    plan["heat_note"] = (
        "Race-day heat matters: your goal paces assume ~60°F. See the heat table on the "
        "Fitness view for realistic Hartselle-summer adjustments."
    )
    return plan
