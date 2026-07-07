"""Briefing API (M9): the morning brief, event countdown, and Body Battery.

Composition layer only. It loads the normalized frames once and stitches
together the *existing* analytics (readiness v2, risk engine, fitness/form) with
the new M9 pieces (weather, heat advisory, training streak, recovery timer,
event countdown). No analytics are re-derived here — this is the same thin
loader-over-pure-functions pattern as ``performance.py``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query

from app.analytics import briefing as brief
from app.analytics import engine as ax
from app.analytics import fitness, readiness
from app.analytics.physiology import _f
from app.config import get_app_config
from app.db.engine import latest_raw, session_scope
from app.logging import get_logger
from app.normalize.body_battery import parse_body_battery

log = get_logger(__name__)
router = APIRouter(prefix="/api")

_KPH_TO_MPH = 0.621371


def _range(days: int) -> tuple[date, date]:
    end = date.today()
    return end - timedelta(days=days - 1), end


def _c_to_f(celsius: float | None) -> float | None:
    return None if celsius is None else round(celsius * 9 / 5 + 32, 1)


def _weather_out(row: dict[str, Any]) -> dict[str, Any]:
    """Serialize today's weather row into imperial units for the UI."""
    if not row:
        return {"available": False}
    wind_kph = _f(row.get("wind_kph"))
    return {
        "available": True,
        "location": get_app_config().location.name,
        "temp_high_f": _c_to_f(_f(row.get("temp_high_c"))),
        "temp_low_f": _c_to_f(_f(row.get("temp_low_c"))),
        "apparent_high_f": _c_to_f(_f(row.get("apparent_high_c"))),
        "humidity_pct": _f(row.get("humidity_pct")),
        "dew_point_f": _c_to_f(_f(row.get("dew_point_c"))),
        "wind_mph": round(wind_kph * _KPH_TO_MPH, 1) if wind_kph is not None else None,
    }


def _event_out(today: date) -> dict[str, Any]:
    event = get_app_config().event
    if event is None:
        return {"available": False}
    return brief.event_countdown(event.name, event.date, today, kind=event.kind)


@router.get("/event")
def event() -> dict[str, Any]:
    """Countdown to the configured goal event (empty when none is configured)."""
    return _event_out(date.today())


def build_briefing() -> dict[str, Any]:
    """Compose the daily brief. Shared by the route and the AI-coach tool.

    Every sub-section degrades to ``{"available": false}`` when its data is
    missing, so the brief never breaks on a fresh install.
    """
    today = date.today()
    now = datetime.now()

    daily = ax.load_daily(*_range(90))
    acts = ax.load_activities(*_range(365))
    load = ax.daily_training_load(acts)

    fit = fitness.fitness_summary(load)
    tsb = _f(fit.get("form_tsb")) if fit.get("available") else None

    weather_frame = ax.load_weather(today, today)
    weather_row = weather_frame.tail(1).to_dicts()[0] if not weather_frame.is_empty() else {}
    heat = brief.heat_advisory(
        _f(weather_row.get("dew_point_c")),
        _f(weather_row.get("apparent_high_c")),
        _f(weather_row.get("temp_high_c")),
    )

    return {
        "date": str(today),
        "readiness": readiness.daily_readiness(daily, load),
        "risk": readiness.risk_flags(daily, acts, load),
        "fitness": fit,
        "streak": brief.training_streak(acts, today),
        "recovery": brief.recovery_timer(acts, now, tsb),
        "weather": _weather_out(weather_row),
        "heat": heat,
        "event": _event_out(today),
    }


@router.get("/briefing")
def briefing() -> dict[str, Any]:
    """The daily brief the dashboard's morning-brief page renders in one shot."""
    return build_briefing()


@router.get("/metrics/body-battery")
def body_battery(days: int = Query(default=7, ge=1, le=90)) -> dict[str, Any]:
    """Intraday Body Battery charge/drain curve for the last ``days`` days.

    Reads the already-collected ``body_battery_events`` raw payloads — no Garmin
    call. Returns per-day charge/drain totals plus a flattened ``series`` for a
    single continuous chart.
    """
    start, end = _range(days)
    per_day: list[dict[str, Any]] = []
    series: list[dict[str, int]] = []
    with session_scope() as s:
        day = start
        while day <= end:
            payload = latest_raw(s, "body_battery_events", day)
            if payload:
                for entry in parse_body_battery(payload):
                    per_day.append({k: entry[k] for k in ("date", "charged", "drained")})
                    series.extend(entry["points"])
            day += timedelta(days=1)
    series.sort(key=lambda p: p["ts_ms"])
    return {"days": per_day, "series": series}
