"""Auth tests: token signing, login exchange, middleware enforcement, fail-closed.

Auth is OFF unless GA_APP_PASSWORD is set, so the rest of the suite runs
unauthenticated. These tests set it (and, for the fail-closed case, prod) via
monkeypatch + a settings-cache reset, mirroring the temp-DB pattern elsewhere.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.db.engine as db
from app import auth
from app.config import Settings, get_settings

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture(autouse=True)
def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GA_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    get_settings.cache_clear()
    db.reset_engine_for_tests()
    yield
    get_settings.cache_clear()
    db.reset_engine_for_tests()


def _client() -> TestClient:
    from app.main import app

    return TestClient(app)


# -- token unit tests --------------------------------------------------------


def test_mint_and_verify_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GA_APP_PASSWORD", PASSWORD)
    get_settings.cache_clear()
    s = get_settings()
    token = auth.mint_token(s)
    assert auth.verify_token(s, token)
    assert not auth.verify_token(s, token + "x")  # tampered signature
    assert not auth.verify_token(s, None)


def test_token_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GA_APP_PASSWORD", PASSWORD)
    get_settings.cache_clear()
    s = get_settings()
    past = time.time() - auth.TOKEN_TTL_SECONDS - 10
    stale = auth.mint_token(s, now=past)
    assert not auth.verify_token(s, stale)


def test_token_invalid_under_different_password() -> None:
    a = Settings(app_password="one")  # type: ignore[arg-type]
    b = Settings(app_password="two")  # type: ignore[arg-type]
    assert not auth.verify_token(b, auth.mint_token(a))


# -- middleware / login integration -----------------------------------------


def test_api_open_when_no_password() -> None:
    """No GA_APP_PASSWORD => auth disabled => endpoints answer without a token."""
    c = _client()
    assert c.get("/api/auth/status").json() == {"auth_required": False}
    assert c.get("/api/metrics/daily?days=1").status_code == 200


def test_api_requires_token_when_password_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GA_APP_PASSWORD", PASSWORD)
    get_settings.cache_clear()
    c = _client()

    assert c.get("/api/auth/status").json() == {"auth_required": True}
    # Protected endpoint rejects an anonymous request...
    assert c.get("/api/metrics/daily?days=1").status_code == 401
    # ...wrong password is rejected...
    assert c.post("/api/login", json={"password": "nope"}).status_code == 401
    # ...correct password mints a token that unlocks the API.
    token = c.post("/api/login", json={"password": PASSWORD}).json()["token"]
    ok = c.get("/api/metrics/daily?days=1", headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200


def test_health_always_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GA_APP_PASSWORD", PASSWORD)
    get_settings.cache_clear()
    assert _client().get("/health").status_code == 200


def test_prod_without_password_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The app must refuse to start in prod with no login password."""
    monkeypatch.setenv("GA_ENVIRONMENT", "prod")
    monkeypatch.delenv("GA_APP_PASSWORD", raising=False)
    get_settings.cache_clear()
    from app.main import app

    with pytest.raises(RuntimeError, match="GA_APP_PASSWORD"), TestClient(app):
        pass


def test_watch_feed_fail_closed_in_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    """In prod, the watch feed refuses when GA_WATCH_TOKEN is unset."""
    monkeypatch.setenv("GA_ENVIRONMENT", "prod")
    monkeypatch.setenv("GA_APP_PASSWORD", PASSWORD)  # so the app can start
    monkeypatch.delenv("GA_WATCH_TOKEN", raising=False)
    get_settings.cache_clear()
    c = _client()
    assert c.get("/api/watch/briefing").status_code == 401
