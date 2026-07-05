"""Pace coach (M7). Running-science goal setting and a plan to get there.

Implements Jack Daniels' VDOT model (Daniels' Running Formula, 3rd ed.):

* VO2 cost of a velocity and the fraction of VO2max sustainable for a duration,
  which together map any race performance to a **VDOT** fitness number.
* Inverting that gives personalized **training paces** (Easy / Marathon /
  Threshold / Interval / Rep) for a VDOT.
* A goal (distance + target time) becomes a required VDOT; the gap to current
  fitness becomes a **week-by-week plan** with a sane mileage ramp.

Everything here is pure math on numbers — no DB, no I/O — so it's fully testable.
Personalization for Trent (Hartselle heat, Mount Whitney altitude) is applied as
explicit, cited adjustments rather than hidden fudge factors.
"""

from __future__ import annotations

import math
from typing import Any

M_PER_MILE = 1609.34

# Named race distances (metres).
RACES: dict[str, float] = {
    "1 mile": M_PER_MILE,
    "5K": 5000.0,
    "10K": 10000.0,
    "Half Marathon": 21097.5,
    "Marathon": 42195.0,
}

# Daniels training intensities as a fraction of VDOT (VO2max) used to derive
# each pace. Values are the representative mid-points of Daniels' zones.
TRAINING_INTENSITY: dict[str, float] = {
    "easy": 0.70,  # E: 59-74% — aerobic base, most weekly volume
    "marathon": 0.79,  # M: marathon-effort
    "threshold": 0.86,  # T: "comfortably hard", ~1 hr race effort
    "interval": 0.975,  # I: at/near vVO2max
    "repetition": 1.05,  # R: faster than vVO2max, economy/speed
}

PACE_LABELS: dict[str, str] = {
    "easy": "Easy",
    "marathon": "Marathon",
    "threshold": "Threshold",
    "interval": "Interval",
    "repetition": "Rep",
}


# -- core Daniels formulas ---------------------------------------------------


def _vo2_of_velocity(v_m_per_min: float) -> float:
    """Oxygen cost (ml/kg/min) of running at ``v`` metres/minute."""
    return -4.60 + 0.182258 * v_m_per_min + 0.000104 * v_m_per_min**2


def _fraction_of_vo2max(t_min: float) -> float:
    """Fraction of VO2max sustainable for ``t`` minutes (drops as races lengthen)."""
    return 0.8 + 0.1894393 * math.exp(-0.012778 * t_min) + 0.2989558 * math.exp(-0.1932605 * t_min)


def _velocity_of_vo2(vo2: float) -> float:
    """Invert the VO2 quadratic to get velocity (m/min) for an oxygen cost."""
    a, b, c = 0.000104, 0.182258, -4.60 - vo2
    disc = b * b - 4 * a * c
    if disc < 0:
        return 0.0
    return (-b + math.sqrt(disc)) / (2 * a)


def vdot_from_performance(distance_m: float, time_s: float) -> float:
    """Map a race performance to a VDOT fitness score."""
    if distance_m <= 0 or time_s <= 0:
        return 0.0
    t_min = time_s / 60.0
    v = distance_m / t_min
    return round(_vo2_of_velocity(v) / _fraction_of_vo2max(t_min), 1)


def predict_time(vdot: float, distance_m: float) -> float:
    """Predict race time (seconds) for a VDOT over a distance (bisection solve)."""
    lo, hi = 1.0, 600.0  # minutes
    for _ in range(60):
        mid = (lo + hi) / 2
        v = distance_m / mid
        implied = _vo2_of_velocity(v) / _fraction_of_vo2max(mid)
        # Faster (smaller mid) -> higher implied VDOT. Adjust the bracket.
        if implied > vdot:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2 * 60.0, 0)


def training_paces(vdot: float) -> dict[str, dict[str, Any]]:
    """Personalized training paces for a VDOT, per km and per mile."""
    out: dict[str, dict[str, Any]] = {}
    for key, frac in TRAINING_INTENSITY.items():
        v = _velocity_of_vo2(vdot * frac)  # m/min
        if v <= 0:
            continue
        sec_per_km = 60_000.0 / v
        sec_per_mi = sec_per_km * (M_PER_MILE / 1000.0)
        out[key] = {
            "label": PACE_LABELS[key],
            "sec_per_km": round(sec_per_km),
            "sec_per_mile": round(sec_per_mi),
            "per_km": fmt_pace(sec_per_km),
            "per_mile": fmt_pace(sec_per_mi),
        }
    return out


# -- formatting --------------------------------------------------------------


def fmt_pace(sec: float) -> str:
    """Seconds per unit -> 'M:SS'."""
    s = round(sec)
    return f"{s // 60}:{s % 60:02d}"


def fmt_time(sec: float) -> str:
    """Seconds -> 'H:MM:SS' or 'M:SS'."""
    s = round(sec)
    h, rem = divmod(s, 3600)
    m, sec_ = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec_:02d}" if h else f"{m}:{sec_:02d}"


# -- heat & altitude (Trent-specific) ----------------------------------------


def heat_penalty_pct(temp_f: float, dew_point_f: float | None = None) -> float:
    """Approx endurance-pace slowdown (%) from heat above ~60°F.

    Rule of thumb from marathon performance studies (e.g. Ely et al., 2007):
    roughly 1.5-3% slower per ~10°F above the low-60s once acclimatization is
    accounted for. We use ~2% per 10°F as a middle estimate.
    """
    over = max(0.0, temp_f - 60.0)
    pct = (over / 10.0) * 2.0
    if dew_point_f is not None and dew_point_f >= 65:
        pct += 1.5  # humid air compounds it — very relevant for Alabama summers
    return round(pct, 1)


def heat_table(base_sec_per_mi: float) -> list[dict[str, Any]]:
    """Show how a goal pace realistically drifts across Hartselle temperatures."""
    rows = []
    for temp in (60, 70, 80, 90):
        pct = heat_penalty_pct(float(temp))
        adj = base_sec_per_mi * (1 + pct / 100.0)
        rows.append(
            {
                "temp_f": temp,
                "penalty_pct": pct,
                "per_mile": fmt_pace(adj),
                "sec_per_mile": round(adj),
            }
        )
    return rows


def altitude_note(altitude_acclimation_pct: float | None) -> str:
    """Whitney-oriented altitude context tied to Garmin's acclimation reading."""
    base = (
        "Mount Whitney tops out at 14,505 ft, where VO2max drops roughly 8-12% vs "
        "sea level and pace suffers well before the summit. "
    )
    if altitude_acclimation_pct is None:
        return base + "Garmin has no altitude-acclimation reading for you yet (you train at ~0 ft)."
    if altitude_acclimation_pct < 20:
        return (
            base + f"Your altitude acclimation is only {altitude_acclimation_pct:.0f}% — "
            "arrive 2-3 days early or plan a graded ascent; the first days are the hardest."
        )
    return base + f"Your altitude acclimation is {altitude_acclimation_pct:.0f}% and building."


# -- the plan ----------------------------------------------------------------


def _phase(week: int, weeks: int) -> str:
    frac = week / weeks
    if frac <= 0.40:
        return "Base"
    if frac <= 0.75:
        return "Build"
    if frac <= 0.90:
        return "Peak"
    return "Taper"


def _week_focus(phase: str, goal_key: str) -> str:
    focus = {
        "Base": "Aerobic volume + strides; one steady long run",
        "Build": "Add Threshold (T) work; extend the long run",
        "Peak": f"Interval (I) + goal-pace {goal_key} reps; peak long run",
        "Taper": "Cut volume ~40%, keep a little sharpness, arrive fresh",
    }
    return focus[phase]


def build_plan(
    current_vdot: float,
    goal_distance_m: float,
    goal_time_s: float | None,
    weeks: int,
    current_weekly_miles: float,
    goal_key: str = "goal",
) -> dict[str, Any]:
    """Assemble a week-by-week plan from current fitness to the goal."""
    weeks = max(4, min(30, weeks))
    start_miles = max(8.0, round(current_weekly_miles or 12.0, 0))
    peak_miles = round(start_miles * min(1.9, 1.0 + weeks * 0.06), 0)

    if goal_time_s:
        goal_vdot = vdot_from_performance(goal_distance_m, goal_time_s)
    else:
        goal_vdot = round(current_vdot + 2.0, 1)  # modest default improvement
        goal_time_s = predict_time(goal_vdot, goal_distance_m)

    gap = round(goal_vdot - current_vdot, 1)
    # VDOT improves ~1 point per ~3.5 weeks of consistent training early on.
    weeks_needed = max(0.0, round(gap * 3.5, 0))
    if gap <= 0:
        verdict, headline = "already-there", "You're already at this fitness — go race it."
    elif weeks_needed <= weeks * 0.8:
        verdict, headline = (
            "on-track",
            f"Realistic: ~{weeks_needed:.0f} weeks of work, and you have {weeks}.",
        )
    elif weeks_needed <= weeks * 1.2:
        verdict, headline = (
            "ambitious",
            f"Ambitious but possible — the timeline is tight ({weeks_needed:.0f} vs {weeks} wks).",
        )
    else:
        verdict, headline = (
            "very-ambitious",
            (
                f"Very ambitious: this typically needs ~{weeks_needed:.0f} weeks; "
                "consider a longer horizon or a softer target."
            ),
        )

    schedule: list[dict[str, Any]] = []
    for wk in range(1, weeks + 1):
        phase = _phase(wk, weeks)
        # 3-weeks-up / 1-week-cutback progression toward peak, then taper.
        if phase == "Taper":
            mileage = round(peak_miles * (0.6 if wk == weeks - 1 else 0.45), 0)
        else:
            ramp = (wk - 1) / max(1, int(weeks * 0.9))
            mileage = round(start_miles + (peak_miles - start_miles) * min(1.0, ramp), 0)
            if wk % 4 == 0:  # cutback week
                mileage = round(mileage * 0.8, 0)
        long_run = round(min(mileage * 0.35, peak_miles * 0.35), 0)
        schedule.append(
            {
                "week": wk,
                "phase": phase,
                "focus": _week_focus(phase, goal_key),
                "mileage": mileage,
                "long_run_miles": long_run,
            }
        )

    return {
        "current_vdot": current_vdot,
        "goal_vdot": goal_vdot,
        "goal_time": fmt_time(goal_time_s),
        "gap_vdot": gap,
        "weeks": weeks,
        "weeks_needed_estimate": weeks_needed,
        "verdict": verdict,
        "headline": headline,
        "mileage_start": start_miles,
        "mileage_peak": peak_miles,
        "goal_paces": training_paces(goal_vdot),
        "schedule": schedule,
    }
