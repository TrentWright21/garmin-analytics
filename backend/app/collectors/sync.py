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

from app.collectors.base import (
    CollectorConnectionError,
    CollectorRateLimitError,
    GarminCollector,
)
from app.collectors.endpoints import DAILY_ENDPOINTS, SNAPSHOT_ENDPOINTS
from app.db.engine import latest_raw, session_scope, store_raw
from app.db.models.core import RawApiData
from app.logging import get_logger
from app.normalize.mappers import build_activity, build_daily_metrics

log = get_logger(__name__)


class SyncEngine:
    def __init__(self, collector: GarminCollector, pause_s: float = 0.4) -> None:
        self._collector = collector
        self._pause_s = pause_s

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

    # -- normalization -----------------------------------------------------

    def _normalize_range(self, start: date, end: date) -> None:
        normalize_range(start, end)


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
