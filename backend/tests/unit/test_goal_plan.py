"""Phase 4 goal-plan generator: pure-function tests on synthetic weeks."""

from __future__ import annotations

from datetime import date

from app.analytics import goal_plan

# Whitney is a Saturday; today three-ish weeks out. A 16-week climb plan then
# spans 2026-04-13 (Mon) .. 2026-07-27 (event week), with 2026-07-06 current.
EVENT = date(2026, 8, 1)
TODAY = date(2026, 7, 10)


def _plan(weekly: list[dict] | None = None) -> dict:
    return goal_plan.goal_plan(
        event_name="Mount Whitney Summit",
        event_date=EVENT,
        event_kind="climb",
        today=TODAY,
        weekly_actual=weekly or [],
        event_vert_gain_ft=6100,
    )


def test_climb_plan_structure_and_anchoring() -> None:
    p = _plan()
    assert p["available"] is True
    assert p["peak_vert_ft"] == 6100  # from the event, not the kind default
    assert p["peak_miles"] == 30
    assert len(p["weeks"]) == 16
    # Anchored to the event's calendar week; last two weeks taper.
    assert p["weeks"][-1]["week_start"] == "2026-07-27"
    assert p["weeks"][-1]["phase"] == "Taper" and p["weeks"][-2]["phase"] == "Taper"
    assert p["weeks"][-3]["phase"] != "Taper"
    # Statuses relative to today.
    assert p["weeks"][0]["status"] == "elapsed"
    assert p["weeks"][-1]["status"] == "upcoming"
    current = [w for w in p["weeks"] if w["status"] == "current"]
    assert len(current) == 1 and current[0]["week_start"] == "2026-07-06"
    assert p["this_week"] is not None and p["this_week"]["phase"] == "Peak"


def test_targets_ramp_then_taper_and_vert_peaks_at_end_of_build() -> None:
    p = _plan()
    # Last build week (index 13 = week 14) hits full peak (factor 1.0).
    peak_week = p["weeks"][13]
    assert peak_week["target_vert_ft"] == 6100
    assert peak_week["target_miles"] == 30
    # Week 1 is well below peak; the final (taper) week is below peak too.
    assert p["weeks"][0]["target_miles"] < peak_week["target_miles"]
    assert p["weeks"][-1]["target_vert_ft"] < peak_week["target_vert_ft"]
    assert all(w["long_effort"] == "long hike" for w in p["weeks"])


def test_adherence_meets_targets_reads_on_track() -> None:
    base = _plan()
    # Feed back the exact targets for every elapsed week -> 100% on both axes.
    fed = [
        {"week": w["week_start"], "miles": w["target_miles"], "vert_ft": w["target_vert_ft"]}
        for w in base["weeks"]
        if w["status"] == "elapsed"
    ]
    p = _plan(fed)
    adh = p["adherence"]
    assert adh["available"] is True
    assert adh["miles_pct"] == 100 and adh["vert_ft_pct"] == 100
    assert adh["status"] == "on-track"
    assert adh["weeks_scored"] == len(fed)


def test_adherence_low_vert_is_behind_for_a_climb() -> None:
    base = _plan()
    # Plenty of miles but no climbing: a climb graded on vert reads "behind".
    fed = [
        {"week": w["week_start"], "miles": 25.0, "vert_ft": 0.0}
        for w in base["weeks"]
        if w["status"] == "elapsed"
    ]
    p = _plan(fed)
    adh = p["adherence"]
    assert adh["status"] == "behind"
    assert adh["vert_ft_pct"] < adh["miles_pct"]
    assert "vert" in adh["headline"].lower() or "climb" in adh["headline"].lower()


def test_weeks_before_actual_data_are_not_scored() -> None:
    base = _plan()
    elapsed = [w for w in base["weeks"] if w["status"] == "elapsed"]
    # Only the most recent elapsed week has data; earlier weeks predate it.
    last_elapsed = elapsed[-1]
    p = _plan([{"week": last_elapsed["week_start"], "miles": 10.0, "vert_ft": 500.0}])
    assert p["weeks"][0]["actual_miles"] is None  # before the data range
    scored = p["adherence"]["weeks_scored"]
    assert scored == 1  # only the in-range elapsed week counts


def test_missing_kind_and_no_event_vert_fall_back_to_defaults() -> None:
    p = goal_plan.goal_plan(
        event_name="Some Race",
        event_date=EVENT,
        event_kind="race",
        today=TODAY,
        weekly_actual=[],
    )
    assert p["peak_vert_ft"] == 1500  # race kind default, no event vert
    assert p["weeks"][0]["long_effort"] == "long run"
    assert p["taper_weeks"] == 2
