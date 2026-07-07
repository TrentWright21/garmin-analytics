"""Briefing API (M9/M10): morning brief, countdown, Body Battery, watch feed.

Composition layer only. It loads the normalized frames once and stitches
together the *existing* analytics (readiness v2, risk engine, fitness/form) with
the new M9 pieces (weather, heat advisory, training streak, recovery timer,
event countdown). No analytics are re-derived here — this is the same thin
loader-over-pure-functions pattern as ``performance.py``.

M10 adds ``/api/watch/briefing`` — a tiny, flat projection of the same brief
sized for a Connect IQ watch's minimal memory.
"""

from __future__ import annotations

import secrets
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.analytics import briefing as brief
from app.analytics import engine as ax
from app.analytics import fitness, readiness
from app.analytics.physiology import _f
from app.config import get_app_config, get_settings
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


# -- watch feed (M10) --------------------------------------------------------


def _watch_action(
    readiness_out: dict[str, Any], recovery: dict[str, Any], heat: dict[str, Any]
) -> str:
    """One short imperative line for the glance — the 'what to do today'.

    Kept to a phrase (a watch has room for little text): recovery/readiness sets
    the base, and a hot dew point appends a heat warning.
    """
    band = readiness_out.get("band")
    if recovery.get("available") and not recovery.get("recovered"):
        base = "Recover - last session still settling"
    elif band == "red":
        base = "Prioritize recovery today"
    elif band == "green" and recovery.get("next_intensity") == "quality":
        base = "Fresh - good for quality"
    elif band == "green":
        base = "Green light - train as planned"
    elif band == "yellow":
        base = "Amber - keep it moderate"
    else:
        base = "Train by feel"
    if heat.get("available") and heat.get("severity") in ("high", "extreme"):
        base += "; heat high, run early + hydrate"
    return base


def build_watch_briefing() -> dict[str, Any]:
    """Flat, tiny projection of the daily brief for a Connect IQ watch.

    Only scalars (no nested objects/arrays) so the watch's minimal-memory JSON
    parser stays cheap. Reuses ``build_briefing`` — no analytics re-derived.
    """
    b = build_briefing()
    r, rec, heat, ev, risk, weather = (
        b["readiness"],
        b["recovery"],
        b["heat"],
        b["event"],
        b["risk"],
        b["weather"],
    )
    return {
        "date": b["date"],
        "readiness_score": r.get("score"),
        "readiness_band": r.get("band", "unknown"),
        "recovery_pct": rec.get("pct_recovered"),
        "next_intensity": rec.get("next_intensity"),
        "heat_severity": heat.get("severity", "none") if heat.get("available") else "none",
        "dew_point_f": heat.get("dew_point_f"),
        "temp_high_f": weather.get("temp_high_f") if weather.get("available") else None,
        "risk_band": risk.get("risk_band", "green"),
        "risk_flags": risk.get("flag_count", 0),
        "event_name": ev.get("name") if ev.get("available") else None,
        "event_days": ev.get("days_until") if ev.get("available") else None,
        "action": _watch_action(r, rec, heat),
    }


@router.get("/watch/briefing")
def watch_briefing(token: str | None = Query(default=None)) -> dict[str, Any]:
    """Compact briefing for the Connect IQ watch app.

    Guard is opt-in: if ``GA_WATCH_TOKEN`` is unset (the localhost/simulator
    default) the feed is open; if set (for a tunneled real watch) a matching
    ``?token=`` is required. Compared in constant time.
    """
    configured = get_settings().watch_token
    if configured is not None and not secrets.compare_digest(
        token or "", configured.get_secret_value()
    ):
        raise HTTPException(status_code=401, detail="invalid or missing watch token")
    return build_watch_briefing()
