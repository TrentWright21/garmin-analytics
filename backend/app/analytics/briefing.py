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
    activities: pl.DataFrame, now: datetime, tsb: float | None = None
) -> dict[str, Any]:
    """Time since the last session and an estimate of hours until recovered.

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
    load = _session_load(last)
    need = _recovery_hours_for(load)
    pct = min(100, round(hours_since / need * 100)) if need else 100
    recovered = hours_since >= need

    if not recovered:
        remaining = round(need - hours_since, 1)
        recommendation = (
            f"About {remaining:.0f} h until you're recovered from your last session. "
            "Keep today easy or take it as rest."
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
