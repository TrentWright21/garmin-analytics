"""Collector abstractions.

``GarminCollector`` is the swap boundary from the Phase 1 research: the rest
of the app only ever talks to this protocol. If Garmin breaks the unofficial
library again (as happened in March 2026), we write one new implementation
and nothing else changes. It also makes tests trivial — a fake collector is
just a class with these methods.

M2 exposes the handful of fetches needed to prove auth end-to-end; the M3
sync engine will grow this surface.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol


class CollectorError(Exception):
    """Base error for all collector failures."""


class CollectorAuthError(CollectorError):
    """Credentials rejected, MFA failed, or tokens unrecoverable."""


class CollectorConnectionError(CollectorError):
    """Network problem or Garmin-side outage. Usually transient."""


class CollectorRateLimitError(CollectorError):
    """Garmin asked us to back off. The sync engine should wait, not retry hot."""


class GarminCollector(Protocol):
    """Anything that can produce Garmin data for one account."""

    def connect(self) -> str:
        """Authenticate (reusing cached tokens when possible).

        Returns the account display name as a human-friendly proof of login.
        Raises CollectorAuthError / CollectorConnectionError on failure.
        """
        ...

    def daily_summary(self, day: date) -> dict[str, Any]:
        """Steps, calories, floors, resting HR, etc. for one calendar day."""
        ...

    def sleep(self, day: date) -> dict[str, Any]:
        """Sleep session + stages for the night ending on ``day``."""
        ...

    def hrv(self, day: date) -> dict[str, Any]:
        """Overnight HRV data for ``day``."""
        ...

    def activities(self, start: int = 0, limit: int = 20) -> list[dict[str, Any]]:
        """Most recent activities, newest first."""
        ...

    def fetch_daily(self, endpoint: str, day: date) -> Any:
        """Fetch one registered daily endpoint (see collectors.endpoints)."""
        ...

    def fetch_snapshot(self, endpoint: str) -> Any:
        """Fetch one registered snapshot endpoint (PRs, race predictions)."""
        ...

    def activities_by_date(self, start: date, end: date) -> list[dict[str, Any]]:
        """All activities whose start date falls in [start, end]."""
        ...

    def activity_details(self, activity_id: int) -> dict[str, Any]:
        """Per-sample detail for one activity: GPS track, speed, HR streams.

        Fetched on demand (not in the daily sync) — one call per activity the
        user actually opens. Raises the CollectorError hierarchy on failure.
        """
        ...
