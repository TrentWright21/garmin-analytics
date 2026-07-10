"""Morning-briefing analytics (M9).

Small, transparent, pure functions that turn the normalized frames into the
pieces of a daily brief. Everything here is a documented heuristic traceable to
real data — no invented scores:

* ``training_streak`` — consecutive active days + recent consistency.
* ``recovery_timer`` — how long since the last session and, from its training
  load, an estimate of when the athlete is recovered (with the reasoning shown).
* ``heat_advisory`` — dew-point-based heat-stress guidance for running, which
  Garmin does not offer and which matters a great deal in a hot, humid summer.
* ``event_countdown`` — days/weeks to the configured goal event.

The route layer loads the frames and composes these into ``/api/briefing``; the
functions themselves take frames/scalars so they stay unit-testable.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from itertools import pairwise
from typing import Any

import polars as pl

from app.analytics.physiology import _f

# -- training streak & consistency -------------------------------------------


def training_streak(activities: pl.DataFrame, today: date) -> dict[str, Any]:
    """Consecutive-active-day streak plus 7/28-day consistency counts.

    A "training day" is any day with at least one recorded activity. The current
    streak counts back from the most recent active day; if that day is today or
    yesterday the streak is considered live, otherwise it has lapsed.
    """
    if activities.is_empty() or "day" not in activities.columns:
        return {"available": False}
    days = sorted({d for d in activities["day"].to_list() if d is not None})
    if not days:
        return {"available": False}

    # Longest run of consecutive calendar days anywhere in the history.
    longest = run = 1
    for prev, cur in pairwise(days):
        run = run + 1 if cur - prev == timedelta(days=1) else 1
        longest = max(longest, run)

    # Current streak: walk backwards from the most recent active day.
    last_active = days[-1]
    active_set = set(days)
    current = 0
    cursor = last_active
    while cursor in active_set:
        current += 1
        cursor -= timedelta(days=1)

    days_since_last = (today - last_active).days
    live = days_since_last <= 1  # today or yesterday keeps the streak alive

    window_7 = today - timedelta(days=6)
    window_28 = today - timedelta(days=27)
    return {
        "available": True,
        "current_streak": current if live else 0,
        "longest_streak": longest,
        "last_active": str(last_active),
        "days_since_last": days_since_last,
        "active_last_7": sum(1 for d in days if d >= window_7),
        "active_last_28": sum(1 for d in days if d >= window_28),
    }


# -- recovery timer -----------------------------------------------------------

# Rough recovery windows by session training load. These are deliberately simple
# and documented (not a black box): heavier sessions need longer before the next
# hard effort. Load here is Garmin's per-activity training load, or an HR-minutes
# proxy when Garmin didn't compute one.
_RECOVERY_HOURS = [
    (40.0, 12),  # short/easy
    (80.0, 24),
    (150.0, 36),
    (250.0, 48),
]
_RECOVERY_HOURS_MAX = 60  # very hard / long


def _session_load(session: dict[str, Any]) -> float | None:
    """Garmin training load, or an HR-minutes proxy, for one session."""
    load = _f(session.get("training_load"))
    if load is not None and load > 0:
        return load
    dur = _f(session.get("duration_s"))
    hr = _f(session.get("avg_hr"))
    if dur is not None and hr is not None:
        return (dur / 60.0) * (hr / 100.0)
    return None


def _recovery_hours_for(load: float | None) -> int:
    if load is None:
        return 24  # unknown load: assume a moderate day
    for threshold, hours in _RECOVERY_HOURS:
        if load < threshold:
            return hours
    return _RECOVERY_HOURS_MAX


def recovery_timer(
    activities: pl.DataFrame,
    now: datetime,
    tsb: float | None = None,
    garmin_recovery_min: float | None = None,
) -> dict[str, Any]:
    """Time since the last session and an estimate of hours until recovered.

    ``garmin_recovery_min`` — Garmin's native recovery timer from this morning's
    ``training_readiness`` payload — is the primary number when available (the
    watch computes it from far more signal than our load table); the documented
    per-session-load heuristic is the fallback. The value is "minutes remaining
    as of the morning sync", so it can slightly overstate later in the day.

    ``tsb`` (Form, from ``fitness.fitness_summary``) refines the recommendation:
    deeply negative form means keep it easy even once the per-session timer says
    you're clear.
    """
    if activities.is_empty() or "start_time_local" not in activities.columns:
        return {"available": False}
    sessions = activities.drop_nulls(subset=["start_time_local"]).sort("start_time_local")
    if sessions.is_empty():
        return {"available": False}

    last = sessions.tail(1).to_dicts()[0]
    start = last.get("start_time_local")
    if not isinstance(start, datetime):
        return {"available": False}

    hours_since = round((now - start).total_seconds() / 3600.0, 1)
    if garmin_recovery_min is not None and garmin_recovery_min >= 0:
        source = "garmin"
        remaining_h = garmin_recovery_min / 60.0
        need = round(hours_since + remaining_h, 1)
        recovered = remaining_h <= 0
        pct = 100 if recovered or need <= 0 else min(100, round(hours_since / need * 100))
    else:
        source = "heuristic"
        need = float(_recovery_hours_for(_session_load(last)))
        pct = min(100, round(hours_since / need * 100)) if need else 100
        recovered = hours_since >= need

    if not recovered:
        remaining = round(need - hours_since, 1)
        timer_label = "Garmin's recovery timer says" if source == "garmin" else "About"
        recommendation = (
            f"{timer_label} {remaining:.0f} h until you're recovered from your last "
            "session. Keep today easy or take it as rest."
        )
        next_intensity = "easy"
    elif tsb is not None and tsb < -25:
        recommendation = (
            "The per-session timer says you're clear, but your Form (TSB) is deeply "
            "negative — favour an easy day until fatigue clears."
        )
        next_intensity = "easy"
    elif tsb is not None and tsb > 5:
        recommendation = "Recovered and fresh — a good window for quality or a long effort."
        next_intensity = "quality"
    else:
        recommendation = "Recovered from your last session — moderate training is fine."
        next_intensity = "moderate"

    return {
        "available": True,
        "last_activity_at": start.isoformat(),
        "last_activity_name": last.get("name"),
        "hours_since": hours_since,
        "estimated_recovery_hours": need,
        "pct_recovered": pct,
        "recovered": recovered,
        "source": source,
        "next_intensity": next_intensity,
        "recommendation": recommendation,
    }


# -- heat advisory ------------------------------------------------------------


def _c_to_f(celsius: float | None) -> float | None:
    return None if celsius is None else round(celsius * 9 / 5 + 32, 1)


# Dew-point-in-Fahrenheit running-comfort scale. This is the widely-used
# runner's dew-point guideline (comfort degrades sharply above ~60F because
# sweat evaporates less, so the body sheds heat poorly). Ordered high-to-low; the
# first threshold the dew point meets or exceeds wins.
_DEW_SCALE = [
    (
        75.0,
        "extreme",
        "Dangerous mugginess. Consider moving indoors or cutting the run short; "
        "hydrate heavily and drop the pace well back.",
    ),
    (
        70.0,
        "high",
        "Oppressive. Expect noticeably slower paces, run by effort not pace, and carry water.",
    ),
    (
        65.0,
        "moderate",
        "Uncomfortable and getting hard. Ease your pace and hydrate; "
        "shift the run earlier if you can.",
    ),
    (60.0, "low", "Sticky. You'll feel it on harder efforts — build in a little pace grace."),
    (55.0, "minimal", "Slightly humid but manageable for most sessions."),
]


def heat_advisory(
    dew_point_c: float | None,
    apparent_high_c: float | None,
    temp_high_c: float | None,
) -> dict[str, Any]:
    """Heat-stress guidance for a run, driven by dew point (the humidity signal).

    Dew point, not raw temperature, governs how hard it is to cool off, so it is
    the primary input; apparent ("feels-like") high is reported alongside.
    """
    dew_f = _c_to_f(dew_point_c)
    if dew_f is None:
        return {"available": False}

    severity, advice = "none", "Comfortable conditions for running."
    for threshold, sev, text in _DEW_SCALE:
        if dew_f >= threshold:
            severity, advice = sev, text
            break

    return {
        "available": True,
        "severity": severity,
        "dew_point_f": dew_f,
        "apparent_high_f": _c_to_f(apparent_high_c),
        "temp_high_f": _c_to_f(temp_high_c),
        "advice": advice,
    }


# -- best run window ------------------------------------------------------------

# Candidate start hours for a run (local). Blocks must fit inside this span —
# nobody is being sent out at 2am for marginally better dew point.
_RUN_EARLIEST_H = 5
_RUN_LATEST_H = 21


def _hour_label(hour: int) -> str:
    if hour == 0:
        return "12 AM"
    if hour < 12:
        return f"{hour} AM"
    if hour == 12:
        return "12 PM"
    return f"{hour - 12} PM"


def best_run_window(
    forecast: dict[str, Any] | None, day: date, block_hours: int = 2
) -> dict[str, Any]:
    """The coolest ``block_hours`` window for a run on ``day``. Pure.

    Scores each forecast hour with the runner's comfort sum — temperature °F +
    dew point °F (the classic pace-adjustment index; dew point is the real
    heat-stress signal) — and returns the daytime block (05:00-21:00) with the
    lowest average. ``forecast`` is the verbatim Open-Meteo payload already
    collected by the daily sync (hourly time/temperature_2m/dew_point_2m in
    local time); missing/short data degrades to ``{"available": False}``.
    """
    hourly = (forecast or {}).get("hourly") or {}
    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or []
    dews = hourly.get("dew_point_2m") or []
    day_prefix = day.isoformat()

    by_hour: dict[int, float] = {}
    temp_by_hour: dict[int, float] = {}
    dew_by_hour: dict[int, float] = {}
    for i, stamp in enumerate(times):
        if not isinstance(stamp, str) or not stamp.startswith(day_prefix):
            continue
        try:
            hour = int(stamp[11:13])
        except ValueError:
            continue
        temp = _f(temps[i]) if i < len(temps) else None
        dew = _f(dews[i]) if i < len(dews) else None
        if temp is None or dew is None:
            continue
        temp_f, dew_f = temp * 9 / 5 + 32, dew * 9 / 5 + 32
        by_hour[hour] = temp_f + dew_f
        temp_by_hour[hour] = temp_f
        dew_by_hour[hour] = dew_f

    best_start: int | None = None
    best_score: float | None = None
    for start in range(_RUN_EARLIEST_H, _RUN_LATEST_H - block_hours + 1):
        hours = [start + o for o in range(block_hours)]
        if not all(h in by_hour for h in hours):
            continue
        score = sum(by_hour[h] for h in hours) / block_hours
        if best_score is None or score < best_score:
            best_start, best_score = start, score

    if best_start is None or best_score is None:
        return {"available": False}
    end = best_start + block_hours
    return {
        "available": True,
        "day": day_prefix,
        "start_hour": best_start,
        "end_hour": end,
        "label": f"{_hour_label(best_start)}-{_hour_label(end)}",
        "avg_temp_f": round(
            sum(temp_by_hour[best_start + o] for o in range(block_hours)) / block_hours, 1
        ),
        "avg_dew_point_f": round(
            sum(dew_by_hour[best_start + o] for o in range(block_hours)) / block_hours, 1
        ),
        "comfort_sum": round(best_score, 1),
    }


# -- event countdown ----------------------------------------------------------


def event_countdown(
    name: str, event_date: date, today: date, kind: str = "other"
) -> dict[str, Any]:
    """Days/weeks remaining to a configured goal event."""
    days = (event_date - today).days
    return {
        "available": True,
        "name": name,
        "date": str(event_date),
        "kind": kind,
        "days_until": days,
        "weeks_until": round(days / 7, 1),
        "is_past": days < 0,
    }
