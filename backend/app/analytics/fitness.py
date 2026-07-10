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
from datetime import timedelta
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


_ZONE_COLS = ("zone_1_s", "zone_2_s", "zone_3_s", "zone_4_s", "zone_5_s")


def intensity_distribution(activities: pl.DataFrame, hr_max: float | None = None) -> dict[str, Any]:
    """Easy / moderate / hard training distribution, weighted by real time in zone.

    Sessions with Garmin's per-zone seconds (``zone_1_s``..``zone_5_s``, Phase
    1b) contribute their true time-in-zone: Z1-2 -> easy, Z3 -> moderate,
    Z4-5 -> hard — so an "easy" run's tempo surges are counted honestly.
    Sessions without zone data fall back to bucketing by session-average HR
    (``physiology.intensity_band``). Reports the polarized-training view:
    elite endurance practice is ~80% easy / ~20% hard with little grey-zone
    middle (Seiler); a high moderate share is the classic junk-miles pattern.
    """
    if activities.is_empty() or "duration_s" not in activities.columns:
        return {"available": False}
    hr_max = hr_max if hr_max is not None else estimate_hr_max(activities)
    has_zone_cols = set(_ZONE_COLS).issubset(activities.columns)

    minutes = {"easy": 0.0, "moderate": 0.0, "hard": 0.0}
    zone_minutes = {f"z{i}": 0.0 for i in range(1, 6)}
    zoned_sessions = 0
    fallback_sessions = 0
    for row in activities.iter_rows(named=True):
        zones = [_f(row.get(c)) or 0.0 for c in _ZONE_COLS] if has_zone_cols else []
        if sum(zones) > 0:
            minutes["easy"] += (zones[0] + zones[1]) / 60.0
            minutes["moderate"] += zones[2] / 60.0
            minutes["hard"] += (zones[3] + zones[4]) / 60.0
            for i, seconds in enumerate(zones):
                zone_minutes[f"z{i + 1}"] += seconds / 60.0
            zoned_sessions += 1
            continue
        avg_hr = _f(row.get("avg_hr"))
        dur = _f(row.get("duration_s"))
        if avg_hr is None or dur is None:
            continue
        minutes[intensity_band(avg_hr, hr_max)] += dur / 60.0
        fallback_sessions += 1

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

    method = (
        "time_in_zone"
        if zoned_sessions and not fallback_sessions
        else "session_avg"
        if fallback_sessions and not zoned_sessions
        else "mixed"
    )
    return {
        "available": True,
        "hr_max_used": round(hr_max, 0),
        "method": method,
        "minutes": {k: round(v, 0) for k, v in minutes.items()},
        "zone_minutes": {k: round(v, 0) for k, v in zone_minutes.items()},
        "pct": pct,
        "aerobic_pct": aerobic,
        "anaerobic_pct": anaerobic,
        "verdict": verdict,
    }


_RACE_COLS = ("time_5k_s", "time_10k_s", "time_half_s", "time_marathon_s")


def race_prediction_trend(preds: pl.DataFrame, baseline_days: int = 30) -> dict[str, Any]:
    """Garmin's race-time predictions: latest values, deltas, and the full series.

    ``preds`` is the ``race_predictions`` frame (one row per day). Deltas
    compare the latest row against a baseline — the newest row at least
    ``baseline_days`` older, else the oldest available — so a thin history
    still yields an honest comparison; ``baseline_span_days`` says how far back
    it actually reached. Negative delta = the predicted time got faster.
    """
    if preds.is_empty():
        return {"available": False}
    df = preds.sort("day")
    last = df.tail(1).to_dicts()[0]
    older = df.filter(pl.col("day") <= last["day"] - timedelta(days=baseline_days))
    base = (older.tail(1) if not older.is_empty() else df.head(1)).to_dicts()[0]

    deltas: dict[str, int | None] = {}
    for col in _RACE_COLS:
        latest_s, base_s = _f(last.get(col)), _f(base.get(col))
        deltas[col] = (
            round(latest_s - base_s) if latest_s is not None and base_s is not None else None
        )

    return {
        "available": True,
        "as_of": str(last["day"]),
        "baseline_day": str(base["day"]),
        "baseline_span_days": (last["day"] - base["day"]).days,
        "latest": {c: last.get(c) for c in _RACE_COLS},
        "deltas_s": deltas,
        "series": df.to_dicts(),
    }


# Load Focus buckets in Garmin's display order, with the DailyMetrics column
# stems they were normalized into.
_FOCUS_BUCKETS = (
    ("anaerobic", "Anaerobic", "load_anaerobic"),
    ("aerobic_high", "High aerobic", "load_aerobic_high"),
    ("aerobic_low", "Low aerobic", "load_aerobic_low"),
)


def garmin_load_focus(daily: pl.DataFrame) -> dict[str, Any]:
    """Garmin's Load Focus + Training Status verdicts, straight from the watch.

    A labeled cross-check next to our own load model (like
    ``garmin_training_readiness`` in the readiness output): the 4-week load in
    Garmin's anaerobic / high-aerobic / low-aerobic buckets against its
    personalized target ranges, each graded below/within/above, plus the
    training-status feedback phrase (e.g. "UNPRODUCTIVE_5" -> "Unproductive").
    """
    if daily.is_empty() or "load_aerobic_low" not in daily.columns:
        return {"available": False}
    rows = daily.sort("day").filter(pl.col("load_aerobic_low").is_not_null())
    status_rows = (
        daily.sort("day").filter(pl.col("training_status").is_not_null())
        if "training_status" in daily.columns
        else pl.DataFrame()
    )
    status = status_rows.tail(1).to_dicts()[0] if not status_rows.is_empty() else {}
    if rows.is_empty():
        return {
            "available": bool(status),
            "as_of": str(status["day"]) if status else None,
            "status": _status_phrase(status.get("training_status")),
            "balance_phrase": None,
            "focus": [],
        }
    last = rows.tail(1).to_dicts()[0]

    focus = []
    for key, label, stem in _FOCUS_BUCKETS:
        load = _f(last.get(stem))
        lo = _f(last.get(f"{stem}_target_min"))
        hi = _f(last.get(f"{stem}_target_max"))
        verdict = None
        if load is not None and lo is not None and hi is not None:
            verdict = "below" if load < lo else "above" if load > hi else "within"
        focus.append(
            {
                "key": key,
                "label": label,
                "load": round(load, 0) if load is not None else None,
                "target_min": lo,
                "target_max": hi,
                "verdict": verdict,
            }
        )

    return {
        "available": True,
        "as_of": str(last["day"]),
        "status": _status_phrase(status.get("training_status")),
        "balance_phrase": _status_phrase(last.get("load_balance_phrase")),
        "focus": focus,
    }


def _status_phrase(raw: Any) -> str | None:
    """ "UNPRODUCTIVE_5" / "BALANCED" -> "Unproductive" / "Balanced"."""
    if not raw:
        return None
    words = [w for w in str(raw).split("_") if w and not w.isdigit()]
    return " ".join(words).capitalize() if words else None
