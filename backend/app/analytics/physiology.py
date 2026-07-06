"""Shared exercise-physiology primitives used across the analytics modules.

Pure functions and constants only — no DB, no Polars side effects — so the
fitness, readiness, and session engines can all lean on ONE definition of a
heart-rate zone, one HR-max estimate, and one training-impulse formula instead
of each re-deriving them slightly differently.

Everything here is deliberately transparent (documented thresholds, cited where
a number comes from a standard) so the dashboard and the AI coach can explain
*why* a value is what it is, which is the whole point of this platform.
"""

from __future__ import annotations

import math
from typing import Any

import polars as pl

# Absolute fallback when we have never observed a max HR and no configured value
# exists. Deliberately conservative; a real measured/observed max always wins.
DEFAULT_HR_MAX = 190.0

# 5-zone %HRmax model (Garmin / Coggan style). Lower bound of each zone as a
# fraction of HR max. Zone 1 is everything below Z2's floor.
HR_ZONE_FLOORS: tuple[tuple[int, float], ...] = (
    (5, 0.90),  # anaerobic / VO2max
    (4, 0.80),  # threshold
    (3, 0.70),  # aerobic / tempo
    (2, 0.60),  # easy
    (1, 0.00),  # recovery
)

# Intensity bands applied to a *session-average* HR (which sits well below the
# session's peak). A genuinely easy run averages ~70% HRmax; a tempo ~80-87%;
# intervals average ~88%+. These are the boundaries for aerobic/threshold/
# anaerobic classification of a whole session by its mean HR.
EASY_CEIL = 0.76
HARD_FLOOR = 0.87


def _f(value: Any) -> float | None:
    """Coerce a (union-typed) Polars scalar to float | None for arithmetic."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def estimate_hr_max(
    activities: pl.DataFrame | None = None,
    daily: pl.DataFrame | None = None,
    configured: float | None = None,
) -> float:
    """Best available HR max: configured value, else the highest ever observed.

    We do not know the user's age, so we cannot use 220-age. Instead we take the
    single highest heart rate the watch has ever recorded (in an activity or as a
    daily max), which for anyone who trains hard is a better estimate than a
    formula. Falls back to ``DEFAULT_HR_MAX`` only when nothing has been observed.

    A user-configured true max (from a max-effort test) should always be passed
    as ``configured`` and takes precedence — that is the accuracy improvement.
    """
    if configured is not None and configured > 0:
        return float(configured)

    observed: list[float] = []
    for df, col in ((activities, "max_hr"), (daily, "max_hr")):
        if df is not None and not df.is_empty() and col in df.columns:
            top = _f(df[col].max())
            if top is not None and top > 0:
                observed.append(top)
    return max(observed) if observed else DEFAULT_HR_MAX


def hr_zone(avg_hr: float, hr_max: float) -> int:
    """Zone 1-5 for a heart rate, given HR max. Guards against a zero max."""
    if hr_max <= 0:
        return 1
    frac = avg_hr / hr_max
    for zone, floor in HR_ZONE_FLOORS:
        if frac >= floor:
            return zone
    return 1


def intensity_band(avg_hr: float, hr_max: float) -> str:
    """Classify a session by its mean HR into easy / moderate / hard.

    "easy" is aerobic base (Z1-2), "moderate" is tempo/threshold territory (Z3),
    "hard" is threshold-and-above where anaerobic contribution is meaningful.
    """
    if hr_max <= 0:
        return "unknown"
    frac = avg_hr / hr_max
    if frac < EASY_CEIL:
        return "easy"
    if frac >= HARD_FLOOR:
        return "hard"
    return "moderate"


def trimp(duration_min: float, avg_hr: float, hr_rest: float, hr_max: float) -> float | None:
    """Banister TRIMP: an HR-based training-impulse load for one session.

    ``load = duration_min * hr_reserve_frac * 0.64 * e^(1.92 * hr_reserve_frac)``

    Uses the generic (sex-averaged) weighting constant. Returns None when the
    inputs cannot yield a valid heart-rate reserve fraction. This is our fallback
    when Garmin did not attach its own training-load value to an activity.
    """
    if duration_min <= 0 or hr_max <= hr_rest:
        return None
    hrr = (avg_hr - hr_rest) / (hr_max - hr_rest)
    hrr = max(0.0, min(1.0, hrr))
    if hrr == 0.0:
        return 0.0
    return round(duration_min * hrr * 0.64 * math.exp(1.92 * hrr), 1)
