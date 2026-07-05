"""Analytics engine (M5). Pure Polars over the normalized tables.

Every function takes DataFrames in and returns DataFrames/dicts out — no DB
access, no side effects — so all of it is unit-testable with synthetic data.

Loaders at the bottom bridge SQLAlchemy -> Polars for the API layer.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
from sqlalchemy import select

from app.db.engine import session_scope
from app.db.models.core import Activity, DailyMetrics


def _f(value: Any) -> float | None:
    """Coerce a Polars scalar (union-typed) to float for arithmetic."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


TREND_METRICS = [
    "steps",
    "resting_hr",
    "hrv_last_night_avg",
    "sleep_score",
    "avg_stress",
    "body_battery_high",
    "training_readiness",
    "vo2max_running",
    "weight_kg",
]


# -- trends ------------------------------------------------------------------


def rolling_trends(daily: pl.DataFrame, windows: tuple[int, ...] = (7, 30)) -> pl.DataFrame:
    """Rolling means for each key metric. Input needs a sorted ``day`` column."""
    if daily.is_empty():
        return daily
    df = daily.sort("day")
    exprs = []
    for metric in TREND_METRICS:
        if metric not in df.columns:
            continue
        for w in windows:
            exprs.append(
                pl.col(metric).rolling_mean(w, min_samples=max(2, w // 3)).alias(f"{metric}_r{w}")
            )
    return df.with_columns(exprs)


def period_summary(daily: pl.DataFrame, every: str = "1w") -> pl.DataFrame:
    """Weekly/monthly aggregates (pass every='1mo' for monthly)."""
    if daily.is_empty():
        return daily
    present = [m for m in TREND_METRICS if m in daily.columns]
    return (
        daily.sort("day")
        .group_by_dynamic("day", every=every)
        .agg([pl.col(m).mean().round(1).alias(f"{m}_avg") for m in present])
    )


# -- training load -------------------------------------------------------------


def daily_training_load(activities: pl.DataFrame) -> pl.DataFrame:
    """Sum Garmin's per-activity training load into one value per day.

    Falls back to a HR-duration proxy when Garmin didn't compute load.
    """
    if activities.is_empty():
        return pl.DataFrame({"day": [], "load": []})
    proxy = (pl.col("duration_s") / 60) * (pl.col("avg_hr") / 100)
    return (
        activities.with_columns(
            pl.coalesce([pl.col("training_load"), proxy]).fill_null(0).alias("_load")
        )
        .group_by("day")
        .agg(pl.col("_load").sum().alias("load"))
        .sort("day")
    )


def acwr(load_by_day: pl.DataFrame) -> pl.DataFrame:
    """Acute:Chronic Workload Ratio — 7d avg load / 28d avg load.

    The classic injury-risk indicator: roughly 0.8-1.3 is the sweet spot;
    sustained >1.5 means load is spiking faster than the body has adapted to.
    """
    if load_by_day.is_empty():
        return load_by_day
    df = (
        load_by_day.sort("day")
        .upsample("day", every="1d")
        .with_columns(pl.col("load").fill_null(0))
    )
    return df.with_columns(
        acute=pl.col("load").rolling_mean(7, min_samples=4),
        chronic=pl.col("load").rolling_mean(28, min_samples=14),
    ).with_columns(
        acwr=(pl.col("acute") / pl.when(pl.col("chronic") > 0).then(pl.col("chronic"))).round(2)
    )


def monotony(load_by_day: pl.DataFrame) -> pl.DataFrame:
    """Foster's training monotony: weekly mean load / weekly std.

    High monotony (>2.0) with high load predicts overtraining/illness — it
    means every day looks the same, with no easy/hard variation.
    """
    if load_by_day.is_empty():
        return load_by_day
    df = (
        load_by_day.sort("day")
        .upsample("day", every="1d")
        .with_columns(pl.col("load").fill_null(0))
    )
    return (
        df.group_by_dynamic("day", every="1w")
        .agg(mean=pl.col("load").mean(), std=pl.col("load").std())
        .with_columns(
            monotony=(pl.col("mean") / pl.when(pl.col("std") > 0).then(pl.col("std"))).round(2)
        )
        .with_columns(strain=(pl.col("mean") * 7 * pl.col("monotony")).round(0))
    )


# -- recovery ---------------------------------------------------------------


def hrv_baseline_deviation(daily: pl.DataFrame) -> pl.DataFrame:
    """7-day HRV vs personal 60-day baseline, in percent.

    Sustained deviation below ~ -8% is an earlier overtraining/illness signal
    than Garmin's own status flag.
    """
    if daily.is_empty() or "hrv_last_night_avg" not in daily.columns:
        return pl.DataFrame({"day": [], "hrv_dev_pct": []})
    df = daily.sort("day")
    return df.with_columns(
        hrv_7d=pl.col("hrv_last_night_avg").rolling_mean(7, min_samples=3),
        hrv_60d=pl.col("hrv_last_night_avg").rolling_mean(60, min_samples=21),
    ).with_columns(
        hrv_dev_pct=((pl.col("hrv_7d") - pl.col("hrv_60d")) / pl.col("hrv_60d") * 100).round(1)
    )


# -- readiness ------------------------------------------------------------------


def readiness_score(daily: pl.DataFrame) -> dict[str, Any]:
    """Composite 0-100 readiness from the latest day's signals.

    Not Garmin's black box: every component and its contribution is returned,
    so the dashboard can show WHY the score is what it is.
    """
    if daily.is_empty():
        return {"score": None, "components": {}}
    dev = hrv_baseline_deviation(daily)
    last = daily.sort("day").tail(1).to_dicts()[0]
    last_dev_rows = dev.tail(1).to_dicts() if not dev.is_empty() else [{}]
    hrv_dev = last_dev_rows[0].get("hrv_dev_pct")

    components: dict[str, float] = {}
    if hrv_dev is not None:
        components["hrv_vs_baseline"] = max(0.0, min(100.0, 70 + float(hrv_dev) * 3))
    if (ss := last.get("sleep_score")) is not None:
        components["sleep"] = float(ss)
    if (bb := last.get("body_battery_high")) is not None:
        components["body_battery"] = float(bb)
    if (stress := last.get("avg_stress")) is not None:
        components["stress"] = max(0.0, 100.0 - float(stress))

    if not components:
        return {"score": None, "components": {}}
    score = round(sum(components.values()) / len(components))
    return {"score": score, "components": {k: round(v) for k, v in components.items()}}


# -- insights -----------------------------------------------------------------


def generate_insights(daily: pl.DataFrame, activities: pl.DataFrame) -> list[str]:
    """Rule-based natural-language findings. Grows every milestone."""
    findings: list[str] = []
    if daily.is_empty():
        return findings
    df = daily.sort("day")

    # Resting HR long-term change
    rhr = df.select("day", "resting_hr").drop_nulls()
    if rhr.height >= 60:
        first = _f(rhr.head(30)["resting_hr"].mean())
        last = _f(rhr.tail(30)["resting_hr"].mean())
        if first and last and abs(last - first) >= 2:
            direction = "dropped" if last < first else "risen"
            findings.append(
                f"Your resting HR has {direction} {abs(last - first):.0f} bpm "
                f"between your first and most recent 30 days of data."
            )

    # Sleep -> next-day body battery
    if {"sleep_seconds", "body_battery_high"}.issubset(df.columns):
        joined = df.select("day", "sleep_seconds", "body_battery_high").drop_nulls()
        if joined.height >= 21:
            long_sleep = joined.filter(pl.col("sleep_seconds") >= 8 * 3600)
            short_sleep = joined.filter(pl.col("sleep_seconds") < 7 * 3600)
            if long_sleep.height >= 5 and short_sleep.height >= 5:
                hi = _f(long_sleep["body_battery_high"].mean())
                lo = _f(short_sleep["body_battery_high"].mean())
                if hi and lo and hi - lo >= 5:
                    findings.append(
                        f"After 8+ hours of sleep your Body Battery peaks {hi - lo:.0f} points "
                        f"higher than after nights under 7 hours."
                    )

    # HRV trend flag
    dev = hrv_baseline_deviation(df)
    if not dev.is_empty():
        recent = dev.tail(1).to_dicts()[0].get("hrv_dev_pct")
        if recent is not None and recent <= -8:
            findings.append(
                f"Your 7-day HRV is {abs(recent):.0f}% below your 60-day baseline — "
                f"a common early sign of accumulated fatigue. Consider an easy day."
            )

    # Temperature effect on runs
    if not activities.is_empty() and {"avg_temp_c", "distance_m", "duration_s"}.issubset(
        activities.columns
    ):
        runs = activities.filter(
            (pl.col("activity_type").str.contains("running").fill_null(False))
            & pl.col("avg_temp_c").is_not_null()
            & (pl.col("distance_m") > 1500)
        ).with_columns(pace_s_per_km=pl.col("duration_s") / (pl.col("distance_m") / 1000))
        if runs.height >= 10:
            cool = runs.filter(pl.col("avg_temp_c") < 21)  # ~70F
            warm = runs.filter(pl.col("avg_temp_c") >= 21)
            if cool.height >= 4 and warm.height >= 4:
                pc = _f(cool["pace_s_per_km"].mean())
                pw = _f(warm["pace_s_per_km"].mean())
                if pc and pw and pw - pc >= 8:
                    findings.append(
                        f"You run about {(pw - pc):.0f} s/km faster when it's below 70°F."
                    )

    return findings


# -- loaders (DB -> Polars) --------------------------------------------------


def load_daily(start: date | None = None, end: date | None = None) -> pl.DataFrame:
    with session_scope() as s:
        q = select(DailyMetrics)
        if start:
            q = q.where(DailyMetrics.day >= start)
        if end:
            q = q.where(DailyMetrics.day <= end)
        rows = s.execute(q.order_by(DailyMetrics.day)).scalars().all()
        data = [{c.name: getattr(r, c.name) for c in DailyMetrics.__table__.columns} for r in rows]
    return pl.DataFrame(data)


def load_activities(start: date | None = None, end: date | None = None) -> pl.DataFrame:
    with session_scope() as s:
        q = select(Activity)
        if start:
            q = q.where(Activity.day >= start)
        if end:
            q = q.where(Activity.day <= end)
        rows = s.execute(q.order_by(Activity.start_time_local)).scalars().all()
        data = [{c.name: getattr(r, c.name) for c in Activity.__table__.columns} for r in rows]
    return pl.DataFrame(data)
