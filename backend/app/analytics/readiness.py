"""Readiness & risk (M8): daily Red/Yellow/Green and an overtraining engine.

Two user-facing outputs:

* ``daily_readiness`` — a transparent 0-100 score with a traffic-light band and
  a ranked list of *drivers* (which signals helped or hurt today). Every
  component and weight is visible; this is deliberately not Garmin's black box.
* ``risk_flags`` — a heuristic overtraining / injury-risk engine that fires
  named, evidence-backed flags: load spikes (ACWR), HRV suppression, elevated
  resting HR, monotony, sleep-debt-vs-load mismatch, rapid fitness ramp, and
  deeply negative form.

The philosophy (per the brief): simple, well-understood rules and weighted
scoring first — accuracy and explainability over model complexity.

Pure functions over the normalized ``daily`` frame plus the training-load frame;
composes the ``engine`` and ``fitness`` primitives rather than re-deriving them.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from app.analytics import engine as ax
from app.analytics import fitness
from app.analytics.physiology import _f

# Component weights for the composite readiness score. Only the components with
# data on the latest day are used; weights are renormalized over what's present.
_WEIGHTS: dict[str, float] = {
    "hrv": 0.30,
    "resting_hr": 0.20,
    "sleep": 0.20,
    "body_battery": 0.15,
    "stress": 0.15,
}

# Traffic-light cutoffs on the final 0-100 score.
GREEN_MIN = 67.0
YELLOW_MIN = 40.0

# Each bpm that the 7-day resting HR sits above the 60-day baseline costs this
# many readiness points (and, past a threshold, raises a risk flag).
RHR_POINTS_PER_BPM = 8.0
RHR_FLAG_BPM = 3.0  # yellow
RHR_ALARM_BPM = 5.0  # red

HRV_FLAG_PCT = -8.0  # yellow: 7d HRV this far below baseline
HRV_ALARM_PCT = -12.0  # red


# -- resting HR ---------------------------------------------------------------


def resting_hr_deviation(daily: pl.DataFrame) -> pl.DataFrame:
    """7-day resting HR vs personal 60-day baseline, in bpm.

    A sustained rise of a few bpm over baseline is a classic early marker of
    accumulated fatigue, dehydration, or oncoming illness.
    """
    if daily.is_empty() or "resting_hr" not in daily.columns:
        return pl.DataFrame({"day": [], "rhr_dev_bpm": []})
    df = daily.sort("day")
    return df.with_columns(
        rhr_7d=pl.col("resting_hr").rolling_mean(7, min_samples=3),
        rhr_60d=pl.col("resting_hr").rolling_mean(60, min_samples=21),
    ).with_columns(rhr_dev_bpm=(pl.col("rhr_7d") - pl.col("rhr_60d")).round(1))


# -- sleep trend --------------------------------------------------------------


def sleep_trend(daily: pl.DataFrame) -> dict[str, Any]:
    """Recent sleep duration/score vs a longer baseline, plus nightly deficit."""
    if daily.is_empty() or "sleep_seconds" not in daily.columns:
        return {"available": False}
    df = (
        daily.sort("day")
        .select("day", "sleep_seconds", "sleep_score")
        .drop_nulls(subset=["sleep_seconds"])
    )
    if df.height < 3:
        return {"available": False}
    hours = df["sleep_seconds"] / 3600.0
    recent = _f(hours.tail(7).mean())
    baseline = _f(hours.mean())
    score_7d = _f(df["sleep_score"].drop_nulls().tail(7).mean())
    deficit = round(baseline - recent, 2) if (recent is not None and baseline is not None) else None
    return {
        "available": True,
        "recent_hours": round(recent, 2) if recent is not None else None,
        "baseline_hours": round(baseline, 2) if baseline is not None else None,
        "deficit_hours_per_night": deficit,
        "sleep_score_7d": round(score_7d, 0) if score_7d is not None else None,
    }


# -- composite readiness ------------------------------------------------------


def _clip(value: float) -> float:
    return max(0.0, min(100.0, value))


def daily_readiness(daily: pl.DataFrame, load_by_day: pl.DataFrame | None = None) -> dict[str, Any]:
    """Composite 0-100 readiness with a traffic-light band and ranked drivers.

    ``load_by_day`` (from ``engine.daily_training_load``) is optional; when
    present, a high acute:chronic ratio or deeply negative form applies a
    training-load penalty on top of the physiological signals.
    """
    if daily.is_empty():
        return {"available": False, "score": None, "band": "unknown", "drivers": []}

    last = daily.sort("day").tail(1).to_dicts()[0]
    hrv_dev = _latest(ax.hrv_baseline_deviation(daily), "hrv_dev_pct")
    rhr_dev = _latest(resting_hr_deviation(daily), "rhr_dev_bpm")

    components: dict[str, float] = {}
    if hrv_dev is not None:
        components["hrv"] = _clip(70.0 + hrv_dev * 3.0)
    if rhr_dev is not None:
        # Below baseline (negative dev) is good and tops out at 100.
        components["resting_hr"] = _clip(100.0 - max(0.0, rhr_dev) * RHR_POINTS_PER_BPM)
    if (ss := last.get("sleep_score")) is not None:
        components["sleep"] = _clip(float(ss))
    if (bb := last.get("body_battery_high")) is not None:
        components["body_battery"] = _clip(float(bb))
    if (stress := last.get("avg_stress")) is not None:
        components["stress"] = _clip(100.0 - float(stress))

    if not components:
        return {"available": False, "score": None, "band": "unknown", "drivers": []}

    weight_sum = sum(_WEIGHTS[k] for k in components)
    base = sum(components[k] * _WEIGHTS[k] for k in components) / weight_sum

    penalty, load_note = _load_penalty(load_by_day)
    score = round(_clip(base - penalty))

    band = "green" if score >= GREEN_MIN else "yellow" if score >= YELLOW_MIN else "red"
    drivers = _drivers(components)

    return {
        "available": True,
        "score": score,
        "band": band,
        "components": {k: round(v) for k, v in components.items()},
        "drivers": drivers,
        "load_penalty": round(penalty, 1),
        "load_note": load_note,
        "recommendation": _readiness_reco(band, drivers),
    }


def _latest(df: pl.DataFrame, col: str) -> float | None:
    if df.is_empty() or col not in df.columns:
        return None
    return _f(df.tail(1).to_dicts()[0].get(col))


def _load_penalty(load_by_day: pl.DataFrame | None) -> tuple[float, str | None]:
    """Subtract readiness points when acute load has spiked or form is buried."""
    if load_by_day is None or load_by_day.is_empty():
        return 0.0, None
    penalty = 0.0
    notes: list[str] = []
    acwr_df = ax.acwr(load_by_day)
    acwr_val = _latest(acwr_df, "acwr")
    if acwr_val is not None and acwr_val > 1.3:
        penalty += min(20.0, (acwr_val - 1.3) * 40.0)
        notes.append(f"acute:chronic load ratio {acwr_val:.2f}")
    tsb = _f(fitness.fitness_summary(load_by_day).get("form_tsb"))
    if tsb is not None and tsb < -25:
        penalty += min(15.0, (abs(tsb) - 25.0) * 0.6)
        notes.append(f"form (TSB) {tsb:.0f}")
    return penalty, ("; ".join(notes) if notes else None)


def _drivers(components: dict[str, float]) -> list[dict[str, Any]]:
    """Rank components worst-first so the UI/coach can lead with what hurt."""
    label = {
        "hrv": "HRV vs baseline",
        "resting_hr": "Resting HR vs baseline",
        "sleep": "Last night's sleep",
        "body_battery": "Body Battery peak",
        "stress": "Stress load",
    }
    out = []
    for key, value in sorted(components.items(), key=lambda kv: kv[1]):
        verdict = "good" if value >= 67 else "ok" if value >= 45 else "low"
        out.append({"key": key, "label": label[key], "value": round(value), "verdict": verdict})
    return out


def _readiness_reco(band: str, drivers: list[dict[str, Any]]) -> str:
    worst = drivers[0]["label"].lower() if drivers else "your recovery signals"
    if band == "green":
        return "Green light. Your body is recovered — a good day for quality or a long effort."
    if band == "yellow":
        return f"Amber. Proceed, but keep intensity moderate; {worst} is the limiter today."
    return f"Red. Prioritise recovery today — {worst} is well below your baseline."


# -- overtraining / injury risk engine ----------------------------------------


def risk_flags(
    daily: pl.DataFrame,
    activities: pl.DataFrame,
    load_by_day: pl.DataFrame | None = None,
) -> dict[str, Any]:
    """Named, evidence-backed risk flags plus an overall risk band.

    Each flag is a dict: ``code``, ``severity`` (red|yellow), ``title``,
    ``detail`` (plain-language), and ``evidence`` (the numbers behind it). This
    is a rules engine, not an ML model, on purpose — it is auditable.
    """
    flags: list[dict[str, Any]] = []
    if load_by_day is None and not activities.is_empty():
        load_by_day = ax.daily_training_load(activities)

    # 1. Load spike — acute:chronic workload ratio.
    if load_by_day is not None and not load_by_day.is_empty():
        acwr_val = _latest(ax.acwr(load_by_day), "acwr")
        if acwr_val is not None:
            if acwr_val >= 1.5:
                flags.append(
                    _flag(
                        "LOAD_SPIKE",
                        "red",
                        "Training load is spiking",
                        f"Your 7-day load is {acwr_val:.2f}x your 28-day baseline "
                        "(>=1.5 is the high-injury-risk zone). Insert an easier day or two.",
                        {"acwr": acwr_val},
                    )
                )
            elif acwr_val >= 1.3:
                flags.append(
                    _flag(
                        "LOAD_SPIKE",
                        "yellow",
                        "Load ramping above the sweet spot",
                        f"Acute:chronic ratio {acwr_val:.2f} (sweet spot 0.8-1.3). "
                        "Fine short-term, but don't stack more hard days on top.",
                        {"acwr": acwr_val},
                    )
                )

        # 2. Monotony — same load every day.
        mono = ax.monotony(load_by_day)
        mono_val = _latest(mono, "monotony")
        mean_val = _latest(mono, "mean")
        if mono_val is not None and mono_val >= 2.0 and (mean_val or 0) > 0:
            flags.append(
                _flag(
                    "MONOTONY",
                    "yellow",
                    "Training is too monotonous",
                    f"Weekly monotony {mono_val:.1f} (>2.0). Every day looks the same; "
                    "add genuine easy days so hard days can be hard.",
                    {"monotony": mono_val},
                )
            )

        # 6. Rapid fitness ramp.
        summary = fitness.fitness_summary(load_by_day)
        ramp = _f(summary.get("ramp_7d"))
        if ramp is not None and ramp > fitness.AGGRESSIVE_RAMP_PER_WEEK:
            flags.append(
                _flag(
                    "RAPID_RAMP",
                    "yellow",
                    "Fitness is ramping fast",
                    f"Your Fitness (CTL) rose {ramp:.1f} in 7 days "
                    f"(>{fitness.AGGRESSIVE_RAMP_PER_WEEK:.0f}/wk is aggressive). "
                    "Great progress, but a common precursor to overuse injury.",
                    {"ramp_7d": ramp},
                )
            )

        # 7. Deeply negative form.
        tsb = _f(summary.get("form_tsb"))
        if tsb is not None and tsb < -30:
            flags.append(
                _flag(
                    "DEEP_FATIGUE",
                    "red",
                    "Form is deeply negative",
                    f"Training Stress Balance {tsb:.0f} (below -30). You are heavily "
                    "fatigued; schedule recovery before it turns non-functional.",
                    {"form_tsb": tsb},
                )
            )

    # 3. HRV suppression.
    hrv_dev = _latest(ax.hrv_baseline_deviation(daily), "hrv_dev_pct")
    if hrv_dev is not None:
        if hrv_dev <= HRV_ALARM_PCT:
            flags.append(
                _flag(
                    "HRV_SUPPRESSION",
                    "red",
                    "HRV is suppressed",
                    f"7-day HRV is {abs(hrv_dev):.0f}% below your 60-day baseline "
                    "(<=12% is a strong fatigue/illness signal). Take an easy day.",
                    {"hrv_dev_pct": hrv_dev},
                )
            )
        elif hrv_dev <= HRV_FLAG_PCT:
            flags.append(
                _flag(
                    "HRV_SUPPRESSION",
                    "yellow",
                    "HRV dipping below baseline",
                    f"7-day HRV is {abs(hrv_dev):.0f}% below baseline — an early sign of "
                    "accumulated fatigue.",
                    {"hrv_dev_pct": hrv_dev},
                )
            )

    # 4. Elevated resting HR.
    rhr_dev = _latest(resting_hr_deviation(daily), "rhr_dev_bpm")
    if rhr_dev is not None:
        if rhr_dev >= RHR_ALARM_BPM:
            flags.append(
                _flag(
                    "RHR_ELEVATED",
                    "red",
                    "Resting HR is elevated",
                    f"Your 7-day resting HR is {rhr_dev:.0f} bpm above baseline "
                    "(>=5 bpm often precedes illness or marks deep fatigue).",
                    {"rhr_dev_bpm": rhr_dev},
                )
            )
        elif rhr_dev >= RHR_FLAG_BPM:
            flags.append(
                _flag(
                    "RHR_ELEVATED",
                    "yellow",
                    "Resting HR creeping up",
                    f"7-day resting HR {rhr_dev:.0f} bpm over baseline. Watch recovery.",
                    {"rhr_dev_bpm": rhr_dev},
                )
            )

    # 5. Sleep debt colliding with training load.
    st = sleep_trend(daily)
    deficit = st.get("deficit_hours_per_night") if st.get("available") else None
    acwr_recent = (
        _latest(ax.acwr(load_by_day), "acwr")
        if load_by_day is not None and not load_by_day.is_empty()
        else None
    )
    if deficit is not None and deficit >= 0.75 and acwr_recent is not None and acwr_recent >= 1.1:
        flags.append(
            _flag(
                "SLEEP_LOAD_MISMATCH",
                "yellow",
                "Under-sleeping while loading up",
                f"You're averaging {deficit:.1f} h/night below your own baseline while "
                f"training load is rising (ACWR {acwr_recent:.2f}). Recovery can't keep up "
                "with intensity — protect sleep or ease the load.",
                {"sleep_deficit_h": deficit, "acwr": acwr_recent},
            )
        )

    band = "red" if any(f["severity"] == "red" for f in flags) else ("yellow" if flags else "green")
    return {"risk_band": band, "flag_count": len(flags), "flags": flags}


def _flag(
    code: str, severity: str, title: str, detail: str, evidence: dict[str, Any]
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "title": title,
        "detail": detail,
        "evidence": {k: round(v, 2) if isinstance(v, float) else v for k, v in evidence.items()},
    }
