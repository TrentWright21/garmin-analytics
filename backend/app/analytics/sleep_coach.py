"""Sleep coach (M7). A science-backed, personalized sleep analyst.

Pure Polars over the normalized ``daily_metrics`` frame — no DB access, no side
effects — so every function is unit-testable with synthetic nights.

What it does that Garmin's app does not:

* Estimates Trent's **personal sleep need** empirically, by finding the sleep
  duration that actually precedes his best next-day recovery (HRV, resting HR,
  Body Battery, stress) — not a generic "8 hours".
* Scores **regularity** the way the sleep-science literature does (bedtime and
  wake-time variability, social jetlag, a Sleep Regularity Index proxy). Timing
  consistency is one of the strongest predictors of sleep quality and daytime
  function (Phillips et al., 2017; AASM consistency guidance).
* Grades **stage architecture** against adult reference ranges (deep/N3 ~13-23%,
  REM ~20-25%, light ~50-60%; efficiency >=85%).
* Tracks **sleep debt** as a rolling 14-night deficit against that personal need.
* Correlates sleep against recovery so recommendations are grounded in *his* data.

References are cited inline so recommendations are transparent, not a black box.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl

# -- science reference ranges (adults) ---------------------------------------
# Percent of total sleep time. Sources: AASM / Sleep Foundation consensus ranges.
DEEP_REF = (13.0, 23.0)
REM_REF = (20.0, 25.0)
LIGHT_REF = (50.0, 63.0)
EFFICIENCY_GOOD = 85.0
# National Sleep Foundation recommended adult range (Hirshkowitz et al., 2015).
NEED_FLOOR, NEED_CEIL = 7.0, 9.0
DEFAULT_NEED = 8.0
# Bedtime/wake standard deviation, in minutes, considered "consistent".
CONSISTENCY_GOOD_MIN = 30.0
CONSISTENCY_OK_MIN = 60.0

# The recovery signals used to estimate personal sleep need. Sign = "higher is
# better", so resting HR and stress are inverted before averaging.
_RECOVERY_SIGNALS: dict[str, int] = {
    "hrv_last_night_avg": +1,
    "body_battery_high": +1,
    "resting_hr": -1,
    "avg_stress": -1,
}


# -- small pure helpers ------------------------------------------------------


def _f(value: Any) -> float | None:
    """Coerce a Polars scalar (union-typed under mypy strict) to float | None."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: float | None, ndigits: int = 1) -> float | None:
    return None if value is None else round(value, ndigits)


# Sleep-time statistics anchor to 18:00 so an overnight window (evening -> next
# noon) is a single monotonic range with no midnight wrap. All bedtime/wake/
# midpoint values are stored as "minutes since 18:00"; convert back for display.
_ANCHOR_MIN = 18 * 60


def _minutes_to_clock(minutes: float | None) -> str | None:
    """A minutes-from-midnight value (may be negative = previous evening) -> HH:MM."""
    if minutes is None:
        return None
    m = round(minutes) % (24 * 60)
    return f"{m // 60:02d}:{m % 60:02d}"


def _anchored_clock(anchored: float | None) -> str | None:
    """An 'anchored to 18:00' value -> wall-clock HH:MM."""
    return None if anchored is None else _minutes_to_clock(anchored + _ANCHOR_MIN)


def _letter(score: float | None) -> str:
    if score is None:
        return "-"
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def _status(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= 80:
        return "good"
    if score >= 60:
        return "watch"
    return "alert"


# -- frame preparation -------------------------------------------------------


def sleep_frame(daily: pl.DataFrame) -> pl.DataFrame:
    """Derive per-night sleep features from the daily metrics frame.

    Adds duration/stage percentages, efficiency, clock-anchored bedtime and
    wake-time (in minutes, evening hours expressed as negative so the axis does
    not wrap at midnight), sleep midpoint, and a recovery index (z-scored blend
    of HRV / Body Battery / inverse resting-HR / inverse stress).
    """
    needed = {"day", "sleep_seconds"}
    if daily.is_empty() or not needed.issubset(daily.columns):
        return pl.DataFrame()

    df = daily.sort("day").filter(pl.col("sleep_seconds").is_not_null())
    if df.is_empty():
        return df

    for col in ("deep_seconds", "light_seconds", "rem_seconds", "awake_seconds"):
        if col not in df.columns:
            df = df.with_columns(pl.lit(None, dtype=pl.Int64).alias(col))

    df = df.with_columns(
        sleep_hours=(pl.col("sleep_seconds") / 3600.0).round(2),
        deep_pct=(pl.col("deep_seconds") / pl.col("sleep_seconds") * 100).round(1),
        rem_pct=(pl.col("rem_seconds") / pl.col("sleep_seconds") * 100).round(1),
        light_pct=(pl.col("light_seconds") / pl.col("sleep_seconds") * 100).round(1),
        awake_pct=(
            pl.col("awake_seconds")
            / (pl.col("sleep_seconds") + pl.col("awake_seconds").fill_null(0))
            * 100
        ).round(1),
        efficiency=(
            pl.col("sleep_seconds")
            / (pl.col("sleep_seconds") + pl.col("awake_seconds").fill_null(0))
            * 100
        ).round(1),
        weekday=pl.col("day").dt.weekday(),  # 1=Mon .. 7=Sun
    )

    # Bedtime / wake-time as minutes-since-18:00 (see _ANCHOR_MIN). This keeps a
    # 22:00 bedtime (240) and a 01:00 bedtime (420) adjacent instead of a day apart.
    def _anchored(col: str) -> pl.Expr:
        # Cast hour/minute out of Int8 first: dt.hour() is Int8 and hour*60
        # (e.g. 22*60=1320) overflows int8, silently corrupting the minutes.
        hour = pl.col(col).dt.hour().cast(pl.Int32)
        minute = pl.col(col).dt.minute().cast(pl.Int32)
        return ((hour * 60 + minute - _ANCHOR_MIN + 24 * 60) % (24 * 60)).cast(pl.Float64)

    if "sleep_start_local" in df.columns:
        df = df.with_columns(bedtime_min=_anchored("sleep_start_local"))
    else:
        df = df.with_columns(bedtime_min=pl.lit(None, dtype=pl.Float64))

    if "sleep_end_local" in df.columns:
        df = df.with_columns(waketime_min=_anchored("sleep_end_local"))
    else:
        df = df.with_columns(waketime_min=pl.lit(None, dtype=pl.Float64))

    df = df.with_columns(midpoint_min=(pl.col("bedtime_min") + pl.col("waketime_min")) / 2)

    # Recovery index: mean of available z-scored recovery signals.
    z_terms: list[pl.Expr] = []
    for col, sign in _RECOVERY_SIGNALS.items():
        if col in df.columns:
            mean = _f(df[col].mean())
            std = _f(df[col].std())
            if mean is not None and std is not None and std > 0:
                z_terms.append(((pl.col(col) - mean) / std * sign).alias(f"_z_{col}"))
    if z_terms:
        df = df.with_columns(z_terms)
        zcols = [t.meta.output_name() for t in z_terms]
        df = df.with_columns(recovery_index=pl.mean_horizontal(zcols).round(3))
    else:
        df = df.with_columns(recovery_index=pl.lit(None, dtype=pl.Float64))

    return df


# -- personal sleep need -----------------------------------------------------


def sleep_need(frame: pl.DataFrame) -> dict[str, Any]:
    """Estimate personal nightly sleep need from recovery-vs-duration evidence.

    Buckets nights by duration and finds which bucket precedes the best average
    recovery index. Honest about method and confidence: with few nights it falls
    back to the population default (8 h) and says so.
    """
    fallback = {
        "estimate_hours": DEFAULT_NEED,
        "method": "default",
        "confidence": "low",
        "buckets": [],
        "note": (
            "Not enough nights with recovery signals yet — using the population "
            f"default of {DEFAULT_NEED:.0f} h. This personalizes as history grows "
            "(a full-year backfill sharpens it considerably)."
        ),
    }
    if frame.is_empty() or "recovery_index" not in frame.columns:
        return fallback
    usable = frame.select("sleep_hours", "recovery_index").drop_nulls()
    if usable.height < 14:
        return fallback

    edges = [0.0, 6.0, 6.5, 7.0, 7.5, 8.0, 8.5, 9.0, 99.0]
    labels = ["<6h", "6-6.5h", "6.5-7h", "7-7.5h", "7.5-8h", "8-8.5h", "8.5-9h", "9h+"]
    mids = [5.75, 6.25, 6.75, 7.25, 7.75, 8.25, 8.75, 9.25]
    bucketed = usable.with_columns(bucket=pl.col("sleep_hours").cut(edges[1:-1], labels=labels))
    agg = (
        bucketed.group_by("bucket")
        .agg(
            avg_recovery=pl.col("recovery_index").mean().round(3),
            nights=pl.len(),
        )
        .sort("bucket")
    )
    buckets = []
    best_mid: float | None = None
    best_recovery: float | None = None
    for row in agg.iter_rows(named=True):
        label = row["bucket"]
        if label not in labels:
            continue
        mid = mids[labels.index(label)]
        rec = row["avg_recovery"]
        nights = int(row["nights"])
        buckets.append({"range": label, "avg_recovery": rec, "nights": nights})
        # Only trust buckets with >=3 nights for the "best" pick.
        if nights >= 3 and rec is not None and (best_recovery is None or rec > best_recovery):
            best_recovery = rec
            best_mid = mid

    if best_mid is None:
        return {**fallback, "buckets": buckets}

    estimate = min(NEED_CEIL, max(NEED_FLOOR, best_mid))
    confidence = "high" if usable.height >= 45 else "moderate"
    return {
        "estimate_hours": round(estimate, 1),
        "method": "recovery-optimized",
        "confidence": confidence,
        "buckets": buckets,
        "note": (
            f"Your best next-day recovery clusters around the {_minutes_to_clock(estimate * 60)} "
            f"band — i.e. about {estimate:.1f} h. That's your personal target, derived "
            f"from {usable.height} nights of HRV / resting-HR / Body-Battery evidence."
        ),
    }


# -- regularity / timing -----------------------------------------------------


def regularity(frame: pl.DataFrame) -> dict[str, Any]:
    """Bedtime & wake-time variability, social jetlag, and a consistency score.

    Timing regularity independently predicts sleep quality, metabolic and mood
    outcomes (Phillips et al., Sci Rep 2017). Lower variability is better.
    """
    empty = {
        "bedtime_sd_min": None,
        "waketime_sd_min": None,
        "social_jetlag_min": None,
        "avg_bedtime": None,
        "avg_waketime": None,
        "score": None,
        "note": "No bedtime/wake timestamps available yet.",
    }
    if frame.is_empty() or "bedtime_min" not in frame.columns:
        return empty
    recent = frame.tail(30)
    bed = recent["bedtime_min"].drop_nulls()
    wake = recent["waketime_min"].drop_nulls()
    if bed.len() < 5 or wake.len() < 5:
        return empty

    bed_sd = _f(bed.std())
    wake_sd = _f(wake.std())
    avg_bed = _f(bed.mean())
    avg_wake = _f(wake.mean())

    # Social jetlag: weekend vs weekday sleep midpoint shift.
    wk = recent.filter(pl.col("weekday") <= 5)["midpoint_min"].drop_nulls()
    we = recent.filter(pl.col("weekday") >= 6)["midpoint_min"].drop_nulls()
    we_mid, wk_mid = _f(we.mean()), _f(wk.mean())
    social_jetlag = (
        abs(we_mid - wk_mid)
        if we.len() >= 2 and wk.len() >= 2 and we_mid is not None and wk_mid is not None
        else None
    )

    # Score: 100 at 0 min SD, ~70 at the "good" threshold, 0 by ~2h combined SD.
    combined_sd = ((bed_sd or 0) + (wake_sd or 0)) / 2
    score = max(0.0, min(100.0, 100.0 - (combined_sd / CONSISTENCY_GOOD_MIN) * 30.0))

    tips = []
    if bed_sd and bed_sd > CONSISTENCY_OK_MIN:
        tips.append(f"your bedtime swings ±{bed_sd:.0f} min")
    if wake_sd and wake_sd > CONSISTENCY_OK_MIN:
        tips.append(f"your wake time swings ±{wake_sd:.0f} min")
    if social_jetlag and social_jetlag > 60:
        tips.append(f"weekends drift {social_jetlag:.0f} min later ('social jetlag')")
    note = (
        "Rock-solid timing — keep it up."
        if not tips
        else "Regularity is the single biggest lever here: " + "; ".join(tips) + "."
    )

    return {
        "bedtime_sd_min": _round(bed_sd, 0),
        "waketime_sd_min": _round(wake_sd, 0),
        "social_jetlag_min": _round(social_jetlag, 0),
        "avg_bedtime": _anchored_clock(avg_bed),
        "avg_waketime": _anchored_clock(avg_wake),
        "score": round(score),
        "note": note,
    }


# -- stage architecture ------------------------------------------------------


def stages(frame: pl.DataFrame) -> dict[str, Any]:
    """Average stage composition vs adult reference ranges, with grades."""
    if frame.is_empty():
        return {}
    recent = frame.tail(30)

    def avg(col: str) -> float | None:
        return _round(_f(recent[col].mean()), 1) if col in recent.columns else None

    deep = avg("deep_pct")
    rem = avg("rem_pct")
    light = avg("light_pct")
    awake = avg("awake_pct")
    eff = avg("efficiency")

    def band_score(value: float | None, lo: float, hi: float) -> float | None:
        if value is None:
            return None
        if lo <= value <= hi:
            return 100.0
        gap = lo - value if value < lo else value - hi
        return max(0.0, 100.0 - gap * 8.0)  # ~8 pts per percentage-point outside

    return {
        "deep_pct": deep,
        "rem_pct": rem,
        "light_pct": light,
        "awake_pct": awake,
        "efficiency": eff,
        "ref": {
            "deep": list(DEEP_REF),
            "rem": list(REM_REF),
            "light": list(LIGHT_REF),
            "efficiency_good": EFFICIENCY_GOOD,
        },
        "deep_score": band_score(deep, *DEEP_REF),
        "rem_score": band_score(rem, *REM_REF),
        "efficiency_score": None if eff is None else max(0.0, min(100.0, (eff - 70) * 5)),
    }


# -- sleep debt --------------------------------------------------------------


def sleep_debt(frame: pl.DataFrame, need_hours: float, window: int = 14) -> dict[str, Any]:
    """Rolling deficit against personal need over the last ``window`` nights."""
    if frame.is_empty() or "sleep_hours" not in frame.columns:
        return {"rolling_hours": None, "per_night": []}
    recent = frame.tail(window).select("day", "sleep_hours").drop_nulls()
    per_night = []
    total_deficit = 0.0
    for row in recent.iter_rows(named=True):
        actual = float(row["sleep_hours"])
        balance = round(actual - need_hours, 2)
        if balance < 0:
            total_deficit += -balance
        per_night.append(
            {"day": str(row["day"]), "actual": actual, "need": need_hours, "balance": balance}
        )
    return {"rolling_hours": round(total_deficit, 1), "per_night": per_night}


# -- correlations ------------------------------------------------------------


def _interpret(r: float, x_label: str, y_label: str, higher_y_better: bool) -> str:
    strength = (
        "a strong"
        if abs(r) >= 0.5
        else "a moderate"
        if abs(r) >= 0.3
        else "a weak"
        if abs(r) >= 0.15
        else "no meaningful"
    )
    if abs(r) < 0.15:
        return f"No meaningful link between {x_label} and {y_label} in your data."
    good = (r > 0) == higher_y_better
    direction = "improves" if good else "worsens"
    return f"More {x_label} {direction} your {y_label} ({strength} correlation, r={r:+.2f})."


def correlations(frame: pl.DataFrame) -> list[dict[str, Any]]:
    """Pearson correlations of sleep inputs against next-day recovery signals."""
    if frame.is_empty():
        return []
    pairs = [
        ("sleep_hours", "hrv_last_night_avg", "sleep", "overnight HRV", True),
        ("sleep_hours", "resting_hr", "sleep", "resting heart rate", False),
        ("sleep_hours", "body_battery_high", "sleep", "Body Battery peak", True),
        ("sleep_hours", "training_readiness", "sleep", "training readiness", True),
        ("sleep_hours", "avg_stress", "sleep", "daytime stress", False),
        ("efficiency", "hrv_last_night_avg", "sleep efficiency", "overnight HRV", True),
    ]
    out: list[dict[str, Any]] = []
    for x, y, xl, yl, better in pairs:
        if x not in frame.columns or y not in frame.columns:
            continue
        sub = frame.select(x, y).drop_nulls()
        if sub.height < 12:
            continue
        r = sub.select(pl.corr(x, y)).item()
        if r is None:
            continue
        out.append(
            {
                "x": x,
                "y": y,
                "r": round(float(r), 2),
                "n": sub.height,
                "interpretation": _interpret(float(r), xl, yl, better),
            }
        )
    # Strongest links first.
    out.sort(key=lambda d: abs(d["r"]), reverse=True)
    return out


# -- prescription, grades, recommendations -----------------------------------


def _prescription(frame: pl.DataFrame, need_hours: float, reg: dict[str, Any]) -> dict[str, Any]:
    """Concrete bedtime/wake targets from median wake-time and personal need."""
    wake_med = (
        _f(frame["waketime_min"].drop_nulls().median()) if "waketime_min" in frame.columns else None
    )
    # Anchored fallback: 06:30 wake -> (390 - 1080 + 1440) % 1440 = 750.
    target_wake = 750.0 if wake_med is None else wake_med
    target_bed = target_wake - need_hours * 60
    return {
        "target_sleep_hours": round(need_hours, 1),
        "target_bedtime": _anchored_clock(target_bed),
        "target_waketime": _anchored_clock(target_wake),
        "consistency_target_min": int(CONSISTENCY_GOOD_MIN),
        "rationale": (
            f"Aim for ~{need_hours:.1f} h in bed, lights out near "
            f"{_anchored_clock(target_bed)} and up near {_anchored_clock(target_wake)}, "
            f"the same time (±{int(CONSISTENCY_GOOD_MIN)} min) every day — weekends included."
        ),
    }


def _recommendations(
    frame: pl.DataFrame,
    dims: list[dict[str, Any]],
    reg: dict[str, Any],
    st: dict[str, Any],
    debt: dict[str, Any],
    need_hours: float,
) -> list[dict[str, Any]]:
    """Prioritized, science-cited, Trent-specific coaching actions."""
    recs: list[dict[str, Any]] = []

    # Weakest graded dimensions drive the priority order.
    for dim in sorted(dims, key=lambda d: (d["score"] is None, d["score"] or 0)):
        if dim["score"] is not None and dim["score"] >= 80:
            continue
        key = dim["key"]
        if key == "duration":
            recs.append(
                {
                    "priority": len(recs) + 1,
                    "title": f"Add sleep — you're short of your {need_hours:.1f} h need",
                    "detail": (
                        f"Your recent average is {dim['value']} h. Closing that gap is the "
                        "highest-yield change: even one extra 30-min block moves HRV and "
                        "next-day readiness in your own data."
                    ),
                    "science": "Sleep extension improves reaction time & recovery (Mah 2011).",
                }
            )
        elif key == "consistency":
            recs.append(
                {
                    "priority": len(recs) + 1,
                    "title": "Anchor your wake time 7 days a week",
                    "detail": (
                        f"{reg.get('note', '')} A fixed wake time stabilizes your circadian "
                        "clock faster than a fixed bedtime — set one alarm, weekends too."
                    ),
                    "science": "Regular timing beats duration alone (Phillips 2017).",
                }
            )
        elif key == "deep":
            recs.append(
                {
                    "priority": len(recs) + 1,
                    "title": "Protect deep sleep — it's your physical-recovery stage",
                    "detail": (
                        f"Deep is {st.get('deep_pct')}% vs a "
                        f"{DEEP_REF[0]:.0f}-{DEEP_REF[1]:.0f}% target. Deep sleep drives muscle "
                        "repair and adaptation — it matters directly for your run training and "
                        "Whitney prep. Cool, dark room; keep alcohol and late hard efforts down."
                    ),
                    "science": "Slow-wave sleep is when tissue repair peaks (Van Cauter).",
                }
            )
        elif key == "rem":
            recs.append(
                {
                    "priority": len(recs) + 1,
                    "title": "Grow REM by sleeping longer in the morning window",
                    "detail": (
                        f"REM is {st.get('rem_pct')}% vs a "
                        f"{REM_REF[0]:.0f}-{REM_REF[1]:.0f}% target. REM concentrates in the last "
                        "third of the night, so cutting sleep short costs REM first. Alcohol "
                        "suppresses it — that's your biggest lever."
                    ),
                    "science": "REM aids motor-skill consolidation & mood regulation (Walker).",
                }
            )
        elif key == "efficiency":
            recs.append(
                {
                    "priority": len(recs) + 1,
                    "title": "Tighten sleep efficiency",
                    "detail": (
                        f"Efficiency is {st.get('efficiency')}% "
                        f"(target >= {EFFICIENCY_GOOD:.0f}%). Reserve the bed for sleep, keep the "
                        "room <20°C / 68°F — relevant given Hartselle summers — and get morning "
                        "daylight to sharpen sleep pressure."
                    ),
                    "science": "Stimulus control & cool temp raise efficiency (AASM CBT-I).",
                }
            )

    if debt.get("rolling_hours") and debt["rolling_hours"] >= 3:
        recs.insert(
            0,
            {
                "priority": 0,
                "title": f"You're carrying {debt['rolling_hours']} h of 2-week sleep debt",
                "detail": (
                    "Repay it gradually — an extra 30-45 min per night beats one long "
                    "weekend catch-up, which just deepens the social-jetlag problem."
                ),
                "science": "Recovery sleep only partly repays sleep debt (Van Dongen 2003).",
            },
        )

    if not recs:
        recs.append(
            {
                "priority": 1,
                "title": "Your sleep is dialed in — hold the line",
                "detail": (
                    "Duration, timing, and architecture all look strong. Keep the routine "
                    "steady through your training block."
                ),
                "science": "",
            }
        )
    for i, r in enumerate(recs, 1):
        r["priority"] = i
    return recs


def _dimensions(
    frame: pl.DataFrame, need_hours: float, reg: dict[str, Any], st: dict[str, Any]
) -> list[dict[str, Any]]:
    recent = frame.tail(30)
    avg_hours = (
        _round(_f(recent["sleep_hours"].mean()), 1) if "sleep_hours" in recent.columns else None
    )

    duration_score: float | None = None
    if avg_hours is not None:
        deficit = max(0.0, need_hours - avg_hours)
        duration_score = max(0.0, 100.0 - deficit * 25.0)  # -25 per hour short

    dims: list[dict[str, Any]] = [
        {
            "key": "duration",
            "label": "Duration",
            "value": avg_hours,
            "target": round(need_hours, 1),
            "unit": "h",
            "score": None if duration_score is None else round(duration_score),
        },
        {
            "key": "consistency",
            "label": "Consistency",
            "value": reg.get("bedtime_sd_min"),
            "target": int(CONSISTENCY_GOOD_MIN),
            "unit": "min SD",
            "score": reg.get("score"),
        },
        {
            "key": "deep",
            "label": "Deep sleep",
            "value": st.get("deep_pct"),
            "target": f"{DEEP_REF[0]:.0f}-{DEEP_REF[1]:.0f}",
            "unit": "%",
            "score": None if st.get("deep_score") is None else round(st["deep_score"]),
        },
        {
            "key": "rem",
            "label": "REM sleep",
            "value": st.get("rem_pct"),
            "target": f"{REM_REF[0]:.0f}-{REM_REF[1]:.0f}",
            "unit": "%",
            "score": None if st.get("rem_score") is None else round(st["rem_score"]),
        },
        {
            "key": "efficiency",
            "label": "Efficiency",
            "value": st.get("efficiency"),
            "target": f">={EFFICIENCY_GOOD:.0f}",
            "unit": "%",
            "score": None if st.get("efficiency_score") is None else round(st["efficiency_score"]),
        },
    ]
    for d in dims:
        d["letter"] = _letter(d["score"])
        d["status"] = _status(d["score"])
    return dims


def _series(frame: pl.DataFrame) -> list[dict[str, Any]]:
    """Compact per-night records for the interactive charts."""
    cols = [
        "day",
        "sleep_hours",
        "sleep_score",
        "deep_pct",
        "rem_pct",
        "light_pct",
        "awake_pct",
        "efficiency",
        "bedtime_min",
        "waketime_min",
        "midpoint_min",
        "hrv_last_night_avg",
        "resting_hr",
        "training_readiness",
        "body_battery_high",
        "avg_stress",
    ]
    present = [c for c in cols if c in frame.columns]
    out = []
    for row in frame.select(present).iter_rows(named=True):
        rec = {k: (str(v) if isinstance(v, date) else v) for k, v in row.items()}
        rec["bedtime_clock"] = _anchored_clock(row.get("bedtime_min"))
        rec["waketime_clock"] = _anchored_clock(row.get("waketime_min"))
        out.append(rec)
    return out


def coach_report(daily: pl.DataFrame) -> dict[str, Any]:
    """The full sleep-coach payload the dashboard renders."""
    frame = sleep_frame(daily)
    if frame.is_empty():
        return {"available": False, "reason": "No sleep data yet — run a sync/backfill first."}

    need = sleep_need(frame)
    need_hours = float(need["estimate_hours"])
    reg = regularity(frame)
    st = stages(frame)
    debt = sleep_debt(frame, need_hours)
    dims = _dimensions(frame, need_hours, reg, st)
    corr = correlations(frame)
    presc = _prescription(frame, need_hours, reg)
    recs = _recommendations(frame, dims, reg, st, debt, need_hours)

    scored = [d["score"] for d in dims if d["score"] is not None]
    overall = round(sum(scored) / len(scored)) if scored else None

    return {
        "available": True,
        "as_of": str(frame["day"].max()),
        "nights_analyzed": frame.height,
        "overall_grade": {"score": overall, "letter": _letter(overall)},
        "prescription": presc,
        "dimensions": dims,
        "recommendations": recs,
        "sleep_need": need,
        "consistency": reg,
        "stages": st,
        "debt": debt,
        "correlations": corr,
        "series": _series(frame),
    }
