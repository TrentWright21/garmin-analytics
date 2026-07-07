"""Sync engine: Garmin -> raw layer -> normalized tables.

Design choices:

* Gentle by default: a short pause between API calls, and a hard stop on
  rate-limit errors (finish tomorrow rather than hammer Garmin today).
* Per-endpoint failure isolation: one broken endpoint never blocks the rest.
* Normalization always re-derives from the raw layer's latest payloads, so
  re-running a day is always safe and idempotent.
"""

from __future__ import annotations

import json
import time
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.base import (
    CollectorConnectionError,
    CollectorRateLimitError,
    GarminCollector,
)
from app.collectors.endpoints import DAILY_ENDPOINTS, SNAPSHOT_ENDPOINTS
from app.collectors.weather import WeatherError, WeatherProvider
from app.config import get_app_config
from app.db.engine import latest_raw, latest_raw_any, session_scope, store_raw
from app.db.models.core import RawApiData
from app.logging import get_logger
from app.normalize.mappers import build_activity, build_daily_metrics
from app.normalize.weather import build_daily_weather, parse_weather_daily

log = get_logger(__name__)


class SyncEngine:
    def __init__(
        self,
        collector: GarminCollector,
        pause_s: float = 0.4,
        *,
        weather: WeatherProvider | None = None,
        weather_location: tuple[float, float] | None = None,
    ) -> None:
        self._collector = collector
        self._pause_s = pause_s
        # Weather is optional and best-effort: a weather failure never aborts a
        # Garmin sync. Absent provider/location = weather simply not collected.
        self._weather = weather
        self._weather_location = weather_location

    # -- public --------------------------------------------------------

    def sync_range(self, start: date, end: date) -> dict[str, int]:
        """Sync every day in [start, end], oldest first. Returns counters."""
        self._collector.connect()
        stats = {"days": 0, "raw_rows": 0, "errors": 0, "activities": 0}

        day = start
        while day <= end:
            try:
                stats["raw_rows"] += self._sync_day(day)
            except CollectorRateLimitError:
                log.warning("sync.rate_limited", stopped_at=str(day))
                break
            stats["days"] += 1
            day += timedelta(days=1)

        stats["activities"] = self._sync_activities(start, end)
        self._sync_snapshots()
        self._sync_weather(start, end)
        self._normalize_range(start, end)
        log.info("sync.finished", **stats)
        return stats

    def sync_recent(self, days: int = 2) -> dict[str, int]:
        """Daily job: re-sync the last N days (Garmin revises recent data)."""
        today = date.today()
        return self.sync_range(today - timedelta(days=days - 1), today)

    # -- collection ------------------------------------------------------

    def _sync_day(self, day: date) -> int:
        new_rows = 0
        for endpoint in DAILY_ENDPOINTS:
            try:
                payload = self._collector.fetch_daily(endpoint, day)
            except CollectorRateLimitError:
                raise  # caller stops the whole run
            except CollectorConnectionError as exc:
                log.warning("sync.endpoint_failed", endpoint=endpoint, day=str(day), err=str(exc))
                continue
            if payload in (None, {}, []):
                continue
            with session_scope() as s:
                if store_raw(s, endpoint, day, payload):
                    new_rows += 1
            time.sleep(self._pause_s)
        log.info("sync.day_done", day=str(day), new_rows=new_rows)
        return new_rows

    def _sync_activities(self, start: date, end: date) -> int:
        try:
            acts = self._collector.activities_by_date(start, end)
        except CollectorConnectionError as exc:
            log.warning("sync.activities_failed", err=str(exc))
            return 0
        count = 0
        with session_scope() as s:
            for payload in acts or []:
                act_day = None
                if isinstance(payload.get("startTimeLocal"), str):
                    act_day = payload["startTimeLocal"][:10]
                stored = store_raw(
                    s, "activity", date.fromisoformat(act_day) if act_day else None, payload
                )
                count += int(stored)
        return count

    def _sync_snapshots(self) -> None:
        for endpoint in SNAPSHOT_ENDPOINTS:
            try:
                payload = self._collector.fetch_snapshot(endpoint)
            except CollectorConnectionError:
                continue
            except CollectorRateLimitError:
                return
            if payload in (None, {}, []):
                continue
            with session_scope() as s:
                store_raw(s, endpoint, date.today(), payload)
            time.sleep(self._pause_s)

    def _sync_weather(self, start: date, end: date) -> None:
        """Fetch local weather into the raw layer. Best-effort, never fatal.

        Two calls: the archive (historical daily for the synced range) and the
        forecast (recent past + upcoming days — this is what fills *today*, since
        Open-Meteo's archive lags a few days). Either failing just logs a warning.
        """
        if self._weather is None or self._weather_location is None:
            return
        lat, lon = self._weather_location
        try:
            history = self._weather.daily_history(lat, lon, start, end)
            with session_scope() as s:
                store_raw(s, "weather_archive", end, history)
        except WeatherError as exc:
            log.warning("sync.weather_history_failed", err=str(exc))
        try:
            forecast = self._weather.forecast(lat, lon, days=7)
            with session_scope() as s:
                store_raw(s, "weather_forecast", date.today(), forecast)
        except WeatherError as exc:
            log.warning("sync.weather_forecast_failed", err=str(exc))

    # -- normalization -----------------------------------------------------

    def _normalize_range(self, start: date, end: date) -> None:
        normalize_range(start, end)


def build_sync_engine(collector: GarminCollector) -> SyncEngine:
    """Wrap a Garmin collector with the Open-Meteo weather provider + location.

    The single place the weather provider is wired from config, so the scheduler,
    the ``/api/sync`` route, and the CLI all sync the same weather source. The
    collector is passed in (not constructed here) so each caller keeps its own
    ``GarminConnectCollector`` reference — the seam that tests monkeypatch.
    """
    from app.collectors.weather import OpenMeteoProvider

    cfg = get_app_config()
    return SyncEngine(
        collector,
        weather=OpenMeteoProvider(),
        weather_location=(cfg.location.latitude, cfg.location.longitude),
    )


def normalize_range(start: date, end: date) -> None:
    """Rebuild the normalized layer for [start, end] from the raw layer.

    The normalized tables are a pure projection of raw, so this is always safe
    to re-run — e.g. after a mapper change — without any Garmin calls.
    """
    with session_scope() as s:
        day = start
        while day <= end:
            raw = {ep: p for ep in DAILY_ENDPOINTS if (p := latest_raw(s, ep, day)) is not None}
            if raw:
                row = build_daily_metrics(day, raw)
                s.merge(row)  # normalized layer is a projection; merge is fine
            day += timedelta(days=1)

        # activities: rebuild from raw payloads in range
        rows = s.execute(
            select(RawApiData).where(
                RawApiData.endpoint == "activity",
                RawApiData.metric_date >= start,
                RawApiData.metric_date <= end,
            )
        ).scalars()
        for r in rows:
            act = build_activity(json.loads(r.payload_json))
            if act:
                s.merge(act)

        normalize_weather(s)


def normalize_weather(session: Session) -> None:
    """Rebuild ``daily_weather`` from the latest stored weather payloads.

    Each weather payload spans many days, so we take the newest archive and
    forecast payloads and materialize every day they contain. Forecast is merged
    last so its fresher values win for the recent days both cover. Pure raw ->
    projection, so it re-runs safely (renormalize, no Garmin/network calls).
    """
    merged: dict[date, dict[str, float | None]] = {}
    for endpoint in ("weather_archive", "weather_forecast"):
        payload = latest_raw_any(session, endpoint)
        if payload:
            merged.update(parse_weather_daily(payload))
    for day, data in merged.items():
        session.merge(build_daily_weather(day, data))
