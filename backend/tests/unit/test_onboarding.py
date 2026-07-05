"""First-run onboarding: friendly guidance instead of tracebacks.

These tests pin the behavior a brand-new user hits before their .env is set
up: every Garmin-touching CLI command must explain what to do in plain
English and exit nonzero — never dump a stack trace.
"""

from __future__ import annotations

import pytest

from app import cli
from app.collectors.base import (
    CollectorAuthError,
    CollectorConnectionError,
    CollectorRateLimitError,
)
from app.config import Settings


def settings_with(email: str | None = None, password: str | None = None) -> Settings:
    """Settings isolated from the developer's real .env file."""
    return Settings(garmin_email=email, garmin_password=password, _env_file=None)


class TestCredentialsProblem:
    def test_unset_credentials_are_flagged(self) -> None:
        problem = cli.credentials_problem(settings_with())
        assert problem is not None
        assert ".env" in problem

    def test_placeholder_email_is_flagged(self) -> None:
        problem = cli.credentials_problem(settings_with("you@example.com", "s3cret"))
        assert problem is not None
        assert "placeholder" in problem

    def test_placeholder_password_is_flagged(self) -> None:
        assert cli.credentials_problem(settings_with("me@real.com", "changeme")) is not None

    def test_real_credentials_pass(self) -> None:
        assert cli.credentials_problem(settings_with("me@real.com", "hunter2")) is None


class TestCliGuard:
    """Without credentials, commands print setup help and exit 1."""

    @pytest.fixture(autouse=True)
    def no_creds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cli, "get_settings", settings_with)

    @pytest.mark.parametrize("command", ["test-auth", "sync", "backfill"])
    def test_commands_explain_setup_instead_of_crashing(
        self, command: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.main([command]) == 1
        err = capsys.readouterr().err
        assert "setup.ps1" in err
        assert "GA_GARMIN_EMAIL" in err
        assert "Traceback" not in err


class _ConnectFails:
    """Collector stub whose login always fails a given way."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def connect(self) -> str:
        raise self._exc


class TestSyncLoginFailures:
    """With credentials present, login failures still exit with plain English."""

    @pytest.fixture(autouse=True)
    def real_creds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cli, "get_settings", lambda: settings_with("me@real.com", "hunter2"))

    def _patch_collector(self, monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
        monkeypatch.setattr(cli, "GarminConnectCollector", lambda settings: _ConnectFails(exc))

    def test_bad_password_prints_setup_help(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._patch_collector(monkeypatch, CollectorAuthError("rejected"))
        assert cli.main(["sync"]) == 1
        err = capsys.readouterr().err
        assert "login failed" in err.lower()
        assert "setup.ps1" in err

    def test_rate_limited_login_says_wait(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._patch_collector(monkeypatch, CollectorRateLimitError("429"))
        assert cli.main(["backfill"]) == 3
        err = capsys.readouterr().err
        assert "rate-limiting" in err
        assert "Traceback" not in err

    def test_connection_failure_is_friendly(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._patch_collector(monkeypatch, CollectorConnectionError("dns down"))
        assert cli.main(["sync"]) == 2
        err = capsys.readouterr().err
        assert "internet connection" in err
