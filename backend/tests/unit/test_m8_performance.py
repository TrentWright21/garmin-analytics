"""M8 tests: fitness model, readiness/risk engine, and session intelligence.

Pure functions are exercised on synthetic Polars frames; the API is exercised
end-to-end against a temp-file SQLite DB seeded directly with normalized rows.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest
from fastapi.testclient import TestClient

import app.db.engine as db
from app.analytics import fitness, physiology, readiness, session
from app.db.models.core import Activity, DailyMetrics


@pytest.fixture(autouse=True)
def temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GA_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    from app.config import get_settings

    get_settings.cache_clear()
    db.reset_engine_for_tests()
    yield
    get_settings.cache_clear()
    db.reset_engine_for_tests()


# -- synthetic data ----------------------------------------------------------

START = date(2026, 1, 1)


def load_frame(loads: list[float]) -> pl.DataFrame:
    days = [START + timedelta(days=i) for i in range(len(loads))]
    return pl.DataFrame({"day": days, "load": loads})


def daily_frame(
    n: int = 70,
    rhr: list[int] | None = None,
    hrv: list[int] | None = None,
    sleep_score: list[int] | None = None,
    sleep_seconds: list[int] | None = None,
) -> pl.DataFrame:
    days = [START + timedelta(days=i) for i in range(n)]
    return pl.DataFrame(
        {
            "day": days,
            "resting_hr": rhr if rhr is not None else [52] * n,
            "hrv_last_night_avg": hrv if hrv is not None else [60] * n,
            "sleep_score": sleep_score if sleep_score is not None else [80] * n,
            "sleep_seconds": sleep_seconds if sleep_seconds is not None else [27000] * n,
            "avg_stress": [30] * n,
            "body_battery_high": [85] * n,
        }
    )


# -- physiology --------------------------------------------------------------


def test_estimate_hr_max_prefers_observed_and_configured() -> None:
    acts = pl.DataFrame({"max_hr": [170.0, 185.0, 180.0]})
    assert physiology.estimate_hr_max(acts) == 185.0
    assert physiology.estimate_hr_max(acts, configured=200.0) == 200.0
    assert physiology.estimate_hr_max(pl.DataFrame()) == physiology.DEFAULT_HR_MAX


def test_hr_zone_and_band() -> None:
    assert physiology.hr_zone(190, 190) == 5
    assert physiology.hr_zone(120, 190) == 2
    assert physiology.intensity_band(120, 190) == "easy"
    assert physiology.intensity_band(170, 190) == "hard"
    assert physiology.intensity_band(155, 190) == "moderate"


def test_trimp_is_monotonic_in_intensity() -> None:
    easy = physiology.trimp(60, 130, 50, 190)
    hard = physiology.trimp(60, 175, 50, 190)
    assert easy is not None and hard is not None and hard > easy
    assert physiology.trimp(60, 130, 190, 190) is None  # bad reserve


# -- fitness model -----------------------------------------------------------


def test_pmc_form_goes_negative_after_a_spike() -> None:
    loads = [50.0] * 60 + [200.0] * 5  # steady base then a hard block
    pmc = fitness.performance_management(load_frame(loads))
    last = pmc.tail(1).to_dicts()[0]
    # Acute load now exceeds chronic, so fatigue > fitness and form is negative.
    assert last["atl"] > last["ctl"]
    assert last["tsb"] < 0
    assert last["ramp_7d"] is not None


def test_pmc_converges_to_steady_load() -> None:
    pmc = fitness.performance_management(load_frame([40.0] * 120))
    last = pmc.tail(1).to_dicts()[0]
    assert abs(last["ctl"] - 40.0) < 1.0
    assert abs(last["tsb"]) < 1.0


def test_fitness_summary_labels_form() -> None:
    summary = fitness.fitness_summary(load_frame([50.0] * 60 + [220.0] * 6))
    assert summary["available"] is True
    assert summary["form_state"] in {"productive", "overreached"}
    assert "interpretation" in summary
    assert fitness.form_state(20) == "very_fresh"
    assert fitness.form_state(-40) == "overreached"


def test_vo2max_trend_detects_improvement_and_confidence() -> None:
    n = 40
    vo2 = [50.0 + i * 0.05 for i in range(n)]
    daily = daily_frame(n).with_columns(pl.Series("vo2max_running", vo2))
    out = fitness.vo2max_trend(daily)
    assert out["available"] is True
    assert out["direction"] == "improving"
    assert out["confidence"] in {"low", "moderate", "high"}


def test_intensity_distribution_polarized_vs_grey_zone() -> None:
    # Mostly easy with a little hard = polarized.
    acts = pl.DataFrame(
        {
            "avg_hr": [120.0, 122.0, 118.0, 121.0, 175.0],
            "duration_s": [3600.0, 3600.0, 3600.0, 3600.0, 1800.0],
        }
    )
    out = fitness.intensity_distribution(acts, hr_max=190)
    assert out["available"] is True
    assert out["aerobic_pct"] > out["anaerobic_pct"]
    assert round(sum(out["pct"].values())) == 100
    assert out["verdict"] in {"polarized", "all-easy", "too-hard", "grey-zone-heavy"}


# -- readiness & risk --------------------------------------------------------


def test_resting_hr_deviation_flags_elevation() -> None:
    rhr = [50] * 60 + [58] * 10  # recent week elevated
    dev = readiness.resting_hr_deviation(daily_frame(70, rhr=rhr))
    last = dev.tail(1).to_dicts()[0]
    assert last["rhr_dev_bpm"] > 4


def test_daily_readiness_bands_and_drivers() -> None:
    good = readiness.daily_readiness(daily_frame(70))
    assert good["available"] is True
    assert good["band"] in {"green", "yellow", "red"}
    assert good["drivers"] and good["drivers"][0]["value"] <= good["drivers"][-1]["value"]

    bad = daily_frame(
        70,
        hrv=[60] * 60 + [45] * 10,
        rhr=[50] * 60 + [60] * 10,
        sleep_score=[80] * 60 + [45] * 10,
    )
    low = readiness.daily_readiness(bad)
    assert low["score"] < good["score"]


def test_risk_flags_fire_on_bad_signals() -> None:
    # HRV crashed and RHR spiked in the recent week -> red flags.
    daily = daily_frame(70, hrv=[60] * 60 + [44] * 10, rhr=[50] * 60 + [60] * 10)
    acts = pl.DataFrame(
        {
            "day": [START + timedelta(days=60 + i) for i in range(8)],
            "training_load": [300.0] * 8,
            "duration_s": [3600.0] * 8,
            "avg_hr": [150.0] * 8,
        }
    )
    out = readiness.risk_flags(daily, acts)
    codes = {f["code"] for f in out["flags"]}
    assert out["risk_band"] == "red"
    assert "HRV_SUPPRESSION" in codes
    assert "RHR_ELEVATED" in codes


def test_risk_flags_quiet_when_healthy() -> None:
    out = readiness.risk_flags(daily_frame(70), pl.DataFrame())
    assert out["risk_band"] == "green"
    assert out["flag_count"] == 0


# -- session intelligence ----------------------------------------------------


def test_efficiency_factor_math() -> None:
    # 10 km in 3000 s = 200 m/min; /150 bpm = 1.333
    assert session.efficiency_factor(10000, 3000, 150) == pytest.approx(1.333, abs=0.01)
    assert session.efficiency_factor(0, 3000, 150) is None


def test_decoupling_detects_second_half_drift() -> None:
    # Same pace both halves, HR climbs in the second half -> positive decoupling.
    splits = [
        {"duration_s": 600, "distance_m": 2000, "avg_hr": 150},
        {"duration_s": 600, "distance_m": 2000, "avg_hr": 150},
        {"duration_s": 600, "distance_m": 2000, "avg_hr": 165},
        {"duration_s": 600, "distance_m": 2000, "avg_hr": 168},
    ]
    out = session.decoupling_index(splits)
    assert out is not None
    assert out["decoupling_pct"] > 5
    assert out["aerobic_status"] == "decoupled"
    assert session.decoupling_index(splits[:1]) is None


def test_analyze_session_full_shape() -> None:
    history = pl.DataFrame(
        {
            "activity_id": [1, 2, 3, 4],
            "activity_type": ["running"] * 4,
            "distance_m": [10000.0, 10200.0, 9800.0, 10100.0],
            "duration_s": [3100.0, 3150.0, 3050.0, 3120.0],
            "avg_hr": [150.0, 151.0, 149.0, 150.0],
            "day": [START + timedelta(days=i) for i in range(4)],
            "elevation_gain_m": [50.0] * 4,
            "avg_temp_c": [15.0] * 4,
            "name": ["run"] * 4,
            "start_time_local": [datetime(2026, 1, 1) + timedelta(days=i) for i in range(4)],
        }
    )
    activity = {
        "activity_id": 5,
        "activity_type": "running",
        "distance_m": 10000.0,
        "duration_s": 2900.0,  # faster than baseline
        "avg_hr": 150.0,
        "day": START + timedelta(days=5),
        "elevation_gain_m": 50.0,
        "avg_temp_c": 15.0,
        "name": "fast run",
    }
    out = session.analyze_session(activity, history, hr_max=190)
    assert out["efficiency_factor"] is not None
    assert out["baseline"]["n"] == 4
    assert out["physiology"]
    assert out["insights"]
    assert out["decoupling"] is None  # no splits supplied


def details_payload(activity_id: int, n: int = 20) -> dict:
    """A synthetic Garmin activity-details payload with a GPS + speed track."""
    descriptors = [
        {"key": "directLatitude", "metricsIndex": 0},
        {"key": "directLongitude", "metricsIndex": 1},
        {"key": "directSpeed", "metricsIndex": 2},
    ]
    metrics = [
        {"metrics": [34.0 + i * 0.001, -86.0 + i * 0.001, 3.0 + (i % 5) * 0.3]} for i in range(n)
    ]
    return {
        "activityId": activity_id,
        "metricDescriptors": descriptors,
        "activityDetailMetrics": metrics,
    }


def test_extract_route_from_metrics() -> None:
    r = session.extract_route(details_payload(5, 25))
    assert r["has_gps"] is True
    assert len(r["points"]) == 25
    assert r["points"][0][2] is not None  # carries speed
    assert r["bounds"][0][0] <= r["bounds"][1][0]  # minLat <= maxLat
    assert r["bounds"][0][1] <= r["bounds"][1][1]  # minLon <= maxLon
    assert r["fast_mps"] >= r["slow_mps"]  # p90 >= p10


def test_extract_route_downsamples() -> None:
    r = session.extract_route(details_payload(1, 5000))
    assert len(r["points"]) <= session._ROUTE_MAX_POINTS


def test_extract_route_no_gps() -> None:
    assert (
        session.extract_route({"metricDescriptors": [], "activityDetailMetrics": []})["has_gps"]
        is False
    )
    assert session.extract_route({})["has_gps"] is False


def test_extract_route_polyline_fallback() -> None:
    payload = {
        "geoPolylineDTO": {"polyline": [{"lat": 34.0, "lon": -86.0}, {"lat": 34.1, "lon": -86.2}]}
    }
    r = session.extract_route(payload)
    assert r["has_gps"] is True
    assert len(r["points"]) == 2
    assert r["points"][0][2] is None  # polyline has no per-point speed


# -- API ---------------------------------------------------------------------


def seed_db() -> None:
    """Insert 70 days of daily metrics + a block of activities directly."""
    with db.session_scope() as s:
        for i in range(70):
            s.merge(
                DailyMetrics(
                    day=START + timedelta(days=i),
                    resting_hr=52,
                    hrv_last_night_avg=60,
                    sleep_score=80,
                    sleep_seconds=27000,
                    avg_stress=30,
                    body_battery_high=85,
                    vo2max_running=50.0 + i * 0.02,
                )
            )
        for i in range(20):
            d = START + timedelta(days=40 + i)
            s.merge(
                Activity(
                    activity_id=1000 + i,
                    start_time_local=datetime(d.year, d.month, d.day, 6, 0),
                    day=d,
                    activity_type="running",
                    name=f"run {i}",
                    distance_m=10000.0,
                    duration_s=3000.0,
                    elevation_gain_m=60.0,
                    avg_hr=150.0,
                    max_hr=178.0,
                    avg_temp_c=15.0,
                    training_load=120.0,
                )
            )


def _client() -> TestClient:
    from app.main import app

    return TestClient(app)


def test_api_fitness_readiness_risk_intensity() -> None:
    seed_db()
    c = _client()
    # dates in fixtures are historical; ask for a wide window so they're included
    f = c.get("/api/analytics/fitness", params={"days": 3650})
    assert f.status_code == 200
    body = f.json()
    assert "summary" in body and "series" in body

    for path in ("/api/analytics/readiness-v2", "/api/analytics/risk", "/api/analytics/vo2max"):
        r = c.get(path)
        assert r.status_code == 200, path

    i = c.get("/api/analytics/intensity", params={"days": 3650})
    assert i.status_code == 200


def test_api_session_endpoints() -> None:
    seed_db()
    c = _client()
    lst = c.get("/api/sessions", params={"days": 3650})
    assert lst.status_code == 200
    assert isinstance(lst.json(), list)

    detail = c.get("/api/session/1005")
    assert detail.status_code == 200
    assert detail.json()["activity_id"] == 1005

    missing = c.get("/api/session/999999")
    assert missing.status_code == 404


def test_api_session_route_uses_cache() -> None:
    seed_db()
    # Seed a cached activity_details payload so the route reads it (no network).
    with db.session_scope() as s:
        db.store_raw(s, "activity_details", START + timedelta(days=45), details_payload(1005, 30))
    c = _client()
    r = c.get("/api/session/1005/route")
    assert r.status_code == 200
    body = r.json()
    assert body["has_gps"] is True
    assert len(body["points"]) == 30
    assert c.get("/api/session/999999/route").status_code == 404


def test_coach_tools_return_json() -> None:
    import json

    from app.ai import coach

    seed_db()
    # These call the DB loaders; just assert they produce parseable JSON.
    assert json.loads(coach.get_fitness_form(3650))
    assert json.loads(coach.get_readiness_detail())
    assert json.loads(coach.get_risk_flags())
    assert json.loads(coach.get_intensity_distribution(3650))
    assert json.loads(coach.get_workout_analysis(1005))["activity_id"] == 1005
