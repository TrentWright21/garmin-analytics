"""Weather provider (M9).

Weather is a SEPARATE external source from Garmin, so it deliberately does not
go through ``GarminCollector`` — that protocol is the Garmin swap boundary and
its invariant ("nothing outside collectors imports garminconnect") is unrelated
here. This module is the analogous swap boundary for weather: the rest of the
app talks to the ``WeatherProvider`` protocol, and a fake provider is trivial to
inject in tests.

Default implementation is **Open-Meteo**: free, no API key, and it exposes the
fields a hot-weather runner actually needs — temperature, apparent ("feels
like") temperature, relative humidity, and dew point (the real heat-stress
signal), historically and as a forecast. Values are traceable to a documented,
physically-modelled source (ECMWF/GFS), satisfying the scientific-integrity bar.

Returned payloads are the verbatim Open-Meteo JSON; parsing/aggregation lives in
``app.normalize.weather`` so it is pure and re-derivable from the raw layer.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol, cast

import httpx

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Daily aggregates Open-Meteo computes for us.
_DAILY_VARS = "temperature_2m_max,temperature_2m_min,apparent_temperature_max,wind_speed_10m_max"
# Humidity + dew point are only offered hourly; we average them to a day in the
# pure parser. Temperature is included so the parser can pick the hottest hour's
# humidity/dew point (what actually matters for an afternoon run).
_HOURLY_VARS = "relative_humidity_2m,dew_point_2m,temperature_2m"

_TIMEOUT_S = 20.0


class WeatherError(Exception):
    """Any failure fetching weather. Callers treat weather as best-effort."""


class WeatherProvider(Protocol):
    """Anything that can produce daily weather for one lat/lon."""

    def daily_history(
        self, latitude: float, longitude: float, start: date, end: date
    ) -> dict[str, Any]:
        """Historical daily + hourly weather for [start, end]. Verbatim JSON."""
        ...

    def forecast(self, latitude: float, longitude: float, days: int = 7) -> dict[str, Any]:
        """Forecast (plus a couple of recent past days) as verbatim JSON."""
        ...


class OpenMeteoProvider:
    """Open-Meteo implementation. No credentials required.

    ``transport`` is an injection seam for tests (pass an ``httpx.MockTransport``
    to avoid the network); in production it is None and httpx uses the default.
    """

    def __init__(
        self, timeout_s: float = _TIMEOUT_S, transport: httpx.BaseTransport | None = None
    ) -> None:
        self._timeout_s = timeout_s
        self._transport = transport

    def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=self._timeout_s, transport=self._transport) as client:
                resp = client.get(url, params=params)
                resp.raise_for_status()
                return cast(dict[str, Any], resp.json())
        except httpx.HTTPError as exc:  # network, timeout, or non-2xx status
            raise WeatherError(f"Open-Meteo request failed: {exc}") from exc

    def daily_history(
        self, latitude: float, longitude: float, start: date, end: date
    ) -> dict[str, Any]:
        return self._get(
            ARCHIVE_URL,
            {
                "latitude": latitude,
                "longitude": longitude,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "daily": _DAILY_VARS,
                "hourly": _HOURLY_VARS,
                "timezone": "auto",
            },
        )

    def forecast(self, latitude: float, longitude: float, days: int = 7) -> dict[str, Any]:
        return self._get(
            FORECAST_URL,
            {
                "latitude": latitude,
                "longitude": longitude,
                "daily": _DAILY_VARS,
                "hourly": _HOURLY_VARS,
                "forecast_days": max(1, min(16, days)),
                "past_days": 5,  # bridges the archive API's few-day publication lag
                "timezone": "auto",
            },
        )
