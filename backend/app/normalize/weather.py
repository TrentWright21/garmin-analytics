"""Open-Meteo JSON -> normalized daily weather. Pure functions.

Open-Meteo gives daily aggregates for temperature/wind but only *hourly*
humidity and dew point. For a runner the 24-hour mean humidity is misleading —
what matters is how muggy it is at the hottest part of the day. So for each day
we sample humidity and dew point at that day's hottest hour rather than
averaging across the cool night.

Kept separate from ``mappers.py`` (which maps Garmin payloads) because this is a
different data source; both feed the same normalize step in the sync engine.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.db.models.weather import DailyWeather


def _num(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _day_of(iso: Any) -> date | None:
    """Parse a ``YYYY-MM-DD`` (or ``...THH:MM``) string to a date, defensively."""
    if not isinstance(iso, str) or len(iso) < 10:
        return None
    try:
        return date.fromisoformat(iso[:10])
    except ValueError:
        return None


def _hottest_hour_by_day(hourly: dict[str, Any]) -> dict[date, dict[str, float | None]]:
    """For each day, humidity + dew point sampled at its hottest hour."""
    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or []
    hums = hourly.get("relative_humidity_2m") or []
    dews = hourly.get("dew_point_2m") or []

    # day -> (hottest temp seen, humidity there, dew point there)
    best: dict[date, tuple[float, float | None, float | None]] = {}
    for i, raw_time in enumerate(times):
        day = _day_of(raw_time)
        if day is None:
            continue
        temp = _num(temps[i]) if i < len(temps) else None
        temp_key = temp if temp is not None else float("-inf")
        if day not in best or temp_key > best[day][0]:
            hum = _num(hums[i]) if i < len(hums) else None
            dew = _num(dews[i]) if i < len(dews) else None
            best[day] = (temp_key, hum, dew)
    return {d: {"humidity_pct": h, "dew_point_c": dp} for d, (_t, h, dp) in best.items()}


def parse_weather_daily(payload: dict[str, Any]) -> dict[date, dict[str, float | None]]:
    """Verbatim Open-Meteo JSON -> ``{day: {field: value}}`` (Celsius, km/h).

    Tolerates missing sections and ragged arrays: an absent field is simply
    null for that day, never an error.
    """
    if not isinstance(payload, dict):
        return {}
    daily = payload.get("daily") or {}
    hourly = payload.get("hourly") or {}

    times = daily.get("time") or []
    highs = daily.get("temperature_2m_max") or []
    lows = daily.get("temperature_2m_min") or []
    app_highs = daily.get("apparent_temperature_max") or []
    winds = daily.get("wind_speed_10m_max") or []

    hourly_by_day = _hottest_hour_by_day(hourly) if isinstance(hourly, dict) else {}

    out: dict[date, dict[str, float | None]] = {}
    for i, raw_time in enumerate(times):
        day = _day_of(raw_time)
        if day is None:
            continue
        row: dict[str, float | None] = {
            "temp_high_c": _num(highs[i]) if i < len(highs) else None,
            "temp_low_c": _num(lows[i]) if i < len(lows) else None,
            "apparent_high_c": _num(app_highs[i]) if i < len(app_highs) else None,
            "wind_kph": _num(winds[i]) if i < len(winds) else None,
            "humidity_pct": None,
            "dew_point_c": None,
        }
        row.update(hourly_by_day.get(day, {}))
        out[day] = row
    return out


def build_daily_weather(day: date, data: dict[str, float | None]) -> DailyWeather:
    """One parsed day -> a DailyWeather row (for ``session.merge``)."""
    return DailyWeather(
        day=day,
        temp_high_c=data.get("temp_high_c"),
        temp_low_c=data.get("temp_low_c"),
        apparent_high_c=data.get("apparent_high_c"),
        humidity_pct=data.get("humidity_pct"),
        dew_point_c=data.get("dew_point_c"),
        wind_kph=data.get("wind_kph"),
    )
