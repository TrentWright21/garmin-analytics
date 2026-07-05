"""M7 coach analytics: pace/VDOT model, sleep coach, and metric insights.

All pure-function tests over synthetic frames — no DB, no network.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta

import polars as pl
import pytest

from app.analytics import metric_insights, pace_coach, sleep_coach

# -- pace coach --------------------------------------------------------------


def test_vdot_of_known_5k() -> None:
    # A 20:00 5K is ~VDOT 49-50 in Daniels' tables.
    vdot = pace_coach.vdot_from_performance(5000, 20 * 60)
    assert 48.0 <= vdot <= 51.0


def test_training_paces_are_ordered() -> None:
    paces = pace_coach.training_paces(50.0)
    # Slower efforts have MORE seconds per km than faster ones.
    assert (
        paces["easy"]["sec_per_km"]
        > paces["marathon"]["sec_per_km"]
        > paces["threshold"]["sec_per_km"]
        > paces["interval"]["sec_per_km"]
        > paces["repetition"]["sec_per_km"]
    )


def test_predict_time_roundtrips_with_vdot() -> None:
    t = pace_coach.predict_time(50.0, 5000)
    back = pace_coach.vdot_from_performance(5000, t)
    assert math.isclose(back, 50.0, abs_tol=0.5)


def test_fmt_helpers() -> None:
    assert pace_coach.fmt_pace(305) == "5:05"
    assert pace_coach.fmt_time(3661) == "1:01:01"
    assert pace_coach.fmt_time(305) == "5:05"


def test_heat_penalty_increases_with_temperature() -> None:
    assert pace_coach.heat_penalty_pct(60) == 0.0
    assert pace_coach.heat_penalty_pct(90) > pace_coach.heat_penalty_pct(70)


def test_build_plan_structure_and_feasibility() -> None:
    plan = pace_coach.build_plan(
        current_vdot=45.0,
        goal_distance_m=pace_coach.RACES["Half Marathon"],
        goal_time_s=None,
        weeks=12,
        current_weekly_miles=20.0,
        goal_key="Half Marathon",
    )
    assert len(plan["schedule"]) == 12
    assert plan["schedule"][-1]["phase"] == "Taper"
    assert plan["goal_vdot"] >= plan["current_vdot"]
    assert plan["verdict"] in {"already-there", "on-track", "ambitious", "very-ambitious"}
    assert set(plan["goal_paces"]) >= {"easy", "threshold", "interval"}


# -- sleep coach -------------------------------------------------------------


def _synthetic_nights(n: int = 45) -> pl.DataFrame:
    """Build nights where longer sleep precedes better recovery."""
    rows = []
    start = date(2026, 1, 1)
    for i in range(n):
        day = start + timedelta(days=i)
        # sleep oscillates 6.0-9.0 h
        hours = 6.0 + 3.0 * (0.5 + 0.5 * math.sin(i / 3.0))
        sleep_s = int(hours * 3600)
        rows.append(
            {
                "day": day,
                "sleep_seconds": sleep_s,
                "deep_seconds": int(sleep_s * 0.16),
                "light_seconds": int(sleep_s * 0.60),
                "rem_seconds": int(sleep_s * 0.22),
                "awake_seconds": int(sleep_s * 0.03),
                "sleep_score": int(60 + hours * 4),
                "sleep_start_local": datetime(day.year, day.month, day.day, 22, 30)
                - timedelta(days=1),
                "sleep_end_local": datetime(day.year, day.month, day.day, 6, 30),
                # recovery improves with sleep
                "hrv_last_night_avg": int(40 + hours * 5),
                "resting_hr": int(70 - hours * 2),
                "body_battery_high": int(50 + hours * 5),
                "avg_stress": int(45 - hours * 2),
                "training_readiness": int(40 + hours * 5),
                "vo2max_running": 49.0,
                "steps": 9000 + i * 10,
                "intensity_minutes": 30,
                "respiration_avg": 13.0,
                "spo2_avg": 95.0,
                "weight_kg": 90.0,
            }
        )
    return pl.DataFrame(rows)


def test_sleep_frame_derives_features() -> None:
    frame = sleep_coach.sleep_frame(_synthetic_nights())
    assert not frame.is_empty()
    for col in (
        "sleep_hours",
        "deep_pct",
        "rem_pct",
        "efficiency",
        "recovery_index",
        "bedtime_min",
    ):
        assert col in frame.columns
    # Deep ~16% of sleep by construction.
    assert 14 <= frame["deep_pct"].mean() <= 18


def test_sleep_need_prefers_longer_sleep() -> None:
    frame = sleep_coach.sleep_frame(_synthetic_nights())
    need = sleep_coach.sleep_need(frame)
    assert sleep_coach.NEED_FLOOR <= need["estimate_hours"] <= sleep_coach.NEED_CEIL
    # With recovery rising in sleep, the estimate should land in the upper half.
    assert need["estimate_hours"] >= 7.5
    assert need["method"] == "recovery-optimized"


def test_coach_report_is_complete() -> None:
    report = sleep_coach.coach_report(_synthetic_nights())
    assert report["available"] is True
    assert report["nights_analyzed"] == 45
    assert report["overall_grade"]["score"] is not None
    assert len(report["dimensions"]) == 5
    assert report["prescription"]["target_bedtime"]
    assert isinstance(report["recommendations"], list) and report["recommendations"]
    assert report["series"]


def test_coach_report_handles_empty() -> None:
    report = sleep_coach.coach_report(pl.DataFrame())
    assert report["available"] is False


def test_regularity_flags_consistent_schedule() -> None:
    frame = sleep_coach.sleep_frame(_synthetic_nights())
    reg = sleep_coach.regularity(frame)
    # Fixed 06:30 wake time -> tiny wake SD.
    assert reg["waketime_sd_min"] is not None
    assert reg["waketime_sd_min"] < 5


# -- metric insights ---------------------------------------------------------


def test_metric_cards_cover_metrics_and_sort_by_status() -> None:
    cards = metric_insights.metric_cards(_synthetic_nights())
    keys = {c["key"] for c in cards}
    assert {"resting_hr", "hrv_last_night_avg", "steps"} <= keys
    order = {"alert": 0, "watch": 1, "good": 2, "neutral": 3}
    ranks = [order.get(c["status"], 4) for c in cards]
    assert ranks == sorted(ranks)
    # Weight is surfaced in pounds.
    weight = next(c for c in cards if c["key"] == "weight_kg")
    assert weight["unit"] == "lb"
    assert weight["value"] == pytest.approx(90.0 * 2.2046226, abs=0.5)
