"""Analytics engine (M5). Pure Polars over the normalized tables.

Every function takes DataFrames in and returns DataFrames/dicts out — no DB
access, no side effects — so all of it is unit-testable with synthetic data.

Loaders at the bottom bridge SQLAlchemy -> Polars for the API layer.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
from sqlalchemy import Date, DateTime, Float, Integer, select

from app.analytics import physiology
from app.db.engine import session_scope
from app.db.models.core import Activity, DailyMetrics
from app.db.models.weather import DailyWeather


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


# TRIMP's heart-rate-reserve math needs a resting HR; when the athlete hasn't
# configured a true one, this conservative population default applies to the
# rare sessions Garmin didn't attach its own load to.
DEFAULT_HR_REST = 60.0

# EWMA-based ACWR needs some history before the chronic side means anything;
# report null for the first two weeks rather than a confident-looking 1.0.
_ACWR_WARMUP_DAYS = 14


def daily_training_load(
    activities: pl.DataFrame,
    *,
    hr_rest: float | None = None,
    hr_max: float | None = None,
) -> pl.DataFrame:
    """Sum per-activity training load into one value per day. ONE load pipeline:
    Garmin's own load when present, Banister TRIMP (``physiology.trimp``) when
    not — the old ``minutes * HR/100`` proxy had no physiological basis and
    scored easy and hard minutes almost alike.

    ``hr_rest`` / ``hr_max`` sharpen the TRIMP fallback; pass the athlete's
    configured values (see ``training_load_for``). Defaults: HR max estimated
    from the activities frame, resting HR ``DEFAULT_HR_REST``.
    """
    if activities.is_empty():
        return pl.DataFrame({"day": [], "load": []})
    rest = hr_rest if hr_rest is not None else DEFAULT_HR_REST
    peak = physiology.estimate_hr_max(activities, configured=hr_max)

    def _trimp_fallback(row: dict[str, Any]) -> float | None:
        dur, hr = row.get("duration_s"), row.get("avg_hr")
        if dur is None or hr is None:
            return None
        return physiology.trimp(dur / 60.0, hr, rest, peak)

    fallback = (
        pl.struct(["duration_s", "avg_hr"]).map_elements(_trimp_fallback, return_dtype=pl.Float64)
        if {"duration_s", "avg_hr"}.issubset(activities.columns)
        else pl.lit(None, dtype=pl.Float64)
    )
    return (
        activities.with_columns(
            pl.coalesce([pl.col("training_load"), fallback]).fill_null(0).alias("_load")
        )
        .group_by("day")
        .agg(pl.col("_load").sum().alias("load"))
        .sort("day")
    )


# Chronic time constant for the EWMA ACWR. The literature's EWMA variant
# (Williams et al.) and Garmin's own ratio both use a ~28-day chronic; the
# PMC's 42-day CTL is NOT reused here because a longer denominator reads
# systematically higher during any build phase, miscalibrating the 1.3/1.5
# thresholds (verified against Garmin's dailyAcuteChronicWorkloadRatio).
ACWR_CHRONIC_TAU = 28


def acwr(load_by_day: pl.DataFrame) -> pl.DataFrame:
    """EWMA Acute:Chronic Workload Ratio over the ONE daily-load series.

    Same machinery as the Performance Management Chart (dense daily calendar +
    exponential averages; acute IS the PMC's ATL), with the literature's 28-day
    chronic constant (Williams et al.) — comparable to Garmin's own ratio and
    to the 1.3/1.5 thresholds. EWMA weights recent days more and never drops a
    spike off a window cliff the way the old rolling means did. ~0.8-1.3 is the
    common sweet-spot heuristic — treat it as a caution signal, not an injury
    prediction (the causal ACWR claims are contested; see Impellizzeri et al.).

    Column names (day/load/acute/chronic/acwr) are unchanged for consumers.
    The first ``_ACWR_WARMUP_DAYS`` are null: too little history to judge.
    """
    if load_by_day.is_empty():
        return load_by_day
    from app.analytics.fitness import FATIGUE_TAU, _alpha, _dense_daily_load

    warm = pl.int_range(pl.len()) >= _ACWR_WARMUP_DAYS
    return (
        _dense_daily_load(load_by_day)
        .with_columns(
            acute=pl.when(warm).then(
                pl.col("load").ewm_mean(alpha=_alpha(FATIGUE_TAU), adjust=False).round(1)
            ),
            chronic=pl.when(warm).then(
                pl.col("load").ewm_mean(alpha=_alpha(ACWR_CHRONIC_TAU), adjust=False).round(1)
            ),
        )
        .with_columns(
            acwr=(pl.col("acute") / pl.when(pl.col("chronic") > 0).then(pl.col("chronic"))).round(2)
        )
        .select("day", "load", "acute", "chronic", "acwr")
    )


def monotony(load_by_day: pl.DataFrame) -> pl.DataFrame:
    """Foster's training monotony over a trailing 7-day window, one row per day.

    High monotony (>2.0) with high load predicts overtraining/illness — it
    means every day looks the same, with no easy/hard variation.

    Trailing window rather than calendar weeks: bucketing by calendar week
    scored the current *partial* week, so two similar easy days on a Monday and
    Tuesday produced a huge spurious monotony value early in every week. The
    trailing window only reports once a full 7 days exist (nulls before that).
    """
    if load_by_day.is_empty():
        return load_by_day
    df = (
        load_by_day.sort("day")
        .upsample("day", every="1d")
        .with_columns(pl.col("load").fill_null(0))
    )
    return (
        df.with_columns(
            mean=pl.col("load").rolling_mean(7, min_samples=7),
            std=pl.col("load").rolling_std(7, min_samples=7),
        )
        .with_columns(
            monotony=(pl.col("mean") / pl.when(pl.col("std") > 0).then(pl.col("std"))).round(2)
        )
        .with_columns(strain=(pl.col("mean") * 7 * pl.col("monotony")).round(0))
    )


# -- recovery ---------------------------------------------------------------


def hrv_baseline_deviation(daily: pl.DataFrame) -> pl.DataFrame:
    """7-day HRV vs personal 60-day baseline, in percent (LEGACY method).

    Kept only as the fallback for thin history (``hrv_swc`` needs ~4 weeks and
    a baseline with real variance). New consumers should prefer ``hrv_swc``,
    which fixes this method's two flaws: raw-ms math on a log-normal quantity,
    and a baseline that includes the very dip it is trying to detect.
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


# Smallest-worthwhile-change band, in baseline SDs (Plews & Laursen / Buchheit):
# a 7-day ln-rMSSD average inside baseline +/- 0.75 SD is normal day-to-day
# variation; beyond 1.5 SD below is an alarm. Shared with the risk engine.
HRV_SWC_BAND_SD = 0.75
HRV_SWC_ALARM_SD = 1.5


def hrv_swc(daily: pl.DataFrame) -> pl.DataFrame:
    """HRV vs a self-referenced ln-rMSSD baseline band (smallest worthwhile change).

    The state-of-practice method:

    * work in ln(rMSSD) — HRV is log-normally distributed, so percent math on
      raw milliseconds misreads the same change at different baselines;
    * compare the 7-day rolling ln mean to a 60-day baseline that EXCLUDES the
      most recent 7 days — otherwise this week's dip drags the baseline down
      and partially hides itself;
    * the normal band is baseline +/- 0.75 SD of its daily ln values (the
      smallest worthwhile change); beyond 1.5 SD below is an alarm. Far ABOVE
      the band is a caution too (parasympathetic saturation seen in deep
      fatigue), not automatically good.

    Returns ``day``, ``hrv_z`` (position in baseline SDs), ``hrv_dev_pct``
    (geometric % vs the same baseline, for human-readable messages), and
    ``hrv_band`` (suppressed | below | normal | above | elevated). ``hrv_z``
    is null until ~4 weeks of history exist (or when the baseline has no
    variance); callers fall back to ``hrv_baseline_deviation`` then.
    """
    if daily.is_empty() or "hrv_last_night_avg" not in daily.columns:
        return pl.DataFrame({"day": [], "hrv_z": [], "hrv_dev_pct": [], "hrv_band": []})
    df = (
        daily.sort("day")
        .with_columns(
            ln=pl.when(pl.col("hrv_last_night_avg") > 0).then(
                pl.col("hrv_last_night_avg").cast(pl.Float64).log()
            )
        )
        .with_columns(
            ln_7d=pl.col("ln").rolling_mean(7, min_samples=3),
            base_mean=pl.col("ln").rolling_mean(60, min_samples=21).shift(7),
            base_sd=pl.col("ln").rolling_std(60, min_samples=21).shift(7),
        )
        .with_columns(
            hrv_z=(
                (pl.col("ln_7d") - pl.col("base_mean"))
                / pl.when(pl.col("base_sd") > 1e-6).then(pl.col("base_sd"))
            ).round(2),
            hrv_dev_pct=(((pl.col("ln_7d") - pl.col("base_mean")).exp() - 1) * 100).round(1),
        )
        .with_columns(
            hrv_band=pl.when(pl.col("hrv_z").is_null())
            .then(None)
            .when(pl.col("hrv_z") <= -HRV_SWC_ALARM_SD)
            .then(pl.lit("suppressed"))
            .when(pl.col("hrv_z") <= -HRV_SWC_BAND_SD)
            .then(pl.lit("below"))
            .when(pl.col("hrv_z") >= HRV_SWC_ALARM_SD)
            .then(pl.lit("elevated"))
            .when(pl.col("hrv_z") >= HRV_SWC_BAND_SD)
            .then(pl.lit("above"))
            .otherwise(pl.lit("normal"))
        )
    )
    return df.select("day", "hrv_z", "hrv_dev_pct", "hrv_band")


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

    # HRV trend flag: SWC band method first, legacy % fallback on thin history.
    swc = hrv_swc(df)
    swc_last = swc.tail(1).to_dicts()[0] if not swc.is_empty() else {}
    z = swc_last.get("hrv_z")
    if z is not None:
        pct = swc_last.get("hrv_dev_pct")
        if z <= -HRV_SWC_BAND_SD and pct is not None:
            findings.append(
                f"Your 7-day HRV is {abs(pct):.0f}% below your normal band "
                f"({z:.1f} SD vs your 60-day baseline) — a common early sign of "
                f"accumulated fatigue. Consider an easy day."
            )
    else:
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


def _model_schema(model: Any) -> dict[str, Any]:
    """Explicit Polars dtype per model column.

    Without this, ``pl.DataFrame`` infers each column's type from only the first
    100 rows. A metric that is null for the first 100+ days (routine once a full
    year is loaded — e.g. a sensor with no early data) would be inferred as the
    ``Null`` dtype, then blow up when a real value appears at row 101. Deriving
    the schema from the SQLAlchemy columns makes construction null-density-proof.
    """
    schema: dict[str, Any] = {}
    for c in model.__table__.columns:
        t = c.type
        if isinstance(t, Integer):
            schema[c.name] = pl.Int64
        elif isinstance(t, Float):
            schema[c.name] = pl.Float64
        elif isinstance(t, DateTime):
            schema[c.name] = pl.Datetime
        elif isinstance(t, Date):
            schema[c.name] = pl.Date
        else:
            schema[c.name] = pl.Utf8
    return schema


def load_daily(start: date | None = None, end: date | None = None) -> pl.DataFrame:
    with session_scope() as s:
        q = select(DailyMetrics)
        if start:
            q = q.where(DailyMetrics.day >= start)
        if end:
            q = q.where(DailyMetrics.day <= end)
        rows = s.execute(q.order_by(DailyMetrics.day)).scalars().all()
        data = [{c.name: getattr(r, c.name) for c in DailyMetrics.__table__.columns} for r in rows]
    return pl.DataFrame(data, schema=_model_schema(DailyMetrics))


def load_activities(start: date | None = None, end: date | None = None) -> pl.DataFrame:
    with session_scope() as s:
        q = select(Activity)
        if start:
            q = q.where(Activity.day >= start)
        if end:
            q = q.where(Activity.day <= end)
        rows = s.execute(q.order_by(Activity.start_time_local)).scalars().all()
        data = [{c.name: getattr(r, c.name) for c in Activity.__table__.columns} for r in rows]
    return pl.DataFrame(data, schema=_model_schema(Activity))


def training_load_for(activities: pl.DataFrame) -> pl.DataFrame:
    """``daily_training_load`` with the athlete's configured HR constants applied.

    Config is a loader-layer concern (the analytics stay pure), so every route/
    tool that already has an activities frame goes through here instead of
    calling ``daily_training_load`` bare.
    """
    from app.config import get_app_config

    athlete = get_app_config().athlete
    return daily_training_load(activities, hr_rest=athlete.hr_rest, hr_max=athlete.hr_max)


def load_training_load(start: date | None = None, end: date | None = None) -> pl.DataFrame:
    """Loader: activities in range -> daily training load, athlete config applied."""
    return training_load_for(load_activities(start, end))


def load_activity(activity_id: int) -> dict[str, Any] | None:
    """One activity row by Garmin activity id, or None if it isn't stored."""
    with session_scope() as s:
        row = s.get(Activity, activity_id)
        if row is None:
            return None
        return {c.name: getattr(row, c.name) for c in Activity.__table__.columns}


def load_weather(start: date | None = None, end: date | None = None) -> pl.DataFrame:
    """Daily weather rows as a Polars frame (empty frame if none collected yet)."""
    with session_scope() as s:
        q = select(DailyWeather)
        if start:
            q = q.where(DailyWeather.day >= start)
        if end:
            q = q.where(DailyWeather.day <= end)
        rows = s.execute(q.order_by(DailyWeather.day)).scalars().all()
        data = [{c.name: getattr(r, c.name) for c in DailyWeather.__table__.columns} for r in rows]
    return pl.DataFrame(data, schema=_model_schema(DailyWeather))
