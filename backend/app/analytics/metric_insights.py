"""Per-metric insight cards (M7). "Something analytical for every data point."

For each tracked metric this produces a compact, self-explaining card: latest
value, 7- and 30-day baselines, trend, a personal z-score, a good/watch/alert
status, a plain-language note, and a sparkline series. Pure Polars over the
daily frame — the API layer just serializes the result.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import polars as pl


def _f(value: Any) -> float | None:
    """Coerce a Polars scalar (union-typed under mypy strict) to float | None."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class MetricSpec:
    key: str
    label: str
    unit: str
    higher_better: bool | None  # None = neutral (context-dependent)
    good: str  # short note fragment describing the good direction


SPECS: list[MetricSpec] = [
    MetricSpec("training_readiness", "Training Readiness", "", True, "ready to train hard"),
    MetricSpec(
        "hrv_last_night_avg", "HRV (overnight)", "ms", True, "well-recovered autonomic tone"
    ),
    MetricSpec("resting_hr", "Resting HR", "bpm", False, "aerobic fitness / recovery"),
    MetricSpec("sleep_score", "Sleep Score", "", True, "good quality sleep"),
    MetricSpec("body_battery_high", "Body Battery (peak)", "", True, "high daily energy reserve"),
    MetricSpec("avg_stress", "Avg Stress", "", False, "low physiological stress"),
    MetricSpec("steps", "Steps", "", True, "daily movement"),
    MetricSpec("intensity_minutes", "Intensity Minutes", "", True, "cardio load (WHO: 150/wk)"),
    MetricSpec("vo2max_running", "VO2max (running)", "", True, "aerobic ceiling"),
    MetricSpec("respiration_avg", "Sleep Respiration", "br/min", False, "calm overnight breathing"),
    MetricSpec("spo2_avg", "Pulse Ox (SpO2)", "%", True, "blood-oxygen saturation"),
    MetricSpec("weight_kg", "Weight", "lb", None, "trend toward your 195-200 lb goal"),
]


def _trend_word(delta_pct: float | None) -> str:
    if delta_pct is None:
        return "flat"
    if delta_pct >= 3:
        return "rising"
    if delta_pct <= -3:
        return "falling"
    return "steady"


def _status(z: float | None, higher_better: bool | None) -> str:
    """Good/watch/alert from a personal z-score and the metric's good direction."""
    if z is None or higher_better is None:
        return "neutral"
    signed = z if higher_better else -z
    if signed >= -0.4:
        return "good"
    if signed >= -1.0:
        return "watch"
    return "alert"


def _note(spec: MetricSpec, latest: float, avg30: float | None, z: float | None) -> str:
    if avg30 is None or z is None:
        return f"Tracking your {spec.label.lower()} — needs a bit more history for context."
    vs = "above" if latest >= avg30 else "below"
    z_desc = (
        "right on your normal"
        if abs(z) < 0.5
        else "a bit off your normal"
        if abs(z) < 1.0
        else "well off your normal"
    )
    good = _status(z, spec.higher_better) == "good"
    tail = f" That reads as {spec.good}." if good else ""
    return f"Latest is {vs} your 30-day average ({z_desc}, z={z:+.1f})." + tail


def _series(df: pl.DataFrame, key: str, n: int = 30) -> list[dict[str, Any]]:
    if key not in df.columns:
        return []
    tail = df.tail(n).select("day", key)
    return [{"day": str(r["day"]), "value": r[key]} for r in tail.iter_rows(named=True)]


def metric_cards(daily: pl.DataFrame) -> list[dict[str, Any]]:
    """One analytical card per metric, most actionable (alert) first."""
    if daily.is_empty():
        return []
    df = daily.sort("day")

    # Weight is stored in kg but Trent thinks in pounds.
    if "weight_kg" in df.columns:
        df = df.with_columns((pl.col("weight_kg") * 2.2046226).alias("weight_lb"))

    cards: list[dict[str, Any]] = []
    for spec in SPECS:
        col = "weight_lb" if spec.key == "weight_kg" else spec.key
        if col not in df.columns:
            continue
        series = df.select("day", col).drop_nulls(col)
        if series.height == 0:
            continue

        values = series[col]
        latest = _f(values[-1])
        if latest is None:
            continue
        avg7 = _f(values.tail(7).mean())
        avg30 = _f(values.tail(30).mean())
        prev7 = _f(values.tail(14).head(7).mean()) if values.len() >= 8 else None
        std30 = _f(values.tail(30).std())

        delta_pct = (
            round((avg7 - prev7) / prev7 * 100, 1)
            if avg7 is not None and prev7 is not None and prev7 != 0
            else None
        )
        z = (
            round((latest - avg30) / std30, 2)
            if avg30 is not None and std30 is not None and std30 != 0
            else None
        )
        status = _status(z, spec.higher_better)

        cards.append(
            {
                "key": spec.key,
                "label": spec.label,
                "unit": spec.unit,
                "higher_better": spec.higher_better,
                "value": round(latest, 1),
                "avg7": None if avg7 is None else round(avg7, 1),
                "avg30": None if avg30 is None else round(avg30, 1),
                "delta_pct": delta_pct,
                "trend": _trend_word(delta_pct),
                "z": z,
                "status": status,
                "note": _note(spec, latest, avg30, z),
                # Select only day + the metric (aliased) to avoid colliding with
                # the source column when it was derived (e.g. weight_lb -> weight_kg).
                "series": _series(df.select("day", pl.col(col).alias(spec.key)), spec.key),
            }
        )

    order = {"alert": 0, "watch": 1, "good": 2, "neutral": 3}
    cards.sort(key=lambda c: order.get(c["status"], 4))
    return cards
