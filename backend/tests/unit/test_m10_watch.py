"""M10 tests: the compact Connect IQ watch feed.

Exercises the flat projection (build_watch_briefing) and the /api/watch/briefing
route, including the opt-in token guard. Runs against a temp-file SQLite DB.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.db.engine as db
from app.api.routes import briefing as briefing_route
from app.config import AppConfig, EventConfig, LocationConfig
from app.db.models.core import Activity
from app.db.models.weather import DailyWeather

TODAY = date.today()


@pytest.fixture(autouse=True)
def temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GA_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    from app.config import get_settings

    get_settings.cache_clear()
    db.reset_engine_for_tests()
    yield
    get_settings.cache_clear()
    db.reset_engine_for_tests()


def _seed() -> None:
    with db.session_scope() as s:
        for i in range(10):
            d = TODAY - timedelta(days=10 - i)
            s.merge(
                Activity(
                    activity_id=3000 + i,
                    start_time_local=datetime(d.year, d.month, d.day, 6),
                    day=d,
                    activity_type="running",
                    name=f"run {i}",
                    distance_m=10000.0,
                    duration_s=3000.0,
                    avg_hr=150.0,
                    training_load=100.0,
                )
            )
        s.merge(DailyWeather(day=TODAY, temp_high_c=34.0, dew_point_c=24.5, apparent_high_c=40.0))


def _cfg() -> AppConfig:
    return AppConfig(
        location=LocationConfig(name="Hartselle, AL"),
        event=EventConfig(name="Mount Whitney", date=TODAY + timedelta(days=26), kind="climb"),
    )


def _client() -> TestClient:
    from app.main import app

    return TestClient(app)


def test_build_watch_briefing_is_flat_scalars(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed()
    monkeypatch.setattr(briefing_route, "get_app_config", _cfg)
    out = briefing_route.build_watch_briefing()
    # Every value must be a scalar (no nested dict/list) for the watch parser.
    for key, value in out.items():
        assert not isinstance(value, (dict, list)), key
    assert out["readiness_band"] in {"green", "yellow", "red", "unknown"}
    assert out["event_days"] == 26
    assert out["heat_severity"] == "extreme"
    assert isinstance(out["action"], str) and out["action"]


def test_watch_endpoint_open_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed()
    monkeypatch.setattr(briefing_route, "get_app_config", _cfg)
    r = _client().get("/api/watch/briefing")
    assert r.status_code == 200
    body = r.json()
    assert "readiness_band" in body and "action" in body


def test_watch_endpoint_requires_token_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed()
    monkeypatch.setattr(briefing_route, "get_app_config", _cfg)
    monkeypatch.setenv("GA_WATCH_TOKEN", "s3cret")
    from app.config import get_settings

    get_settings.cache_clear()
    c = _client()
    assert c.get("/api/watch/briefing").status_code == 401
    assert c.get("/api/watch/briefing", params={"token": "wrong"}).status_code == 401
    assert c.get("/api/watch/briefing", params={"token": "s3cret"}).status_code == 200
