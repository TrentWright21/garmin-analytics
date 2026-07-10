"""Goal-plan generator (Phase 4): an event-anchored week-by-week training plan.

Turns the configured goal EVENT (a summit hike, a race, ...) into a dated,
phase-structured plan of weekly targets — mileage, elevation-gain (vert), and a
long effort — then overlays the athlete's ACTUAL weekly volume so they can see
where they stand versus where a typical build wants them.

The plan is anchored to the event: its final week is the event's calendar week
and it spans ``plan_weeks`` back from there, so weeks that have already elapsed
carry an actual overlay (retrospective adherence) while upcoming weeks carry
targets (the final push). Vert progression is first-class here because summit
days are defined by elevation gain, not distance — Mount Whitney's day hike is
~6,100 ft of gain, so the weekly vert targets, not the mileage, are the crux.

Pure functions: the route layer loads the weekly-volume actuals and the event
config and hands them in. No DB, no I/O — fully unit-testable.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

# Per event kind: an idealized plan length + taper, peak weekly targets, and the
# label for the week's key session. Peak vert is overridden by the event's own
# configured elevation gain when present (the summit's real demand is the anchor).
_KIND: dict[str, dict[str, Any]] = {
    "climb": {
        "plan_weeks": 16,
        "taper_weeks": 2,
        "peak_miles": 30.0,
        "peak_vert_ft": 6000.0,
        "long": "long hike",
    },
    "hike": {
        "plan_weeks": 12,
        "taper_weeks": 1,
        "peak_miles": 24.0,
        "peak_vert_ft": 4000.0,
        "long": "long hike",
    },
    "race": {
        "plan_weeks": 14,
        "taper_weeks": 2,
        "peak_miles": 32.0,
        "peak_vert_ft": 1500.0,
        "long": "long run",
    },
    "other": {
        "plan_weeks": 12,
        "taper_weeks": 1,
        "peak_miles": 24.0,
        "peak_vert_ft": 2000.0,
        "long": "long effort",
    },
}

_START_FRACTION = 0.45  # week-1 target as a fraction of peak
_TAPER_FRACTIONS: dict[int, list[float]] = {1: [0.55], 2: [0.70, 0.50], 3: [0.80, 0.65, 0.45]}
_ON_TRACK = 0.85  # actual/target at or above this reads as on-track
_BUILDING = 0.60  # between this and _ON_TRACK reads as building; below is behind


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _phase(build_week: int, build_weeks: int) -> str:
    frac = build_week / max(1, build_weeks)
    if frac <= 0.45:
        return "Base"
    if frac <= 0.80:
        return "Build"
    return "Peak"


def goal_plan(
    *,
    event_name: str,
    event_date: date,
    event_kind: str,
    today: date,
    weekly_actual: list[dict[str, Any]],
    event_vert_gain_ft: float | None = None,
) -> dict[str, Any]:
    """Event-anchored weekly plan with an actual-volume overlay and adherence.

    ``weekly_actual`` is ``engine.weekly_volume`` output (Monday-anchored rows
    with ``week``/``miles``/``vert_ft``). Returns the dated week list, a summary
    (this-week targets, peak, days/weeks to go, current phase), and an adherence
    read over the elapsed weeks that fall within the athlete's actual data.
    """
    tmpl = _KIND.get(event_kind, _KIND["other"])
    plan_weeks = int(tmpl["plan_weeks"])
    taper_weeks = int(tmpl["taper_weeks"])
    build_weeks = plan_weeks - taper_weeks
    peak_miles = float(tmpl["peak_miles"])
    peak_vert = float(event_vert_gain_ft or tmpl["peak_vert_ft"])
    long_label = str(tmpl["long"])

    event_monday = _monday(event_date)
    this_monday = _monday(today)
    start_monday = event_monday - timedelta(weeks=plan_weeks - 1)
    days_until = (event_date - today).days

    actual_by_week: dict[str, dict[str, Any]] = {
        str(row["week"]): row for row in weekly_actual if row.get("week") is not None
    }
    actual_weeks = sorted(actual_by_week)
    earliest_actual = date.fromisoformat(actual_weeks[0]) if actual_weeks else None

    weeks: list[dict[str, Any]] = []
    scored_miles: list[float] = []
    scored_vert: list[float] = []
    for i in range(plan_weeks):
        wk_monday = start_monday + timedelta(weeks=i)
        n = i + 1  # 1-indexed
        if n <= build_weeks:
            phase = _phase(n, build_weeks)
            ramp = _START_FRACTION + (1 - _START_FRACTION) * ((n - 1) / max(1, build_weeks - 1))
            # 3-up / 1-down: every 4th build week is a cutback (never the last).
            factor = ramp * (0.8 if (n % 4 == 0 and n != build_weeks) else 1.0)
        else:
            phase = "Taper"
            factor = _TAPER_FRACTIONS[taper_weeks][n - build_weeks - 1]
        t_miles = round(peak_miles * factor)
        t_vert = round(peak_vert * factor / 100) * 100

        status = (
            "elapsed"
            if wk_monday < this_monday
            else "current"
            if wk_monday == this_monday
            else "upcoming"
        )
        entry: dict[str, Any] = {
            "week": n,
            "week_start": str(wk_monday),
            "phase": phase,
            "status": status,
            "target_miles": t_miles,
            "target_vert_ft": t_vert,
            "long_effort": long_label,
        }

        # Overlay actuals for elapsed + current weeks; score adherence only for
        # weeks within the athlete's real data range (missing = a genuine 0).
        if status in ("elapsed", "current"):
            act = actual_by_week.get(str(wk_monday))
            a_miles = _f(act.get("miles")) if act else None
            a_vert = _f(act.get("vert_ft")) if act else None
            in_range = earliest_actual is not None and wk_monday >= earliest_actual
            entry["actual_miles"] = (
                round(a_miles, 1) if a_miles is not None else (0.0 if in_range else None)
            )
            entry["actual_vert_ft"] = (
                round(a_vert) if a_vert is not None else (0 if in_range else None)
            )
            if in_range and status == "elapsed":
                scored_miles.append((a_miles or 0.0) / t_miles if t_miles else 0.0)
                scored_vert.append((a_vert or 0.0) / t_vert if t_vert else 0.0)
        weeks.append(entry)

    current = next((w for w in weeks if w["status"] == "current"), None)
    adherence = _adherence(
        scored_miles, scored_vert, event_name, event_kind, days_until, long_label
    )

    return {
        "available": True,
        "event": {
            "name": event_name,
            "date": str(event_date),
            "kind": event_kind,
            "days_until": days_until,
            "weeks_until": round(days_until / 7, 1),
            "is_past": days_until < 0,
            "vert_gain_ft": int(peak_vert),
        },
        "plan_weeks": plan_weeks,
        "taper_weeks": taper_weeks,
        "peak_miles": round(peak_miles),
        "peak_vert_ft": int(peak_vert),
        "this_week": (
            {
                "phase": current["phase"],
                "target_miles": current["target_miles"],
                "target_vert_ft": current["target_vert_ft"],
                "long_effort": current["long_effort"],
            }
            if current
            else None
        ),
        "adherence": adherence,
        "weeks": weeks,
    }


def _adherence(
    miles_ratios: list[float],
    vert_ratios: list[float],
    event_name: str,
    event_kind: str,
    days_until: int,
    long_label: str,
) -> dict[str, Any]:
    """Retrospective adherence: mean actual/target over scored elapsed weeks.

    ``status`` follows the WORSE of the two dimensions (a climb built on miles
    but no vert isn't ready), and the headline is honest — under-building is
    stated plainly rather than dressed up, and the advice leans on the vert
    that summit days actually demand.
    """
    if not miles_ratios:
        return {"available": False}
    miles_pct = round(sum(miles_ratios) / len(miles_ratios) * 100)
    vert_pct = round(sum(vert_ratios) / len(vert_ratios) * 100)
    # Vert is the binding constraint for climbs/hikes; miles for everything else.
    primary = vert_pct if event_kind in ("climb", "hike") else miles_pct
    weeks_left = max(0, round(days_until / 7))

    if primary >= _ON_TRACK * 100:
        status, headline = (
            "on-track",
            f"You're tracking a typical {event_kind} build — hold the {long_label} and keep "
            "banking vert.",
        )
    elif primary >= _BUILDING * 100:
        status, headline = (
            "building",
            f"A little under a typical build. The vert is what {event_name} rewards — make the "
            f"weekly {long_label} your priority for the {weeks_left} weeks left.",
        )
    else:
        status, headline = (
            "behind",
            f"Well under a typical {event_kind} build. Be realistic on the day: go steady, and "
            f"bank as much climbing as you safely can over the last {weeks_left} weeks.",
        )
    return {
        "available": True,
        "miles_pct": miles_pct,
        "vert_ft_pct": vert_pct,
        "weeks_scored": len(miles_ratios),
        "status": status,
        "headline": headline,
    }
