"""M2 tests: collector error translation, missing-credential handling, CLI.

No real Garmin calls — the library client is replaced with fakes via the
injectable ``client_factory``. Real auth is verified manually with
``python -m app.cli test-auth``.
"""

from datetime import date
from pathlib import Path
from typing import Any

import pytest
from garminconnect import (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from app.cli import cmd_test_auth
from app.collectors.base import (
    CollectorAuthError,
    CollectorConnectionError,
    CollectorRateLimitError,
)
from app.collectors.garmin_connect import GarminConnectCollector
from app.config import Settings


class FakeGarmin:
    """Stands in for garminconnect.Garmin."""

    login_error: Exception | None = None
    call_error: Exception | None = None

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    def login(self, tokenstore: str | None = None) -> tuple[None, None]:
        if self.login_error:
            raise self.login_error
        self.tokenstore = tokenstore
        return (None, None)

    def get_full_name(self) -> str:
        return "Test Runner"

    def get_stats(self, day: str) -> dict[str, Any]:
        if self.call_error:
            raise self.call_error
        return {"totalSteps": 8500, "restingHeartRate": 52, "calendarDate": day}

    def get_sleep_data(self, day: str) -> dict[str, Any]:
        return {"dailySleepDTO": {"calendarDate": day}}

    def get_hrv_data(self, day: str) -> dict[str, Any]:
        return {"hrvSummary": {"calendarDate": day}}

    def get_activities(self, start: int, limit: int) -> list[dict[str, Any]]:
        return [{"activityName": "Morning Run", "startTimeLocal": "2026-07-04 06:10"}]


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "garmin_email": "t@example.com",
        "garmin_password": "pw",
        "garmin_tokens_dir": tmp_path / "tokens",
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def make_collector(tmp_path: Path, fake_cls: type[FakeGarmin] = FakeGarmin, **overrides: Any):
    return GarminConnectCollector(
        make_settings(tmp_path, **overrides),
        mfa_prompt=lambda: "123456",
        client_factory=fake_cls,
    )


class TestConnect:
    def test_happy_path_creates_token_dir(self, tmp_path: Path) -> None:
        c = make_collector(tmp_path)
        assert c.connect() == "Test Runner"
        assert (tmp_path / "tokens").is_dir()

    def test_missing_credentials(self, tmp_path: Path) -> None:
        c = make_collector(tmp_path, garmin_email=None, garmin_password=None)
        with pytest.raises(CollectorAuthError, match="not set"):
            c.connect()

    def test_bad_password_translates(self, tmp_path: Path) -> None:
        class Rejecting(FakeGarmin):
            login_error = GarminConnectAuthenticationError("401")

        with pytest.raises(CollectorAuthError):
            make_collector(tmp_path, Rejecting).connect()

    def test_rate_limit_translates(self, tmp_path: Path) -> None:
        class Limited(FakeGarmin):
            login_error = GarminConnectTooManyRequestsError("429")

        with pytest.raises(CollectorRateLimitError):
            make_collector(tmp_path, Limited).connect()


class TestFetches:
    def test_daily_summary(self, tmp_path: Path) -> None:
        c = make_collector(tmp_path)
        data = c.daily_summary(date(2026, 7, 4))
        assert data["totalSteps"] == 8500

    def test_connection_error_translates_on_fetch(self, tmp_path: Path) -> None:
        class Flaky(FakeGarmin):
            call_error = GarminConnectConnectionError("boom")

        c = make_collector(tmp_path, Flaky)
        with pytest.raises(CollectorConnectionError):
            c.daily_summary(date(2026, 7, 4))

    def test_lazy_connect_on_first_fetch(self, tmp_path: Path) -> None:
        c = make_collector(tmp_path)
        # no explicit connect() — fetch should trigger it
        assert c.activities(limit=1)[0]["activityName"] == "Morning Run"


class TestCli:
    def test_test_auth_success_exit_code(self, tmp_path: Path, capsys: Any) -> None:
        assert cmd_test_auth(make_collector(tmp_path)) == 0
        out = capsys.readouterr().out
        assert "Logged in as: Test Runner" in out
        assert "steps=8500" in out

    def test_test_auth_bad_login_exit_code(self, tmp_path: Path) -> None:
        class Rejecting(FakeGarmin):
            login_error = GarminConnectAuthenticationError("401")

        assert cmd_test_auth(make_collector(tmp_path, Rejecting)) == 1
