"""Local insight engine: deterministic metric detail + measured relationships."""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from app.analytics import insight_engine as ie

START = date(2026, 1, 1)


def frame(n: int, **cols: list) -> pl.DataFrame:
    days = [START + timedelta(days=i) for i in range(n)]
    return pl.DataFrame({"day": days, **cols})


def test_detail_structure_and_measured_relationships() -> None:
    n = 90
    sleep = [60.0 + i * 0.2 for i in range(n)]  # steadily rising
    hrv = [40.0 + s * 0.5 for s in sleep]  # positively correlated
    rhr = [80.0 - s * 0.3 for s in sleep]  # inversely correlated
    daily = frame(
        n,
        sleep_score=sleep,
        hrv_last_night_avg=hrv,
        resting_hr=rhr,
        body_battery_high=[70.0] * n,  # constant -> no correlation, excluded
    )
    d = ie.metric_detail(daily, "sleep_score", 90)
    assert d["available"] is True
    assert d["label"] == "Sleep Score" and d["direction"] == "higher-better"
    assert d["current"] is not None
    assert d["stats"]["max"] >= d["stats"]["min"]
    assert len(d["series"]) == 90
    rels = {r["key"]: r["r"] for r in d["relationships"]}
    assert rels["hrv_last_night_avg"] > 0.3  # measured, positive
    assert rels["resting_hr"] < 0  # measured, inverse
    assert "body_battery_high" not in rels  # flat -> no spurious link
    assert d["insights"] and all(isinstance(s, str) for s in d["insights"])
    assert "Sleep Score" in d["chart_summary"]


def test_thin_history_says_so() -> None:
    d = ie.metric_detail(frame(5, sleep_score=[60.0, 61.0, 62.0, 63.0, 64.0]), "sleep_score", 90)
    assert d["available"] is True
    assert d["insights"] == ["There is not enough history yet to establish a reliable trend."]


def test_outlier_is_flagged() -> None:
    vals = [60.0] * 59 + [100.0]
    d = ie.metric_detail(frame(60, sleep_score=vals), "sleep_score", 90)
    assert any("unusually high" in s for s in d["insights"])


def test_consecutive_run_insight() -> None:
    vals = [60.0] * 80 + [58.0, 60.0, 63.0, 66.0, 70.0]  # last 5 strictly rising
    d = ie.metric_detail(frame(85, sleep_score=vals), "sleep_score", 90)
    assert any("consecutive" in s for s in d["insights"])


def test_lower_better_metric_direction_and_status() -> None:
    # Resting HR: rising is bad. A run of rising RHR should read as "declined".
    vals = [50.0] * 80 + [50.0, 52.0, 54.0, 56.0]
    d = ie.metric_detail(frame(84, resting_hr=vals), "resting_hr", 90)
    assert d["direction"] == "lower-better"
    assert any("declined" in s for s in d["insights"])


def test_unknown_metric_and_empty_frame() -> None:
    assert ie.metric_detail(pl.DataFrame(), "sleep_score")["available"] is False
    assert ie.metric_detail(frame(10, sleep_score=[60.0] * 10), "nope")["available"] is False
