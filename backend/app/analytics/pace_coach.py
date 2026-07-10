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
from itertools import pairwise
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


# -- race-specific training volume (research pass, 2026-07-10) ----------------
#
# The old model scaled peak mileage from CURRENT volume only, so a 7 mi/wk
# runner got a ~13 mi/wk "half marathon plan". Volume targets are now anchored
# to the RACE and the GOAL TIME. Sources (multi-source research sweep
# 2026-07-10; single-pass extraction corroborated against the primary papers —
# the adversarial verify stage was cut short by a usage limit):
#
# * Fokkema et al. 2020 (PMC7496388, prospective, n=997): half-marathoners
#   peaking >32 km/wk (~20 mi) finished ~4 min faster; marathoners <40 km/wk
#   (~25 mi) were slower and >65 km/wk (~40 mi) ~14 min faster; the longest
#   run needn't exceed ~35 km (~22 mi); higher volume showed NO extra injury
#   risk in this cohort.
# * Progression evidence (Buist 2008 RCT n=532; Nielsen 2012/2014; Damsted
#   2018): the weekly "10% rule" is NOT protective (20.8% vs 20.3% injuries at
#   10% vs 24% weekly growth); >30% weekly jumps trend risky; a 2025 cohort
#   (PMC12421110) locates the real risk in SESSION spikes — keep any single
#   run within ~110% of the last month's longest. So the ramp caps ABSOLUTE
#   weekly jumps and grows the long run gradually, not by a magic 10%.
# * Taper (Bosquet 2007 meta-analysis; 2023 meta): cut volume 41-60% over
#   ~8-14 days keeping intensity and frequency; large marathon field data
#   (Strava, n=158k) favors up to 3 weeks for the marathon itself.
# * Plan anchors: Higdon Novice HM starts 12 mpw, peaks 23 (long run 10);
#   Higdon marathon Novice 1 peaks ~40 mpw (long 18-20), Intermediate 45-50,
#   Hansons caps the long run at 16 mi, Pfitzinger 55+; Couch-to-5K reaches a
#   5K in 9 weeks; couch-to-marathon is ~24 weeks.

# Per race: the volume floor below which race-day suffers (research/plan
# consensus), goal-time -> peak-mileage anchors (seconds, miles/week; slowest
# first), long-run share of weekly volume + absolute cap, taper length, and a
# typical minimum preparation horizon from a low (~5-10 mpw) base.
RACE_VOLUME: dict[str, dict[str, Any]] = {
    "1 mile": {
        "floor_peak": 10.0,
        "long_share": 0.30,
        "long_cap": 8.0,
        "taper_weeks": 1,
        "min_prep_weeks": 6,
        "anchors": [(600.0, 12.0), (480.0, 18.0), (420.0, 25.0), (360.0, 35.0), (300.0, 45.0)],
    },
    "5K": {
        "floor_peak": 12.0,
        "long_share": 0.32,
        "long_cap": 9.0,
        "taper_weeks": 1,
        "min_prep_weeks": 8,
        "anchors": [(2100.0, 15.0), (1800.0, 20.0), (1500.0, 28.0), (1320.0, 35.0), (1140.0, 45.0)],
    },
    "10K": {
        "floor_peak": 15.0,
        "long_share": 0.35,
        "long_cap": 11.0,
        "taper_weeks": 1,
        "min_prep_weeks": 10,
        "anchors": [(4500.0, 18.0), (3900.0, 22.0), (3300.0, 30.0), (2880.0, 40.0), (2520.0, 50.0)],
    },
    "Half Marathon": {
        "floor_peak": 20.0,  # the Fokkema performance threshold (~32 km/wk)
        "long_share": 0.45,
        "long_cap": 13.0,
        "taper_weeks": 2,
        "min_prep_weeks": 12,
        "anchors": [
            (9900.0, 20.0),  # 2:45
            (9000.0, 22.0),  # 2:30
            (8100.0, 24.0),  # 2:15
            (7200.0, 28.0),  # 2:00
            (6300.0, 35.0),  # 1:45
            (5400.0, 45.0),  # 1:30
        ],
    },
    "Marathon": {
        "floor_peak": 25.0,  # Fokkema: <40 km/wk was measurably slower
        "long_share": 0.50,
        "long_cap": 20.0,  # plans peak 16-20; research shows no gain past ~22
        "taper_weeks": 3,
        "min_prep_weeks": 18,
        "anchors": [
            (19800.0, 28.0),  # 5:30
            (18000.0, 30.0),  # 5:00
            (16200.0, 34.0),  # 4:30
            (14400.0, 40.0),  # 4:00
            (12600.0, 48.0),  # 3:30
            (10800.0, 58.0),  # 3:00
        ],
    },
}

# Race-week (and preceding) volume as a fraction of peak, per taper length —
# the last entry is race week. Cuts land in Bosquet's 41-60% band.
_TAPER_FRACTIONS: dict[int, list[float]] = {1: [0.55], 2: [0.70, 0.50], 3: [0.80, 0.65, 0.45]}

# Weekly mileage increment during the build: proportional at higher volume but
# never a big absolute jump (session spikes, not weekly percentages, carry the
# measured injury risk — so cap the jump, don't fetishize 10%).
_RAMP_FRACTION = 0.12
_RAMP_MIN_MI = 2.0
_RAMP_MAX_MI = 4.0

_VOLUME_RESEARCH_NOTE: dict[str, str] = {
    "1 mile": "Mile racing rewards speed on an aerobic base; ~15-25 mi/wk covers most goals.",
    "5K": "Novice 5K plans live near 15 mi/wk; faster goals reward 25-40 mi/wk of base.",
    "10K": "10K plans typically peak 20-30 mi/wk for novices, 40+ for sharp goals.",
    "Half Marathon": (
        "Recreational half-marathoners peaking above ~20 mi/wk raced ~4 min faster "
        "(Fokkema 2020); classic novice plans peak 23-30 mi/wk."
    ),
    "Marathon": (
        "Below ~25 mi/wk marathon times measurably suffer and faster finishers cluster "
        "at 40+ mi/wk (Fokkema 2020); the long run needn't exceed ~20 mi."
    ),
}


def race_volume(goal_key: str, goal_time_s: float) -> dict[str, Any]:
    """Race- and goal-time-specific volume targets (pure lookup + interpolation)."""
    cfg = RACE_VOLUME.get(goal_key, RACE_VOLUME["Half Marathon"])
    anchors: list[tuple[float, float]] = cfg["anchors"]
    target = _interp_anchors(anchors, goal_time_s)
    return {
        "target_peak": round(target, 0),
        "floor_peak": cfg["floor_peak"],
        "long_share": cfg["long_share"],
        "long_cap": cfg["long_cap"],
        "taper_weeks": cfg["taper_weeks"],
        "min_prep_weeks": cfg["min_prep_weeks"],
    }


def _interp_anchors(anchors: list[tuple[float, float]], goal_time_s: float) -> float:
    """Linear interpolation of peak mileage between goal-time anchors."""
    if goal_time_s >= anchors[0][0]:
        return anchors[0][1]
    if goal_time_s <= anchors[-1][0]:
        return anchors[-1][1]
    for (t_slow, m_slow), (t_fast, m_fast) in pairwise(anchors):
        if t_fast <= goal_time_s <= t_slow:
            frac = (t_slow - goal_time_s) / (t_slow - t_fast)
            return m_slow + frac * (m_fast - m_slow)
    return anchors[-1][1]


def tanda_marathon_peak_miles(goal_time_s: float, easy_pace_s_per_km: float) -> float | None:
    """Marathon-only cross-check: weekly volume implied by the Tanda equation.

    Tanda (2011, revalidated 2020, RMSE ~5.4 min): marathon pace Pm (s/km) =
    17.1 + 140*exp(-0.0053*K) + 0.55*P, with K = mean weekly km over the final
    8 weeks and P = mean training pace (s/km). Inverting for K at the athlete's
    easy pace gives the average volume that historically supports the goal;
    peak is ~1/0.85 of the 8-week average. None when the goal is outside the
    equation's domain (very fast/slow goals).
    """
    pm = goal_time_s / 42.195
    inner = pm - 17.1 - 0.55 * easy_pace_s_per_km
    if inner <= 0 or inner >= 140.0:
        return None
    k_km_per_wk = -math.log(inner / 140.0) / 0.0053
    peak_mi = (k_km_per_wk / 1.60934) / 0.85
    return round(peak_mi, 0) if 10.0 <= peak_mi <= 90.0 else None


def _phase_for(build_week: int, build_weeks: int) -> str:
    frac = build_week / max(1, build_weeks)
    if frac <= 0.45:
        return "Base"
    if frac <= 0.80:
        return "Build"
    return "Peak"


def _week_focus(phase: str, goal_key: str) -> str:
    focus = {
        "Base": "Aerobic volume + strides; one steady long run",
        "Build": "Add Threshold (T) work; extend the long run",
        "Peak": f"Interval (I) + goal-pace {goal_key} reps; peak long run",
        "Taper": "Cut volume 40-60%, keep intensity and frequency, arrive fresh",
    }
    return focus[phase]


def _bump(verdict: str, at_least: int = 0) -> str:
    order = ["already-there", "on-track", "ambitious", "very-ambitious"]
    idx = order.index(verdict) if verdict in order else 1
    return order[min(max(idx + 1, at_least), len(order) - 1)]


def build_plan(
    current_vdot: float,
    goal_distance_m: float,
    goal_time_s: float | None,
    weeks: int,
    current_weekly_miles: float,
    goal_key: str = "goal",
) -> dict[str, Any]:
    """Assemble a week-by-week plan from current fitness to the goal.

    Fitness (VDOT gap) and VOLUME (race-specific weekly-mileage targets) are
    judged separately and both feed the verdict: being fast enough on paper
    doesn't help if the safe ramp can't reach the volume the race rewards.
    """
    weeks = max(4, min(30, weeks))

    if goal_time_s:
        goal_vdot = vdot_from_performance(goal_distance_m, goal_time_s)
    else:
        goal_vdot = round(current_vdot + 2.0, 1)  # modest default improvement
        goal_time_s = predict_time(goal_vdot, goal_distance_m)

    # -- volume targets for THIS race + goal ---------------------------------
    vol = race_volume(goal_key, goal_time_s)
    target_peak = float(vol["target_peak"])
    start_miles = max(5.0, round(current_weekly_miles or 8.0, 0))
    # Never prescribe less than the athlete already runs — maintain, don't cut.
    target_peak = max(target_peak, start_miles)

    taper_weeks = int(min(vol["taper_weeks"], max(1, weeks // 4)))
    build_weeks = weeks - taper_weeks

    # Safe build: capped absolute weekly jumps with a cutback every 4th week.
    mileages: list[float] = []
    m = start_miles
    for wk in range(1, build_weeks + 1):
        shown = m * 0.8 if (wk % 4 == 0 and wk != build_weeks) else m
        mileages.append(round(shown, 0))
        inc = min(_RAMP_MAX_MI, max(_RAMP_MIN_MI, m * _RAMP_FRACTION))
        m = min(target_peak, m + inc)
    peak_miles = round(max(mileages) if mileages else start_miles, 0)

    volume_limited = peak_miles < target_peak - 1.0
    under_floor = peak_miles < float(vol["floor_peak"]) - 0.5

    # -- fitness verdict (VDOT gap), then volume adjustments ------------------
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

    if under_floor:
        # A volume shortfall makes the goal at least "ambitious", whatever the
        # paper fitness says — and "go race it" would be the wrong send-off.
        verdict = _bump(verdict, at_least=2)
        fitness_context = (
            "Your speed is already there; the weekly miles aren't yet." if gap <= 0 else headline
        )
        headline = (
            f"Volume is the limiter: a safe ramp from {start_miles:.0f} mi/wk reaches "
            f"~{peak_miles:.0f} in {weeks} weeks, under the ~{vol['floor_peak']:.0f} mi/wk "
            f"this distance rewards. " + fitness_context
        )

    volume_note = (
        f"Volume target for this goal: ~{target_peak:.0f} mi/wk at peak "
        f"(distance floor ~{vol['floor_peak']:.0f}); this plan reaches "
        f"{peak_miles:.0f} mi/wk. " + _VOLUME_RESEARCH_NOTE.get(goal_key, "")
    )
    if goal_key == "Marathon":
        easy = training_paces(goal_vdot).get("easy")
        tanda = tanda_marathon_peak_miles(goal_time_s, float(easy["sec_per_km"])) if easy else None
        if tanda is not None:
            volume_note += f" Tanda-model cross-check: ~{tanda:.0f} mi/wk peak for this time."
    if weeks < int(vol["min_prep_weeks"]) and target_peak > start_miles * 1.5:
        volume_note += (
            f" Note: from a low base, {goal_key} prep typically wants "
            f"~{vol['min_prep_weeks']} weeks (you have {weeks})."
        )

    # -- schedule --------------------------------------------------------------
    long_share, long_cap = float(vol["long_share"]), float(vol["long_cap"])

    def _long_run(weekly_mi: float) -> float:
        return round(min(long_cap, weekly_mi * long_share), 0)

    schedule: list[dict[str, Any]] = []
    for wk in range(1, build_weeks + 1):
        phase = _phase_for(wk, build_weeks)
        mileage = mileages[wk - 1]
        schedule.append(
            {
                "week": wk,
                "phase": phase,
                "focus": _week_focus(phase, goal_key),
                "mileage": mileage,
                "long_run_miles": _long_run(mileage),
            }
        )
    for i, frac in enumerate(_TAPER_FRACTIONS[taper_weeks]):
        mileage = round(peak_miles * frac, 0)
        schedule.append(
            {
                "week": build_weeks + i + 1,
                "phase": "Taper",
                "focus": _week_focus("Taper", goal_key),
                "mileage": mileage,
                "long_run_miles": _long_run(mileage),
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
        "mileage_target_peak": target_peak,
        "volume_limited": volume_limited,
        "volume_note": volume_note,
        "long_run_peak": _long_run(peak_miles),
        "taper_weeks": taper_weeks,
        "goal_paces": training_paces(goal_vdot),
        "schedule": schedule,
    }
