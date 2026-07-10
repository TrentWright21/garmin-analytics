"""Local deterministic insight engine (redesign Phase 3, stage 5).

Turns one metric's history into a detail payload for the ``/metric/:key`` view:
current value, status, change vs the previous period, range stats, the series,
plain-English **local** insights, and REAL relationships with other metrics
(Pearson correlation over aligned days — never a fabricated link).

Everything here is Tier 1: pure math on the athlete's own data, no external AI.
It reuses the specs + helpers in ``metric_insights`` so the two never drift, and
degrades cleanly on thin/partial history. The route layer loads the frame.
"""

from __future__ import annotations

import math
from typing import Any

import polars as pl

from app.analytics import metric_insights as mi

_SPEC_BY_KEY = {s.key: s for s in mi.SPECS}

# Canonical relationship map (mirrors the frontend registry). Only pairs that
# are physiologically plausible AND computable from daily columns; the actual
# correlation is measured, so a weak/absent link simply won't be shown.
_RELATED: dict[str, list[str]] = {
    "training_readiness": ["sleep_score", "hrv_last_night_avg", "resting_hr"],
    "hrv_last_night_avg": ["sleep_score", "resting_hr", "avg_stress"],
    "resting_hr": ["hrv_last_night_avg", "sleep_score"],
    "sleep_score": ["hrv_last_night_avg", "resting_hr", "body_battery_high"],
    "body_battery_high": ["avg_stress", "sleep_score"],
    "avg_stress": ["body_battery_high", "sleep_score"],
    "respiration_avg": ["hrv_last_night_avg"],
    "steps": [],
    "intensity_minutes": [],
    "vo2max_running": [],
}

_MIN_HISTORY = 7  # non-null points needed before any trend insight
_MIN_CORR_N = 10  # aligned day-pairs needed before a relationship is shown
_MIN_CORR_R = 0.25  # |r| below this is not worth surfacing
_NIGHTLY = {"sleep_score", "hrv_last_night_avg", "respiration_avg", "resting_hr"}


def metric_detail(daily: pl.DataFrame, key: str, days: int = 90) -> dict[str, Any]:
    """Full detail payload for one metric over the last ``days`` days."""
    spec = _SPEC_BY_KEY.get(key)
    if spec is None or daily.is_empty() or key not in daily.columns:
        return {"available": False, "key": key}

    df = daily.sort("day").select("day", key)
    series_rows = df.tail(days).to_dicts()
    nonnull = df.drop_nulls(subset=[key])
    if nonnull.is_empty():
        return {"available": False, "key": key}

    values = nonnull[key]
    current = mi._f(values[-1])
    as_of = str(nonnull["day"][-1])
    avg7 = mi._f(values.tail(7).mean())
    prev7 = mi._f(values.tail(14).head(7).mean()) if values.len() >= 8 else None
    avg30 = mi._f(values.tail(30).mean())
    std30 = mi._f(values.tail(30).std())
    delta_pct = (
        round((avg7 - prev7) / prev7 * 100, 1)
        if avg7 is not None and prev7 is not None and prev7 != 0
        else None
    )
    z = (
        round((current - avg30) / std30, 2)
        if current is not None and avg30 is not None and std30 is not None and std30 != 0
        else None
    )
    status = mi._status(z, spec.higher_better)

    # Stats over the DISPLAYED range (what the chart shows).
    disp = [v for r in series_rows if (v := mi._f(r[key])) is not None]
    stats = {
        "avg": round(sum(disp) / len(disp), 1) if disp else None,
        "min": round(min(disp), 1) if disp else None,
        "max": round(max(disp), 1) if disp else None,
        "trend": mi._trend_word(delta_pct),
    }
    normal = (
        {"low": round(avg30 - std30, 1), "high": round(avg30 + std30, 1)}
        if avg30 is not None and std30 is not None
        else None
    )

    insights = _local_insights(spec, disp, current, avg7, avg30, std30, z, delta_pct)
    relationships = _relationships(df, daily, key, days)

    unit = spec.unit
    return {
        "available": True,
        "key": key,
        "label": spec.label,
        "unit": unit,
        "direction": (
            "higher-better"
            if spec.higher_better
            else "lower-better"
            if spec.higher_better is False
            else "neutral"
        ),
        "range_days": days,
        "current": None if current is None else round(current, 1),
        "as_of": as_of,
        "status": status,
        "delta": {"pct": delta_pct, "vs": "previous 7 days"},
        "stats": stats,
        "baseline": {"avg30": None if avg30 is None else round(avg30, 1), "z": z, "normal": normal},
        "series": [{"day": str(r["day"]), "value": r[key]} for r in series_rows],
        "insights": insights,
        "relationships": relationships,
        "chart_summary": _chart_summary(spec, days, current, stats),
    }


def _local_insights(
    spec: mi.MetricSpec,
    disp: list[float],
    current: float | None,
    avg7: float | None,
    avg30: float | None,
    std30: float | None,
    z: float | None,
    delta_pct: float | None,
) -> list[str]:
    """Ranked, concise, personal-baseline-first insights (most salient first)."""
    label = spec.label.lower()
    period = "nights" if spec.key in _NIGHTLY else "days"
    out: list[str] = []

    if len(disp) < _MIN_HISTORY:
        return ["There is not enough history yet to establish a reliable trend."]

    # Outlier (strongest signal).
    if z is not None and abs(z) >= 2.0:
        out.append(
            f"Today is an unusually {'high' if z > 0 else 'low'} reading versus your "
            f"normal range (z = {z:+.1f})."
        )

    # Baseline deviation (7-day vs 30-day).
    if avg7 is not None and avg30 is not None and avg30 != 0:
        pct = (avg7 - avg30) / avg30 * 100
        if abs(pct) >= 5:
            out.append(
                f"Your {label} is {abs(pct):.0f}% {'above' if pct > 0 else 'below'} "
                "your 30-day baseline."
            )

    # Consecutive rising/falling run (framed by good direction).
    direction, run = _consecutive_run(disp)
    if run >= 3 and direction != "flat":
        improving = (direction == "rising") == bool(spec.higher_better)
        verb = (
            "improved"
            if spec.higher_better is not None and improving
            else "declined"
            if spec.higher_better is not None
            else ("risen" if direction == "rising" else "fallen")
        )
        out.append(f"Your {label} has {verb} for {run} consecutive {period}.")

    # 7-day trend.
    if delta_pct is not None and abs(delta_pct) >= 3 and len(out) < 3:
        out.append(f"Your 7-day average is trending {'upward' if delta_pct > 0 else 'downward'}.")

    # Reassurance when nothing notable fired.
    if not out and z is not None and abs(z) < 1:
        out.append("This value is within your normal personal range.")

    return out[:3]


def _consecutive_run(vals: list[float]) -> tuple[str, int]:
    """Length of the trailing strictly-monotonic run (rising/falling/flat)."""
    if len(vals) < 2 or vals[-1] == vals[-2]:
        return ("flat", 0)
    up = vals[-1] > vals[-2]
    n = 1
    for i in range(len(vals) - 1, 0, -1):
        if (up and vals[i] > vals[i - 1]) or (not up and vals[i] < vals[i - 1]):
            n += 1
        else:
            break
    return ("rising" if up else "falling", n)


def _relationships(
    df_metric: pl.DataFrame, daily: pl.DataFrame, key: str, days: int
) -> list[dict[str, Any]]:
    """Measured Pearson correlations with related metrics over the display range."""
    out: list[dict[str, Any]] = []
    label = _SPEC_BY_KEY[key].label
    window = daily.sort("day").tail(days)
    for other in _RELATED.get(key, []):
        other_spec = _SPEC_BY_KEY.get(other)
        if other_spec is None or other not in daily.columns:
            continue
        pair = window.select(pl.col(key), pl.col(other)).drop_nulls()
        n = pair.height
        if n < _MIN_CORR_N:
            continue
        r = _pearson(pair[key].to_list(), pair[other].to_list())
        if r is None or abs(r) < _MIN_CORR_R:
            continue
        out.append(
            {
                "key": other,
                "label": other_spec.label,
                "r": round(r, 2),
                "n": n,
                "interpretation": (
                    f"Over the last {n} days, higher {other_spec.label} tended to coincide "
                    f"with {'higher' if r > 0 else 'lower'} {label} (r = {r:+.2f})."
                ),
            }
        )
    out.sort(key=lambda d: abs(d["r"]), reverse=True)
    return out


def _pearson(xs: list[Any], ys: list[Any]) -> float | None:
    """Pearson correlation of two equal-length numeric lists, or None."""
    pts = [
        (float(x), float(y)) for x, y in zip(xs, ys, strict=True) if x is not None and y is not None
    ]
    n = len(pts)
    if n < 3:
        return None
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    sxx = sum((p[0] - mx) ** 2 for p in pts)
    syy = sum((p[1] - my) ** 2 for p in pts)
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pts)
    denom = math.sqrt(sxx * syy)
    return sxy / denom if denom > 0 else None


def _chart_summary(
    spec: mi.MetricSpec, days: int, current: float | None, stats: dict[str, Any]
) -> str:
    """One-line screen-reader summary of the chart (accessibility)."""
    unit = f" {spec.unit}" if spec.unit else ""
    cur = "no recent value" if current is None else f"{round(current, 1)}{unit}"
    avg = stats.get("avg")
    lo, hi = stats.get("min"), stats.get("max")
    return (
        f"{spec.label} over the last {days} days: currently {cur}; "
        f"average {avg}{unit}, ranging {lo} to {hi}{unit}; trend {stats.get('trend')}."
    )
