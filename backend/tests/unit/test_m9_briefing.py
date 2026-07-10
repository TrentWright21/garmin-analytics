"""M9 tests: weather ingestion, briefing analytics, and the briefing API.

Pure functions run on synthetic payloads/frames; the provider runs against an
``httpx.MockTransport`` (no network); the API runs end-to-end against a
temp-file SQLite DB seeded with normalized rows and raw payloads.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import polars as pl
import pytest
from fastapi.testclient import TestClient

import app.db.engine as db
from app.analytics import briefing as brief
from app.api.routes import briefing as briefing_route
from app.collectors.weather import OpenMeteoProvider, WeatherError
from app.config import AppConfig, EventConfig, LocationConfig
from app.db.models.core import Activity
from app.db.models.weather import DailyWeather
from app.normalize.body_battery import parse_body_battery
from app.normalize.weather import build_daily_weather, parse_weather_daily


@pytest.fixture(autouse=True)
def temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GA_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    from app.config import get_settings

    get_settings.cache_clear()
    db.reset_engine_for_tests()
    yield
    get_settings.cache_clear()
    db.reset_engine_for_tests()


TODAY = date.today()


# -- weather parsing ---------------------------------------------------------


def open_meteo_payload() -> dict:
    """Two days of daily aggregates + hourly humidity/dew, muggiest at midday."""
    return {
        "daily": {
            "time": ["2026-06-01", "2026-06-02"],
            "temperature_2m_max": [30.0, 32.0],
            "temperature_2m_min": [18.0, 19.0],
            "apparent_temperature_max": [33.0, 36.0],
            "wind_speed_10m_max": [10.0, 12.0],
        },
        "hourly": {
            "time": [
                "2026-06-01T05:00",
                "2026-06-01T14:00",  # hottest hour of day 1
                "2026-06-02T05:00",
                "2026-06-02T15:00",  # hottest hour of day 2
            ],
            "temperature_2m": [18.0, 30.0, 19.0, 32.0],
            "relative_humidity_2m": [92.0, 55.0, 90.0, 50.0],
            "dew_point_2m": [16.0, 20.0, 17.0, 21.0],
        },
    }


def test_parse_weather_daily_samples_hottest_hour() -> None:
    parsed = parse_weather_daily(open_meteo_payload())
    day1 = parsed[date(2026, 6, 1)]
    assert day1["temp_high_c"] == 30.0
    assert day1["apparent_high_c"] == 33.0
    assert day1["wind_kph"] == 10.0
    # humidity + dew point taken at 14:00 (hottest), not the humid dawn hour.
    assert day1["humidity_pct"] == 55.0
    assert day1["dew_point_c"] == 20.0
    assert parsed[date(2026, 6, 2)]["dew_point_c"] == 21.0


def test_parse_weather_daily_tolerates_missing_sections() -> None:
    assert parse_weather_daily({}) == {}
    partial = parse_weather_daily({"daily": {"time": ["2026-06-01"], "temperature_2m_max": [25.0]}})
    row = partial[date(2026, 6, 1)]
    assert row["temp_high_c"] == 25.0
    assert row["dew_point_c"] is None  # no hourly section


def test_build_daily_weather_row() -> None:
    row = build_daily_weather(date(2026, 6, 1), {"temp_high_c": 30.0, "dew_point_c": 20.0})
    assert isinstance(row, DailyWeather)
    assert row.day == date(2026, 6, 1)
    assert row.temp_high_c == 30.0
    assert row.humidity_pct is None


# -- body battery parsing ----------------------------------------------------


def test_parse_body_battery_handles_mixed_row_shapes() -> None:
    payload = [
        {
            "date": "2026-07-05",
            "charged": 40,
            "drained": 55,
            "bodyBatteryValuesArray": [
                [1720003600000, 60],  # [ts, level]
                [1720000000000, "MEASURED", 55],  # [ts, status, level]
                [1720007200000, 58, 1],  # [ts, level, version]
            ],
        }
    ]
    out = parse_body_battery(payload)
    assert len(out) == 1
    day = out[0]
    assert day["charged"] == 40
    assert [p["level"] for p in day["points"]] == [55, 60, 58]  # sorted by timestamp
    assert day["points"][0]["ts_ms"] == 1720000000000


def test_parse_body_battery_tolerates_empty_and_dict() -> None:
    assert parse_body_battery(None) == []
    assert parse_body_battery({"date": "2026-07-05", "bodyBatteryValuesArray": None}) == [
        {"date": "2026-07-05", "charged": None, "drained": None, "points": []}
    ]


# -- training streak ---------------------------------------------------------


def acts_on_days(days: list[date]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "day": days,
            "start_time_local": [datetime(d.year, d.month, d.day, 6) for d in days],
            "name": [f"run {i}" for i in range(len(days))],
            "training_load": [80.0] * len(days),
            "duration_s": [3000.0] * len(days),
            "avg_hr": [150.0] * len(days),
        }
    )


def test_training_streak_live_and_longest() -> None:
    days = [TODAY - timedelta(days=i) for i in (5, 4, 3, 1, 0)]  # 3-run then 2-run runs
    out = brief.training_streak(acts_on_days(sorted(days)), TODAY)
    assert out["available"] is True
    assert out["current_streak"] == 2  # today + yesterday
    assert out["longest_streak"] == 3
    assert out["active_last_7"] == 5


def test_training_streak_lapsed_when_stale() -> None:
    days = [TODAY - timedelta(days=i) for i in (10, 9, 8)]
    out = brief.training_streak(acts_on_days(sorted(days)), TODAY)
    assert out["current_streak"] == 0  # last activity was >1 day ago
    assert out["days_since_last"] == 8


def test_training_streak_empty() -> None:
    assert brief.training_streak(pl.DataFrame(), TODAY) == {"available": False}


# -- recovery timer ----------------------------------------------------------


def test_recovery_timer_not_yet_recovered() -> None:
    start = datetime.now() - timedelta(hours=6)
    acts = pl.DataFrame(
        {
            "start_time_local": [start],
            "name": ["hard intervals"],
            "training_load": [200.0],  # -> 48h window
            "duration_s": [3600.0],
            "avg_hr": [165.0],
        }
    )
    out = brief.recovery_timer(acts, datetime.now())
    assert out["recovered"] is False
    assert out["estimated_recovery_hours"] == 48
    assert out["next_intensity"] == "easy"
    assert 0 < out["pct_recovered"] < 100


def test_recovery_timer_recovered_and_fresh_vs_buried() -> None:
    start = datetime.now() - timedelta(hours=72)
    acts = pl.DataFrame(
        {
            "start_time_local": [start],
            "name": ["easy run"],
            "training_load": [50.0],
            "duration_s": [1800.0],
            "avg_hr": [140.0],
        }
    )
    fresh = brief.recovery_timer(acts, datetime.now(), tsb=10.0)
    assert fresh["recovered"] is True
    assert fresh["next_intensity"] == "quality"

    buried = brief.recovery_timer(acts, datetime.now(), tsb=-30.0)
    assert buried["recovered"] is True
    assert buried["next_intensity"] == "easy"  # deep fatigue overrides the timer


def test_recovery_timer_empty() -> None:
    assert brief.recovery_timer(pl.DataFrame(), datetime.now()) == {"available": False}


def test_recovery_timer_prefers_garmin_native_number() -> None:
    start = datetime.now() - timedelta(hours=6)
    acts = pl.DataFrame(
        {
            "start_time_local": [start],
            "name": ["easy run"],
            "training_load": [50.0],
            "duration_s": [1800.0],
            "avg_hr": [140.0],
        }
    )
    out = brief.recovery_timer(acts, datetime.now(), garmin_recovery_min=767.0)
    assert out["source"] == "garmin"
    assert out["recovered"] is False
    assert out["estimated_recovery_hours"] == pytest.approx(6 + 767 / 60, abs=0.2)
    assert "Garmin" in out["recommendation"]

    cleared = brief.recovery_timer(acts, datetime.now(), garmin_recovery_min=0.0)
    assert cleared["source"] == "garmin"
    assert cleared["recovered"] is True
    assert cleared["pct_recovered"] == 100


def test_recovery_timer_falls_back_to_heuristic_without_garmin() -> None:
    start = datetime.now() - timedelta(hours=6)
    acts = pl.DataFrame(
        {
            "start_time_local": [start],
            "name": ["run"],
            "training_load": [200.0],
            "duration_s": [3600.0],
            "avg_hr": [165.0],
        }
    )
    out = brief.recovery_timer(acts, datetime.now(), garmin_recovery_min=None)
    assert out["source"] == "heuristic"
    assert out["estimated_recovery_hours"] == 48


# -- heat advisory -----------------------------------------------------------


def test_heat_advisory_dew_point_scale() -> None:
    extreme = brief.heat_advisory(dew_point_c=24.0, apparent_high_c=40.0, temp_high_c=36.0)
    assert extreme["severity"] == "extreme"
    assert extreme["dew_point_f"] == pytest.approx(75.2, abs=0.1)
    assert extreme["apparent_high_f"] == pytest.approx(104.0, abs=0.1)

    mild = brief.heat_advisory(dew_point_c=5.0, apparent_high_c=15.0, temp_high_c=14.0)
    assert mild["severity"] == "none"


def test_heat_advisory_unavailable_without_dew_point() -> None:
    assert brief.heat_advisory(None, 30.0, 30.0) == {"available": False}


# -- event countdown ---------------------------------------------------------


def test_event_countdown() -> None:
    out = brief.event_countdown("Mount Whitney", TODAY + timedelta(days=14), TODAY, kind="climb")
    assert out["days_until"] == 14
    assert out["weeks_until"] == 2.0
    assert out["is_past"] is False
    assert brief.event_countdown("Past", TODAY - timedelta(days=1), TODAY)["is_past"] is True


# -- config ------------------------------------------------------------------


def test_event_config_optional_fields() -> None:
    climb = EventConfig(name="Whitney", date=date(2026, 8, 1), kind="climb")
    assert climb.distance_m is None and climb.goal_time is None
    race = EventConfig(name="10K", date=date(2026, 9, 1), kind="race", distance_m=10000.0)
    assert race.distance_m == 10000.0


def test_app_config_event_defaults_none() -> None:
    assert AppConfig().event is None
    assert AppConfig().location.name == "Hartselle, AL"


# -- weather provider (mocked transport) -------------------------------------


def test_provider_history_and_forecast() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=open_meteo_payload())

    provider = OpenMeteoProvider(transport=httpx.MockTransport(handler))
    hist = provider.daily_history(34.4, -86.9, date(2026, 6, 1), date(2026, 6, 2))
    assert "daily" in hist
    assert "archive-api" in seen[0]
    provider.forecast(34.4, -86.9, days=7)
    assert "forecast" in seen[1]


def test_provider_raises_weather_error_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    provider = OpenMeteoProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(WeatherError):
        provider.daily_history(34.4, -86.9, date(2026, 6, 1), date(2026, 6, 2))


# -- normalize weather from the raw layer ------------------------------------


def test_normalize_weather_from_raw() -> None:
    from app.analytics import engine as ax
    from app.collectors.sync import normalize_weather

    with db.session_scope() as s:
        db.store_raw(s, "weather_archive", date(2026, 6, 2), open_meteo_payload())
    with db.session_scope() as s:
        normalize_weather(s)

    frame = ax.load_weather(date(2026, 6, 1), date(2026, 6, 2))
    assert frame.height == 2
    row = frame.sort("day").tail(1).to_dicts()[0]
    assert row["dew_point_c"] == 21.0


# -- API ---------------------------------------------------------------------


def _client() -> TestClient:
    from app.main import app

    return TestClient(app)


def seed_recent_activities(n: int = 10) -> None:
    with db.session_scope() as s:
        for i in range(n):
            d = TODAY - timedelta(days=n - i)
            s.merge(
                Activity(
                    activity_id=2000 + i,
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


def test_api_briefing_shape_and_heat(monkeypatch: pytest.MonkeyPatch) -> None:
    seed_recent_activities()
    # today's weather with an oppressive dew point.
    with db.session_scope() as s:
        s.merge(DailyWeather(day=TODAY, temp_high_c=34.0, dew_point_c=23.0, apparent_high_c=40.0))

    cfg = AppConfig(
        location=LocationConfig(name="Hartselle, AL"),
        event=EventConfig(name="Mount Whitney", date=TODAY + timedelta(days=26), kind="climb"),
    )
    monkeypatch.setattr(briefing_route, "get_app_config", lambda: cfg)

    r = _client().get("/api/briefing")
    assert r.status_code == 200
    body = r.json()
    for key in ("readiness", "risk", "fitness", "streak", "recovery", "weather", "heat", "event"):
        assert key in body
    assert body["heat"]["available"] is True
    assert body["heat"]["severity"] in {"high", "extreme"}
    assert body["weather"]["temp_high_f"] == pytest.approx(93.2, abs=0.1)
    assert body["event"]["days_until"] == 26
    assert body["streak"]["available"] is True


def test_api_event_empty_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(briefing_route, "get_app_config", lambda: AppConfig(event=None))
    r = _client().get("/api/event")
    assert r.status_code == 200
    assert r.json() == {"available": False}


def test_api_body_battery_from_raw() -> None:
    payload = [
        {
            "date": TODAY.isoformat(),
            "charged": 30,
            "drained": 20,
            "bodyBatteryValuesArray": [[1720000000000, 55], [1720003600000, 62]],
        }
    ]
    with db.session_scope() as s:
        db.store_raw(s, "body_battery_events", TODAY, payload)
    r = _client().get("/api/metrics/body-battery", params={"days": 7})
    assert r.status_code == 200
    body = r.json()
    assert len(body["series"]) == 2
    assert body["days"][0]["charged"] == 30


def test_coach_get_briefing_returns_json(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ai import coach

    seed_recent_activities()
    monkeypatch.setattr(briefing_route, "get_app_config", lambda: AppConfig(event=None))
    assert json.loads(coach.get_briefing())["date"] == TODAY.isoformat()
