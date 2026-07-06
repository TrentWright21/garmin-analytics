"""Session intelligence (M8): what actually happened in one workout.

For a single activity this produces the layer Garmin's per-activity screen does
not: an efficiency factor (speed per heartbeat), a comparison against the user's
own baseline for *similar* sessions, a plain-language physiological breakdown,
aerobic decoupling / cardiac drift when split data is available, and concrete
"missed opportunity" or "nailed it" insights.

Pure functions. ``analyze_session`` takes the activity row + the user's activity
history (both plain dicts / Polars frames) so it is fully unit-testable; the API
loader passes real data in.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from app.analytics.physiology import _f, hr_zone, intensity_band

M_PER_MILE = 1609.344

_ZONE_MEANING = {
    1: "recovery",
    2: "aerobic base (easy)",
    3: "aerobic/tempo",
    4: "threshold",
    5: "VO2max / anaerobic",
}


def efficiency_factor(
    distance_m: float | None, duration_s: float | None, avg_hr: float | None
) -> float | None:
    """Aerobic efficiency: metres covered per minute, per heart beat.

    ``EF = (speed in m/min) / average HR``. Higher is better: at the same heart
    rate you are moving faster. Rising EF across similar easy runs is one of the
    cleanest signals that aerobic fitness is improving.
    """
    d, t, hr = _f(distance_m), _f(duration_s), _f(avg_hr)
    if not d or not t or not hr or t <= 0 or hr <= 0:
        return None
    return round((d / (t / 60.0)) / hr, 3)


def _pace_s_per_km(distance_m: float | None, duration_s: float | None) -> float | None:
    d, t = _f(distance_m), _f(duration_s)
    if not d or not t or d <= 0:
        return None
    return t / (d / 1000.0)


def decoupling_index(splits: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Aerobic decoupling: how much efficiency drifted from first half to second.

    ``splits`` is an ordered list of lap dicts each with ``duration_s``,
    ``distance_m`` and ``avg_hr``. We compute the efficiency factor of the first
    vs second half (by elapsed time) and report the percentage drop.

    >5% decoupling on a steady effort means HR drifted up (or pace fell) as the
    session wore on — a sign of going out too hard, heat, dehydration, or that
    the effort exceeded current aerobic durability (Friel's Pw:Hr / aerobic
    decoupling). Returns None if the splits lack the data to compute it.
    """
    usable = [
        s
        for s in splits
        if _f(s.get("duration_s")) and _f(s.get("distance_m")) and _f(s.get("avg_hr"))
    ]
    if len(usable) < 2:
        return None
    total = sum(float(s["duration_s"]) for s in usable)
    half = total / 2.0

    first: list[dict[str, Any]] = []
    second: list[dict[str, Any]] = []
    elapsed = 0.0
    for s in usable:
        dur = float(s["duration_s"])
        mid = elapsed + dur / 2.0
        (first if mid <= half else second).append(s)
        elapsed += dur
    if not first or not second:
        return None

    def half_ef(group: list[dict[str, Any]]) -> float | None:
        dist = sum(float(s["distance_m"]) for s in group)
        time = sum(float(s["duration_s"]) for s in group)
        hr = sum(float(s["avg_hr"]) * float(s["duration_s"]) for s in group) / time
        return efficiency_factor(dist, time, hr)

    ef1, ef2 = half_ef(first), half_ef(second)
    if ef1 is None or ef2 is None or ef1 == 0:
        return None
    drift = round((ef1 - ef2) / ef1 * 100.0, 1)
    return {
        "decoupling_pct": drift,
        "first_half_ef": ef1,
        "second_half_ef": ef2,
        "aerobic_status": "well-coupled" if drift <= 5 else "decoupled",
    }


def _similar(history: pl.DataFrame, activity: dict[str, Any]) -> pl.DataFrame:
    """Past activities of the same type at a comparable distance (+-25%)."""
    if history.is_empty() or "activity_type" not in history.columns:
        return history.clear()
    a_type = activity.get("activity_type")
    dist = _f(activity.get("distance_m"))
    df = history
    if "activity_id" in df.columns and activity.get("activity_id") is not None:
        df = df.filter(pl.col("activity_id") != activity["activity_id"])
    if a_type is not None:
        df = df.filter(pl.col("activity_type") == a_type)
    if dist is not None and dist > 0 and "distance_m" in df.columns:
        df = df.filter(
            (pl.col("distance_m") >= dist * 0.75) & (pl.col("distance_m") <= dist * 1.25)
        )
    return df


def analyze_session(
    activity: dict[str, Any],
    history: pl.DataFrame,
    hr_max: float,
    splits: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Full breakdown of one session: physiology, efficiency, baseline, drift."""
    avg_hr = _f(activity.get("avg_hr"))
    dist = _f(activity.get("distance_m"))
    dur = _f(activity.get("duration_s"))
    ef = efficiency_factor(dist, dur, avg_hr)
    pace = _pace_s_per_km(dist, dur)

    band = intensity_band(avg_hr, hr_max) if avg_hr else "unknown"
    zone = hr_zone(avg_hr, hr_max) if avg_hr else None

    out: dict[str, Any] = {
        "activity_id": activity.get("activity_id"),
        "day": str(activity.get("day")) if activity.get("day") else None,
        "type": activity.get("activity_type"),
        "name": activity.get("name"),
        "distance_mi": round(dist / M_PER_MILE, 2) if dist else None,
        "duration_min": round(dur / 60.0, 1) if dur else None,
        "avg_hr": round(avg_hr) if avg_hr else None,
        "pct_hr_max": round(avg_hr / hr_max * 100) if (avg_hr and hr_max) else None,
        "effort": band,
        "zone": zone,
        "efficiency_factor": ef,
    }

    out["physiology"] = _physiology(activity, band, zone, hr_max)

    # Baseline comparison against similar sessions.
    similar = _similar(history, activity)
    out["baseline"] = _baseline(similar, ef, pace)

    # Aerobic decoupling / cardiac drift.
    if splits:
        out["decoupling"] = decoupling_index(splits)
    else:
        out["decoupling"] = None
        out["decoupling_note"] = (
            "Per-lap data not loaded for this activity; decoupling needs the "
            "activity-detail endpoint."
        )

    out["insights"] = _session_insights(activity, band, out["baseline"], out.get("decoupling"))
    return out


def _physiology(activity: dict[str, Any], band: str, zone: int | None, hr_max: float) -> list[str]:
    notes: list[str] = []
    avg_hr = _f(activity.get("avg_hr"))
    if avg_hr and zone:
        notes.append(
            f"Averaged {round(avg_hr / hr_max * 100)}% of max HR — Zone {zone} "
            f"({_ZONE_MEANING[zone]})."
        )
    if band == "easy":
        notes.append(
            "Predominantly fat-oxidation / aerobic base work; low glycogen cost, "
            "builds capillary density and mitochondria without much fatigue."
        )
    elif band == "moderate":
        notes.append(
            "Sustained tempo/threshold effort: heavy on aerobic glycolysis and "
            "lactate clearance — productive but costs real recovery."
        )
    elif band == "hard":
        notes.append(
            "High anaerobic contribution: taxes VO2max and lactate tolerance. "
            "Potent stimulus, but demands adequate recovery afterwards."
        )

    dist = _f(activity.get("distance_m"))
    gain = _f(activity.get("elevation_gain_m"))
    if dist and gain and dist > 0 and (gain / (dist / 1000.0)) > 15:
        notes.append(
            f"Climbing-heavy: {round(gain)} m gain over {round(dist / 1000, 1)} km "
            f"({round(gain / (dist / 1000.0))} m/km) inflates HR for the pace."
        )
    temp = _f(activity.get("avg_temp_c"))
    if temp and temp >= 24:
        notes.append(
            f"Run in heat (~{round(temp * 9 / 5 + 32)}F): cardiac drift and HR are "
            "expected to run higher than the pace alone implies."
        )
    return notes


def _baseline(similar: pl.DataFrame, ef: float | None, pace: float | None) -> dict[str, Any]:
    if similar.is_empty():
        return {"n": 0, "note": "No comparable past sessions yet."}
    n = similar.height
    ef_vals: list[float] = [
        v
        for r in similar.to_dicts()
        if (v := efficiency_factor(r.get("distance_m"), r.get("duration_s"), r.get("avg_hr")))
        is not None
    ]
    pace_vals = [
        p
        for r in similar.to_dicts()
        if (p := _pace_s_per_km(r.get("distance_m"), r.get("duration_s"))) is not None
    ]
    base_ef = round(sum(ef_vals) / len(ef_vals), 3) if ef_vals else None
    base_pace = round(sum(pace_vals) / len(pace_vals), 1) if pace_vals else None

    ef_delta_pct = round((ef - base_ef) / base_ef * 100, 1) if (ef and base_ef) else None
    pace_delta = round(base_pace - pace, 1) if (pace and base_pace) else None  # +ve = faster
    return {
        "n": n,
        "baseline_ef": base_ef,
        "baseline_pace_s_per_km": base_pace,
        "ef_delta_pct": ef_delta_pct,
        "pace_delta_s_per_km": pace_delta,
    }


def _session_insights(
    activity: dict[str, Any],
    band: str,
    baseline: dict[str, Any],
    decoupling: dict[str, Any] | None,
) -> list[str]:
    out: list[str] = []
    dist = _f(activity.get("distance_m"))

    # Efficiency signal vs the user's own similar sessions.
    ef_delta = baseline.get("ef_delta_pct")
    if isinstance(ef_delta, int | float) and baseline.get("n", 0) >= 3:
        if ef_delta >= 4:
            out.append(
                f"Fitness signal: {ef_delta:.0f}% more speed per heartbeat than your recent "
                "similar sessions — aerobic fitness is trending up."
            )
        elif ef_delta <= -4:
            out.append(
                f"Efficiency was {abs(ef_delta):.0f}% below your similar-session baseline — "
                "possible residual fatigue, heat, or terrain. Worth noting if it repeats."
            )

    # Long run run too hard (grey zone) — a very common, costly mistake.
    if band == "moderate" and dist and dist / M_PER_MILE >= 6:
        out.append(
            "This longer run sat in the tempo 'grey zone'. If it was meant to be easy, "
            "slowing down would build the same base with far less fatigue."
        )
    if band == "hard" and dist and dist / M_PER_MILE >= 8:
        out.append(
            "Long run at a hard average HR — a big recovery cost. Make sure this was an "
            "intended key session, not an easy day that got away from you."
        )

    # Decoupling verdict.
    if decoupling and decoupling.get("decoupling_pct") is not None:
        d = decoupling["decoupling_pct"]
        if d > 8:
            out.append(
                f"Significant cardiac drift ({d:.0f}%): efficiency fell sharply in the second "
                "half — likely went out too fast, or aerobic durability is the limiter."
            )
        elif d <= 5:
            out.append(
                f"Well-coupled ({d:.0f}% drift): you held efficiency to the end — strong "
                "aerobic durability for this effort."
            )

    # Pacing positive.
    pace_delta = baseline.get("pace_delta_s_per_km")
    if isinstance(pace_delta, int | float) and pace_delta >= 5 and baseline.get("n", 0) >= 3:
        out.append(f"Ran ~{pace_delta:.0f} s/km faster than your similar-session average.")
    if not out:
        out.append("Solid, unremarkable session — right in line with your recent norms.")
    return out


def session_efficiency_series(activities: pl.DataFrame, hr_max: float) -> list[dict[str, Any]]:
    """Compact per-session list: date, type, distance, effort, efficiency factor.

    Feeds a list/table view and lets the coach scan recent sessions cheaply.
    """
    if activities.is_empty():
        return []
    out: list[dict[str, Any]] = []
    for r in activities.sort("start_time_local").to_dicts():
        avg_hr = _f(r.get("avg_hr"))
        dist = _f(r.get("distance_m"))
        out.append(
            {
                "activity_id": r.get("activity_id"),
                "day": str(r.get("day")) if r.get("day") else None,
                "type": r.get("activity_type"),
                "distance_mi": round(dist / M_PER_MILE, 2) if dist else None,
                "effort": intensity_band(avg_hr, hr_max) if avg_hr else "unknown",
                "efficiency_factor": efficiency_factor(
                    r.get("distance_m"), r.get("duration_s"), r.get("avg_hr")
                ),
            }
        )
    return out


# -- GPS route ----------------------------------------------------------------

RoutePoint = tuple[float, float, float | None, float | None]  # (lat, lon, speed_m_s, hr)
_ROUTE_MAX_POINTS = 600


def extract_route(details: dict[str, Any]) -> dict[str, Any]:
    """Parse a Garmin activity-details payload into a pace-colored GPS track.

    Prefers the per-sample ``activityDetailMetrics`` (which carry speed aligned
    with lat/lon); falls back to the ``geoPolylineDTO`` outline (lat/lon only,
    no per-point speed). Points without coordinates (indoor stretches / GPS
    drop-outs) are dropped. Returns ``{"has_gps": False}`` for treadmill / pool /
    strength activities that never recorded a position.

    Speed scale uses the 10th/90th percentiles so a single GPS-glitch spike can't
    wash out the fast/slow color range.
    """
    points = _points_from_metrics(details) or _points_from_polyline(details)
    if len(points) < 2:
        return {"has_gps": False}

    points = _downsample(points, _ROUTE_MAX_POINTS)
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    speeds = [p[2] for p in points if p[2] is not None]
    fast, slow = _speed_scale(speeds)
    pts = [
        [
            round(la, 5),
            round(lo, 5),
            (round(sp, 2) if sp is not None else None),
            (round(hr) if hr is not None else None),
        ]
        for la, lo, sp, hr in points
    ]
    return {
        "has_gps": True,
        "points": pts,
        "bounds": [[min(lats), min(lons)], [max(lats), max(lons)]],
        "fast_mps": fast,
        "slow_mps": slow,
    }


def _at(arr: list[Any], i: int) -> Any:
    return arr[i] if 0 <= i < len(arr) else None


def _points_from_metrics(details: dict[str, Any]) -> list[RoutePoint]:
    descs = details.get("metricDescriptors")
    metrics = details.get("activityDetailMetrics")
    if not isinstance(descs, list) or not isinstance(metrics, list):
        return []
    idx: dict[str, int] = {}
    for d in descs:
        if isinstance(d, dict) and d.get("key") is not None and d.get("metricsIndex") is not None:
            idx[str(d["key"])] = int(d["metricsIndex"])
    if "directLatitude" not in idx or "directLongitude" not in idx:
        return []
    i_lat, i_lon = idx["directLatitude"], idx["directLongitude"]
    i_spd, i_hr = idx.get("directSpeed"), idx.get("directHeartRate")
    out: list[RoutePoint] = []
    for m in metrics:
        arr = m.get("metrics") if isinstance(m, dict) else None
        if not isinstance(arr, list):
            continue
        lat, lon = _f(_at(arr, i_lat)), _f(_at(arr, i_lon))
        if lat is None or lon is None:
            continue
        spd = _f(_at(arr, i_spd)) if i_spd is not None else None
        hr = _f(_at(arr, i_hr)) if i_hr is not None else None
        out.append((lat, lon, spd, hr))
    return out


def _points_from_polyline(details: dict[str, Any]) -> list[RoutePoint]:
    dto = details.get("geoPolylineDTO")
    poly = dto.get("polyline") if isinstance(dto, dict) else None
    if not isinstance(poly, list):
        return []
    out: list[RoutePoint] = []
    for p in poly:
        if not isinstance(p, dict):
            continue
        lat = _f(p.get("lat"))
        lon = _f(p.get("lon") if p.get("lon") is not None else p.get("lng"))
        if lat is None or lon is None:
            continue
        out.append((lat, lon, _f(p.get("speed")), _f(p.get("heartRate"))))
    return out


def _downsample(points: list[RoutePoint], max_n: int) -> list[RoutePoint]:
    """Even sample of at most ``max_n`` points, keeping the first and last."""
    n = len(points)
    if n <= max_n:
        return points
    seen: set[int] = set()
    out: list[RoutePoint] = []
    for i in range(max_n):
        idx = round(i * (n - 1) / (max_n - 1))
        if idx not in seen:
            seen.add(idx)
            out.append(points[idx])
    return out


def _speed_scale(speeds: list[float]) -> tuple[float | None, float | None]:
    """Return (fast, slow) speeds as the p90 / p10 — robust to GPS spikes."""
    if not speeds:
        return None, None
    s = sorted(speeds)

    def pct(p: float) -> float:
        k = (len(s) - 1) * p
        lo = int(k)
        hi = min(lo + 1, len(s) - 1)
        return s[lo] + (s[hi] - s[lo]) * (k - lo)

    return round(pct(0.9), 2), round(pct(0.1), 2)
