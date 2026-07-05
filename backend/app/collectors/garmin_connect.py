"""GarminCollector implementation backed by the python-garminconnect library.

Behavior:

* First ever login: email + password (+ MFA code prompt if your account has
  it enabled). Resulting OAuth tokens are saved to ``settings.garmin_tokens_dir``.
* Every run after that: tokens are reused silently — no password sent, no MFA.
  The library auto-refreshes tokens and self-heals if cached ones go stale.
* All library/network exceptions are translated into our CollectorError
  hierarchy so the rest of the app never imports ``garminconnect`` directly.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any, cast

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from app.collectors.base import (
    CollectorAuthError,
    CollectorConnectionError,
    CollectorError,
    CollectorRateLimitError,
)
from app.collectors.endpoints import DAILY_ENDPOINTS, SNAPSHOT_ENDPOINTS
from app.config import Settings
from app.logging import get_logger

log = get_logger(__name__)


def _prompt_mfa() -> str:
    """Ask the human for their MFA code on first login."""
    return input("Garmin MFA code: ").strip()


class GarminConnectCollector:
    """Production collector talking to Garmin Connect."""

    def __init__(
        self,
        settings: Settings,
        mfa_prompt: Callable[[], str] = _prompt_mfa,
        client_factory: Callable[..., Garmin] = Garmin,
    ) -> None:
        self._settings = settings
        self._mfa_prompt = mfa_prompt
        self._client_factory = client_factory  # injectable for tests
        self._client: Garmin | None = None

    # -- auth -----------------------------------------------------------

    def connect(self) -> str:
        if self._client is not None:
            return self._display_name()

        tokens_dir = self._settings.garmin_tokens_dir
        tokens_dir.mkdir(parents=True, exist_ok=True)

        email = self._settings.garmin_email
        password = self._settings.garmin_password
        if email is None or password is None:
            raise CollectorAuthError(
                "GA_GARMIN_EMAIL / GA_GARMIN_PASSWORD are not set. Fill them in your .env file."
            )

        client = self._client_factory(
            email=email.get_secret_value(),
            password=password.get_secret_value(),
            prompt_mfa=self._mfa_prompt,
        )
        try:
            client.login(tokenstore=str(tokens_dir))
        except GarminConnectAuthenticationError as exc:
            raise CollectorAuthError(f"Garmin rejected the login: {exc}") from exc
        except GarminConnectTooManyRequestsError as exc:
            raise CollectorRateLimitError(str(exc)) from exc
        except GarminConnectConnectionError as exc:
            raise CollectorConnectionError(str(exc)) from exc

        self._client = client
        name = self._display_name()
        log.info("garmin.connected", account=name, tokens_dir=str(tokens_dir))
        return name

    def _require_client(self) -> Garmin:
        if self._client is None:
            self.connect()
        assert self._client is not None
        return self._client

    def _display_name(self) -> str:
        try:
            return str(self._require_client().get_full_name())
        except CollectorError:
            raise
        except Exception:  # name is cosmetic, never fatal
            return "(unknown)"

    # -- fetches ---------------------------------------------------------

    def daily_summary(self, day: date) -> dict[str, Any]:
        return cast(dict[str, Any], self._call("get_stats", day.isoformat()))

    def sleep(self, day: date) -> dict[str, Any]:
        return cast(dict[str, Any], self._call("get_sleep_data", day.isoformat()))

    def hrv(self, day: date) -> dict[str, Any]:
        return cast(dict[str, Any], self._call("get_hrv_data", day.isoformat()))

    def activities(self, start: int = 0, limit: int = 20) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], self._call("get_activities", start, limit))

    # -- plumbing ---------------------------------------------------------

    def _call(self, method: str, *args: Any) -> Any:
        """Invoke a garminconnect method with unified error translation.

        The library already retries transient failures internally
        (retry_attempts=3 with backoff), so we don't re-retry here — we just
        classify what comes out so the sync engine can decide what to do.
        """
        client = self._require_client()
        try:
            result = getattr(client, method)(*args)
        except GarminConnectTooManyRequestsError as exc:
            raise CollectorRateLimitError(f"{method}: {exc}") from exc
        except GarminConnectAuthenticationError as exc:
            raise CollectorAuthError(f"{method}: {exc}") from exc
        except GarminConnectConnectionError as exc:
            raise CollectorConnectionError(f"{method}: {exc}") from exc
        log.debug("garmin.fetched", method=method, args=args)
        return result

    def fetch_daily(self, endpoint: str, day: date) -> Any:
        method = DAILY_ENDPOINTS[endpoint]
        return self._call(method, day.isoformat())

    def fetch_snapshot(self, endpoint: str) -> Any:
        method = SNAPSHOT_ENDPOINTS[endpoint]
        return self._call(method)

    def activities_by_date(self, start: date, end: date) -> list[dict[str, Any]]:
        return cast(
            list[dict[str, Any]],
            self._call("get_activities_by_date", start.isoformat(), end.isoformat()),
        )
