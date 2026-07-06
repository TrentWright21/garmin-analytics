"""Fitness modelling (M8): the Performance Management Chart and friends.

The centrepiece is the impulse-response / PMC model that TrainingPeaks and (in a
black box) Garmin's "Training Status" are built on:

* **CTL** — Chronic Training Load, a 42-day exponentially-weighted average of
  daily load. This is *Fitness*: it rises slowly and falls slowly.
* **ATL** — Acute Training Load, a 7-day EWMA of daily load. This is *Fatigue*:
  it rises and falls fast.
* **TSB** — Training Stress Balance = CTL - ATL. This is *Form*: positive means
  fresh, deeply negative means buried under fatigue.

Unlike Garmin we expose every number and the interpretation bands, so the coach
can say "you are fresh because your fatigue has dropped faster than your fitness"
instead of showing an opaque badge.

Pure Polars/maths over frames the loaders in ``engine`` provide — unit-testable
with synthetic load series.
"""

from __future__ import annotations

import math
from typing import Any

import polars as pl

from app.analytics.physiology import _f, estimate_hr_max, intensity_band

# Time constants (days) for the two EWMAs. 42/7 is the de-facto standard.
FITNESS_TAU = 42
FATIGUE_TAU = 7

# Weekly CTL gain beyond which injury risk climbs (the classic "ramp rate").
SAFE_RAMP_PER_WEEK = 5.0
AGGRESSIVE_RAMP_PER_WEEK = 8.0


def _alpha(tau: int) -> float:
    """EWMA smoothing factor for an N-day exponential time constant."""
    return 1.0 - math.exp(-1.0 / tau)


def _dense_daily_load(load_by_day: pl.DataFrame) -> pl.DataFrame:
    """Sort, fill the calendar to one row per day, zero-fill rest days."""
    return (
        load_by_day.sort("day")
        .upsample("day", every="1d")
        .with_columns(pl.col("load").fill_null(0.0))
    )


def performance_management(load_by_day: pl.DataFrame) -> pl.DataFrame:
    """Daily Fitness (CTL), Fatigue (ATL), Form (TSB) and 7-day ramp.

    ``load_by_day`` is the output of ``engine.daily_training_load`` (columns
    ``day``, ``load``). Returns one row per calendar day with the PMC series.
    """
    if load_by_day.is_empty():
        return pl.DataFrame({"day": [], "load": [], "ctl": [], "atl": [], "tsb": [], "ramp_7d": []})
    df = _dense_daily_load(load_by_day)
    df = df.with_columns(
        ctl=pl.col("load").ewm_mean(alpha=_alpha(FITNESS_TAU), adjust=False),
        atl=pl.col("load").ewm_mean(alpha=_alpha(FATIGUE_TAU), adjust=False),
    ).with_columns(
        tsb=(pl.col("ctl") - pl.col("atl")),
        ramp_7d=(pl.col("ctl") - pl.col("ctl").shift(7)),
    )
    return df.with_columns(
        pl.col("ctl").round(1),
        pl.col("atl").round(1),
        pl.col("tsb").round(1),
        pl.col("ramp_7d").round(1),
    )


def form_state(tsb: float | None) -> str:
    """Human label for a Training Stress Balance value.

    Bands follow common PMC practice. "fresh" is race-ready or under-loaded;
    "optimal" is the productive-training sweet spot; "overreached" is a warning.
    """
    if tsb is None:
        return "unknown"
    if tsb > 15:
        return "very_fresh"  # tapered/detraining
    if tsb > 5:
        return "fresh"
    if tsb >= -10:
        return "optimal"
    if tsb >= -30:
        return "productive"  # building, meaningful fatigue
    return "overreached"


def fitness_summary(load_by_day: pl.DataFrame) -> dict[str, Any]:
    """Latest Fitness/Fatigue/Form snapshot with interpretation and ramp flag."""
    pmc = performance_management(load_by_day)
    if pmc.is_empty():
        return {"available": False}
    last = pmc.tail(1).to_dicts()[0]
    ctl, atl, tsb, ramp = (last.get(k) for k in ("ctl", "atl", "tsb", "ramp_7d"))

    ramp_flag = "steady"
    if ramp is not None:
        if ramp > AGGRESSIVE_RAMP_PER_WEEK:
            ramp_flag = "aggressive"
        elif ramp > SAFE_RAMP_PER_WEEK:
            ramp_flag = "building"
        elif ramp < -SAFE_RAMP_PER_WEEK:
            ramp_flag = "detraining"

    return {
        "available": True,
        "as_of": str(last["day"]),
        "fitness_ctl": ctl,
        "fatigue_atl": atl,
        "form_tsb": tsb,
        "form_state": form_state(_f(tsb)),
        "ramp_7d": ramp,
        "ramp_flag": ramp_flag,
        "interpretation": _form_sentence(_f(tsb), _f(ctl)),
    }


def _form_sentence(tsb: float | None, ctl: float | None) -> str:
    state = form_state(tsb)
    base = {
        "very_fresh": "Very fresh — well tapered, but sustained high form means you are "
        "no longer building fitness.",
        "fresh": "Fresh and race-ready: fatigue has cleared while fitness held.",
        "optimal": "Balanced — training is productive without excessive fatigue.",
        "productive": "Carrying real fatigue from a solid training block; this is where "
        "fitness is built. Watch recovery.",
        "overreached": "Deeply fatigued (form well below -30). Back off before this "
        "becomes non-functional overreaching.",
        "unknown": "Not enough load history yet to establish form.",
    }[state]
    return base


# -- VO2max -------------------------------------------------------------------


def vo2max_trend(daily: pl.DataFrame, window: int = 90) -> dict[str, Any]:
    """Smoothed VO2max, its trend, and a confidence grade.

    Garmin's VO2max is a stepwise integer estimate that jitters. We EWMA-smooth
    it, fit its slope over ``window`` days, and grade confidence from how many
    distinct readings we have and how stable they are — so the coach never over-
    reads a one-point blip.
    """
    if daily.is_empty() or "vo2max_running" not in daily.columns:
        return {"available": False}
    s = daily.sort("day").select("day", "vo2max_running").drop_nulls()
    if s.is_empty():
        return {"available": False}

    s = s.with_columns(
        smoothed=pl.col("vo2max_running").ewm_mean(alpha=_alpha(14), adjust=False).round(2)
    )
    recent = s.tail(window)
    rows = recent.select("day", "vo2max_running").to_dicts()
    values = [float(r["vo2max_running"]) for r in rows]
    latest = _f(recent["smoothed"].tail(1).item())
    n = len(values)

    # Least-squares slope against ACTUAL day offsets (readings are sparse and
    # unevenly spaced, so a positional index would wildly over-project the rate).
    # Only fit once the readings span enough calendar time to be meaningful.
    slope_per_90d: float | None = None
    first_day = rows[0]["day"]
    xs = [float((r["day"] - first_day).days) for r in rows]
    span = xs[-1] if xs else 0.0
    if n >= 5 and span >= 14:
        mean_x = sum(xs) / n
        mean_y = sum(values) / n
        denom = sum((x - mean_x) ** 2 for x in xs)
        if denom > 0:
            slope = (
                sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values, strict=True)) / denom
            )
            # Report the rate per 90 days, clamped to a physiologically sane band
            # so a noisy short fit can't claim an impossible swing.
            slope_per_90d = round(max(-8.0, min(8.0, slope * 90)), 2)

    spread = _f(recent["vo2max_running"].std()) or 0.0
    distinct = recent["vo2max_running"].n_unique()
    if n >= 30 and distinct >= 3 and spread < 2.0:
        confidence = "high"
    elif n >= 12 and distinct >= 2:
        confidence = "moderate"
    else:
        confidence = "low"

    direction = "stable"
    if slope_per_90d is not None:
        if slope_per_90d >= 0.5:
            direction = "improving"
        elif slope_per_90d <= -0.5:
            direction = "declining"

    return {
        "available": True,
        "current": latest,
        "trend_per_90d": slope_per_90d,
        "direction": direction,
        "confidence": confidence,
        "readings": n,
    }


# -- intensity distribution ---------------------------------------------------


def intensity_distribution(activities: pl.DataFrame, hr_max: float | None = None) -> dict[str, Any]:
    """Aerobic vs anaerobic training distribution, weighted by duration.

    Each session is bucketed by its *average* HR into easy / moderate / hard
    (see ``physiology.intensity_band``), then time is summed per bucket. Reports
    the polarized-training view: elite endurance athletes spend ~80% easy and
    ~20% hard with little in the "moderate" grey zone (Seiler). A high moderate
    share is the classic "grey-zone junk miles" pattern.

    NOTE: this uses session-average HR, not per-second zone streams. The true
    time-in-zone distribution needs the activity-detail endpoint (see roadmap).
    """
    if activities.is_empty() or not {"avg_hr", "duration_s"}.issubset(activities.columns):
        return {"available": False}
    hr_max = hr_max if hr_max is not None else estimate_hr_max(activities)
    df = activities.select("avg_hr", "duration_s").drop_nulls()
    if df.is_empty():
        return {"available": False}

    minutes = {"easy": 0.0, "moderate": 0.0, "hard": 0.0}
    for row in df.iter_rows(named=True):
        avg_hr = _f(row["avg_hr"])
        dur = _f(row["duration_s"])
        if avg_hr is None or dur is None:
            continue
        minutes[intensity_band(avg_hr, hr_max)] += dur / 60.0

    total = sum(minutes.values())
    if total <= 0:
        return {"available": False}
    pct = {k: round(v / total * 100, 1) for k, v in minutes.items()}
    aerobic = round(pct["easy"], 1)
    anaerobic = round(pct["moderate"] + pct["hard"], 1)

    verdict = "polarized"
    if pct["moderate"] >= 35:
        verdict = "grey-zone-heavy"
    elif pct["easy"] < 65:
        verdict = "too-hard"
    elif pct["hard"] < 5:
        verdict = "all-easy"

    return {
        "available": True,
        "hr_max_used": round(hr_max, 0),
        "minutes": {k: round(v, 0) for k, v in minutes.items()},
        "pct": pct,
        "aerobic_pct": aerobic,
        "anaerobic_pct": anaerobic,
        "verdict": verdict,
    }
