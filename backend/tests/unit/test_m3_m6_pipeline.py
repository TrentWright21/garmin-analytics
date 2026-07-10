"""M3-M6 tests: raw layer dedupe, sync pipeline, normalization, analytics, API.

Uses a fake collector emitting realistic Garmin payload shapes and a
temp-file SQLite DB, so the full pipeline runs exactly as in production.
"""

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text as sa_text

import app.db.engine as db
from app.analytics import engine as ax
from app.collectors.sync import SyncEngine
from app.db.models.core import Activity, DailyMetrics, RacePrediction, RawApiData
from app.normalize.mappers import build_daily_metrics, build_race_prediction


@pytest.fixture(autouse=True)
def temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GA_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    from app.config import get_settings

    get_settings.cache_clear()
    db.reset_engine_for_tests()
    yield
    get_settings.cache_clear()
    db.reset_engine_for_tests()


DAY = date(2026, 7, 1)


def summary_payload(day: date, steps: int = 9000) -> dict[str, Any]:
    return {
        "totalSteps": steps,
        "totalKilocalories": 2600,
        "activeKilocalories": 700,
        "floorsAscended": 11.0,
        "restingHeartRate": 53,
        "minHeartRate": 47,
        "maxHeartRate": 168,
        "averageStressLevel": 28,
        "maxStressLevel": 82,
        "bodyBatteryHighestValue": 88,
        "bodyBatteryLowestValue": 21,
        "moderateIntensityMinutes": 20,
        "vigorousIntensityMinutes": 15,
    }


def sleep_payload(day: date) -> dict[str, Any]:
    return {
        "dailySleepDTO": {
            "sleepTimeSeconds": 27000,
            "deepSleepSeconds": 5400,
            "lightSleepSeconds": 14400,
            "remSleepSeconds": 7200,
            "awakeSleepSeconds": 900,
            "sleepScores": {"overall": {"value": 82}},
        },
        # overnight extras live at the top level, outside the DTO
        "bodyBatteryChange": 67,
        "restlessMomentsCount": 40,
        "avgSkinTempDeviationC": -0.3,
    }


def training_status_payload() -> dict[str, Any]:
    return {
        "mostRecentTrainingStatus": {
            "latestTrainingStatusData": {
                "3500092692": {
                    "trainingStatus": 2,
                    "trainingStatusFeedbackPhrase": "UNPRODUCTIVE_5",
                    "fitnessTrend": 1,
                }
            }
        }
    }


class FakeCollector:
    """GarminCollector emitting realistic payload shapes, no network."""

    def __init__(self) -> None:
        self.revised = False

    def connect(self) -> str:
        return "Test Runner"

    def fetch_daily(self, endpoint: str, day: date) -> Any:
        if endpoint == "daily_summary":
            return summary_payload(day, steps=9500 if self.revised else 9000)
        if endpoint == "sleep":
            return sleep_payload(day)
        if endpoint == "hrv":
            return {"hrvSummary": {"lastNightAvg": 62, "status": "BALANCED"}}
        if endpoint == "training_readiness":
            return [{"score": 71, "recoveryTime": 767, "acuteLoad": 220, "hrvWeeklyAverage": 76}]
        if endpoint == "training_status":
            return training_status_payload()
        if endpoint == "max_metrics":
            return [{"generic": {"vo2MaxPreciseValue": 51.3}}]
        return {}  # everything else: empty, must be skipped gracefully

    def fetch_snapshot(self, endpoint: str) -> Any:
        if endpoint == "race_predictions":
            return {
                "calendarDate": str(date.today()),
                "time5K": 1485,
                "time10K": 3223,
                "timeHalfMarathon": 7453,
                "timeMarathon": 16878,
            }
        return {"snapshot": endpoint}

    def activities_by_date(self, start: date, end: date) -> list[dict[str, Any]]:
        return [
            {
                "activityId": 111,
                "activityName": "Hartselle Running",
                "startTimeLocal": f"{start} 06:15:00",
                "activityType": {"typeKey": "running"},
                "distance": 8000.0,
                "duration": 2700.0,
                "averageHR": 152.0,
                "maxHR": 171.0,
                "calories": 520.0,
                "elevationGain": 60.0,
                "averageRunningCadenceInStepsPerMinute": 172.0,
                "averageTemperature": 24.0,
                "activityTrainingLoad": 95.0,
                "aerobicTrainingEffect": 2.8,
                "anaerobicTrainingEffect": 0.4,
                "trainingEffectLabel": "AEROBIC_BASE",
                "averageSpeed": 2.96,
                "hrTimeInZone_1": 155.0,
                "hrTimeInZone_2": 409.0,
                "hrTimeInZone_3": 1201.7,
                "hrTimeInZone_4": 0.0,
                "hrTimeInZone_5": 0.0,
            }
        ]

    # unused protocol members for these tests
    def daily_summary(self, day: date) -> dict[str, Any]:
        return summary_payload(day)

    def sleep(self, day: date) -> dict[str, Any]:
        return sleep_payload(day)

    def hrv(self, day: date) -> dict[str, Any]:
        return {}

    def activities(self, start: int = 0, limit: int = 20) -> list[dict[str, Any]]:
        return []


class TestRawLayer:
    def test_identical_payload_is_deduped(self) -> None:
        with db.session_scope() as s:
            assert db.store_raw(s, "daily_summary", DAY, {"a": 1}) is True
            assert db.store_raw(s, "daily_summary", DAY, {"a": 1}) is False

    def test_revised_payload_appends_never_overwrites(self) -> None:
        with db.session_scope() as s:
            db.store_raw(s, "daily_summary", DAY, {"steps": 100})
            db.store_raw(s, "daily_summary", DAY, {"steps": 150})
        with db.session_scope() as s:
            rows = s.query(RawApiData).filter_by(endpoint="daily_summary").all()
            assert len(rows) == 2  # both versions kept forever
            assert db.latest_raw(s, "daily_summary", DAY)["steps"] == 150


class TestSyncPipeline:
    def test_full_sync_populates_all_layers(self) -> None:
        collector = FakeCollector()
        stats = SyncEngine(collector, pause_s=0).sync_range(DAY, DAY + timedelta(days=1))
        assert stats["days"] == 2
        assert stats["activities"] == 1

        with db.session_scope() as s:
            dm = s.get(DailyMetrics, DAY)
            assert dm is not None
            assert dm.steps == 9000
            assert dm.sleep_score == 82
            assert dm.hrv_last_night_avg == 62
            assert dm.training_readiness == 71
            assert dm.vo2max_running == 51.3
            # Phase 1b: Garmin's own verdicts + overnight extras
            assert dm.recovery_time_min == 767
            assert dm.acute_load_garmin == 220
            assert dm.hrv_weekly_avg == 76
            assert dm.training_status == "UNPRODUCTIVE_5"
            assert dm.body_battery_change == 67
            assert dm.restless_moments == 40
            assert dm.skin_temp_dev_c == -0.3
            act = s.get(Activity, 111)
            assert act is not None and act.activity_type == "running"
            # Phase 1b: Training Effect + speed + HR-zone seconds
            assert act.aerobic_te == 2.8
            assert act.anaerobic_te == 0.4
            assert act.te_label == "AEROBIC_BASE"
            assert act.avg_speed_mps == 2.96
            assert act.zone_3_s == 1201.7

    def test_race_prediction_snapshot_normalizes(self) -> None:
        # The snapshot is stored at today's date, so a range covering today
        # (as the daily sync's always does) materializes the row.
        today = date.today()
        SyncEngine(FakeCollector(), pause_s=0).sync_range(today, today)
        with db.session_scope() as s:
            rp = s.get(RacePrediction, today)
            assert rp is not None
            assert rp.time_5k_s == 1485
            assert rp.time_10k_s == 3223
            assert rp.time_half_s == 7453
            assert rp.time_marathon_s == 16878

    def test_resync_with_revision_updates_normalized_keeps_raw(self) -> None:
        collector = FakeCollector()
        engine = SyncEngine(collector, pause_s=0)
        engine.sync_range(DAY, DAY)
        collector.revised = True
        engine.sync_range(DAY, DAY)

        with db.session_scope() as s:
            dm = s.get(DailyMetrics, DAY)
            assert dm is not None and dm.steps == 9500  # normalized reflects revision
            raws = s.query(RawApiData).filter_by(endpoint="daily_summary").count()
            assert raws == 2  # ...but the original is still there


class TestPhase1bMappers:
    def test_race_prediction_prefers_payload_calendar_date(self) -> None:
        rp = build_race_prediction({"calendarDate": "2026-07-07", "time5K": 1485}, DAY)
        assert rp is not None
        assert rp.day == date(2026, 7, 7)
        assert rp.time_5k_s == 1485

    def test_race_prediction_falls_back_to_metric_date(self) -> None:
        rp = build_race_prediction({"time10K": 3223}, DAY)
        assert rp is not None
        assert rp.day == DAY
        assert rp.time_10k_s == 3223

    def test_race_prediction_without_times_or_day_is_skipped(self) -> None:
        assert build_race_prediction({"userId": 1}, DAY) is None  # no times
        assert build_race_prediction({"time5K": 1485}, None) is None  # no day at all

    def test_training_status_missing_sections_tolerated(self) -> None:
        m = build_daily_metrics(DAY, {"training_status": {"mostRecentTrainingStatus": {}}})
        assert m.training_status is None
        m = build_daily_metrics(DAY, {"training_status": {"unexpected": "shape"}})
        assert m.training_status is None


class TestColumnMigration:
    def test_add_missing_columns_restores_dropped_column(self) -> None:
        engine = db.get_engine()
        with engine.begin() as conn:
            conn.execute(sa_text("ALTER TABLE daily_metrics DROP COLUMN training_status"))
        db._add_missing_columns(engine)  # simulates startup on a pre-1b database
        with db.session_scope() as s:
            s.merge(DailyMetrics(day=DAY, training_status="PRODUCTIVE_1"))
        with db.session_scope() as s:
            row = s.get(DailyMetrics, DAY)
            assert row is not None and row.training_status == "PRODUCTIVE_1"
        db._add_missing_columns(engine)  # idempotent: re-run is a no-op


def synthetic_daily(n: int = 90) -> pl.DataFrame:
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(n)]
    return pl.DataFrame(
        {
            "day": days,
            "steps": [8000 + (i % 7) * 500 for i in range(n)],
            "resting_hr": [58 - i // 15 for i in range(n)],  # improving over time
            "hrv_last_night_avg": [60 + (i % 5) for i in range(n)],
            "sleep_score": [75 + (i % 10) for i in range(n)],
            "sleep_seconds": [(6 + (i % 4)) * 3600 for i in range(n)],
            "avg_stress": [30 for _ in range(n)],
            "body_battery_high": [70 + (i % 4) * 8 for i in range(n)],
            "training_readiness": [65 for _ in range(n)],
            "vo2max_running": [50.0 for _ in range(n)],
            "weight_kg": [88.0 for _ in range(n)],
        }
    )


class TestAnalytics:
    def test_rolling_trends_adds_columns(self) -> None:
        out = ax.rolling_trends(synthetic_daily())
        assert "steps_r7" in out.columns and "resting_hr_r30" in out.columns
        assert out["steps_r7"].drop_nulls().len() > 0

    def test_acwr_sweet_spot_on_steady_load(self) -> None:
        load = pl.DataFrame(
            {
                "day": [date(2026, 1, 1) + timedelta(days=i) for i in range(60)],
                "load": [80.0] * 60,
            }
        )
        out = ax.acwr(load)
        last = out.tail(1).to_dicts()[0]
        assert last["acwr"] == pytest.approx(1.0, abs=0.05)  # steady load => ~1.0

    def test_monotony_flags_unvaried_training(self) -> None:
        load = pl.DataFrame(
            {
                "day": [date(2026, 1, 1) + timedelta(days=i) for i in range(28)],
                "load": [80.0 + (i % 2) for i in range(28)],  # nearly identical days
            }
        )
        out = ax.monotony(load).drop_nulls("monotony")
        assert out["monotony"].max() > 2.0

    def test_readiness_score_has_components(self) -> None:
        result = ax.readiness_score(synthetic_daily())
        assert result["score"] is not None and 0 <= result["score"] <= 100
        assert "sleep" in result["components"]

    def test_insights_finds_rhr_improvement(self) -> None:
        findings = ax.generate_insights(synthetic_daily(), pl.DataFrame())
        assert any("resting HR" in f for f in findings)

    def test_insights_flags_hrv_suppression_via_swc(self) -> None:
        hrv = [60 + (i % 7) - 3 for i in range(83)] + [46] * 7
        df = synthetic_daily(90).with_columns(pl.Series("hrv_last_night_avg", hrv))
        findings = ax.generate_insights(df, pl.DataFrame())
        assert any("below your normal band" in f for f in findings)


class TestApi:
    def test_routes_respond(self) -> None:
        SyncEngine(FakeCollector(), pause_s=0).sync_range(DAY, DAY)
        from app.main import app

        with TestClient(app) as client:
            assert client.get("/api/metrics/daily?days=3650").status_code == 200
            assert client.get("/api/analytics/readiness").status_code == 200
            body = client.get("/api/insights?days=3650").json()
            assert "insights" in body
