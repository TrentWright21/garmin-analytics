"""Morning Readiness Brief tests: safety ceiling, workout logic, formatting.

All pure and offline: the ceiling and fallback are deterministic functions, and
the AI path is exercised with a fake Anthropic client (no network). These cover
the required cases: good-recovery day, poor-recovery day, missing metrics, no
configured goal, the intensity clamp, and a graceful fallback on a bad response.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

from app.ai.morning_brief import (
    WorkoutRecommendation,
    _data_confidence,
    _merge_metrics,
    _prompt_payload,
    _week_summary,
    build_workout,
    fallback_workout,
    intensity_ceiling,
)
from app.config import GoalConfig, Settings
from app.notify.message import format_morning_message

TODAY = date(2026, 7, 8)


def _no_key_settings() -> Settings:
    """Settings with the Anthropic key cleared, so build_workout uses the fallback.

    The dev .env may carry a real GA_ANTHROPIC_API_KEY; nulling it keeps the
    no-key path offline and deterministic (no live API call from the test suite).
    """
    settings = Settings()
    settings.anthropic_api_key = None
    return settings


GOOD: dict[str, Any] = {
    "date": "2026-07-08",
    "readiness": {"score": 84, "band": "green", "drivers": []},
    "risk": {"risk_band": "green", "flag_count": 0, "flags": []},
    "recovery": {"available": True, "pct_recovered": 95, "recovered": True},
    "fitness": {"available": True, "form_tsb": 3.0, "form_state": "fresh"},
    "event": {"available": True, "name": "Whitney", "days_until": 24},
}

POOR: dict[str, Any] = {
    "date": "2026-07-08",
    "readiness": {"score": 28, "band": "red", "drivers": []},
    "risk": {
        "risk_band": "red",
        "flag_count": 1,
        "flags": [{"title": "HRV suppression", "severity": "red"}],
    },
    "recovery": {"available": True, "pct_recovered": 40, "recovered": False},
}

MISSING: dict[str, Any] = {
    "date": "2026-07-08",
    "readiness": {"available": False, "score": None, "band": "unknown", "drivers": []},
    "risk": {"risk_band": "green", "flag_count": 0, "flags": []},
    "recovery": {"available": False},
}


# -- deterministic safety ceiling ---------------------------------------------


def test_ceiling_good_day_allows_quality() -> None:
    ceiling, _ = intensity_ceiling(GOOD["readiness"], GOOD["risk"], GOOD["recovery"])
    assert ceiling == "hard"


def test_ceiling_poor_day_forces_rest() -> None:
    ceiling, reason = intensity_ceiling(POOR["readiness"], POOR["risk"], POOR["recovery"])
    assert ceiling == "rest"
    assert "HRV suppression" in reason


def test_ceiling_missing_metrics_is_conservative_easy() -> None:
    ceiling, _ = intensity_ceiling(MISSING["readiness"], MISSING["risk"], MISSING["recovery"])
    assert ceiling == "easy"


def test_ceiling_yellow_day_caps_at_easy() -> None:
    readiness = {"band": "yellow", "score": 60, "drivers": []}
    risk = {"risk_band": "green", "flag_count": 0, "flags": []}
    recovery = {"available": True, "recovered": True}
    ceiling, _ = intensity_ceiling(readiness, risk, recovery)
    assert ceiling == "easy"


def test_ceiling_load_flags_counted_once_not_summed() -> None:
    # One load spike drags readiness to yellow via its load penalty AND fires
    # two load-family flags. The old flat count made that 3 bad signals -> rest;
    # the two-axis ceiling strips the penalty (physiology is actually green) and
    # caps the load family at one contribution -> moderate.
    readiness = {"band": "yellow", "score": 62, "load_penalty": 12.0, "drivers": []}
    risk = {
        "flags": [
            {"code": "LOAD_SPIKE", "title": "Load ramping", "severity": "yellow"},
            {"code": "RAPID_RAMP", "title": "Fitness is ramping fast", "severity": "yellow"},
        ]
    }
    recovery = {"available": True, "recovered": True}
    ceiling, _ = intensity_ceiling(readiness, risk, recovery)
    assert ceiling == "moderate"


def test_ceiling_red_load_flag_with_clean_physiology_caps_easy() -> None:
    readiness = {"band": "green", "score": 80, "drivers": []}
    risk = {"flags": [{"code": "LOAD_SPIKE", "title": "Load is spiking", "severity": "red"}]}
    ceiling, _ = intensity_ceiling(readiness, risk, {"available": True, "recovered": True})
    assert ceiling == "easy"


def test_ceiling_physio_flags_still_stack_to_rest() -> None:
    readiness = {"band": "green", "score": 80, "drivers": []}
    risk = {
        "flags": [
            {"code": "HRV_SUPPRESSION", "title": "HRV is suppressed", "severity": "red"},
            {"code": "RHR_ELEVATED", "title": "Resting HR is elevated", "severity": "yellow"},
        ]
    }
    ceiling, _ = intensity_ceiling(readiness, risk, {"available": True, "recovered": True})
    assert ceiling == "rest"  # physiology axis: 2 + 1 = 3


def test_ceiling_blocks_back_to_back_hard_days() -> None:
    recent = [{"day": str(TODAY - timedelta(days=1)), "training_load": 220}]
    ceiling, reason = intensity_ceiling(
        GOOD["readiness"], GOOD["risk"], GOOD["recovery"], recent=recent, today=TODAY
    )
    assert ceiling == "easy"
    assert "back-to-back" in reason


def test_ceiling_hard_two_days_ago_allows_quality() -> None:
    recent = [{"day": str(TODAY - timedelta(days=2)), "training_load": 220}]
    ceiling, _ = intensity_ceiling(
        GOOD["readiness"], GOOD["risk"], GOOD["recovery"], recent=recent, today=TODAY
    )
    assert ceiling == "hard"


# -- rule-based fallback ------------------------------------------------------


def test_fallback_respects_each_ceiling() -> None:
    goal = GoalConfig(focus="endurance")
    assert fallback_workout("rest", goal, [], TODAY).intensity == "rest"
    assert fallback_workout("recovery", goal, [], TODAY).intensity == "recovery"
    assert fallback_workout("easy", goal, [], TODAY).intensity == "easy"
    moderate = fallback_workout("moderate", goal, [], TODAY)
    assert moderate.intensity == "moderate"
    assert moderate.summary and moderate.insight  # every ceiling has fallback text


def test_fallback_quality_day_picks_goal_workout() -> None:
    tempo = fallback_workout("hard", GoalConfig(focus="endurance"), [], TODAY)
    assert tempo.workout_type == "tempo"
    strength = fallback_workout("hard", GoalConfig(focus="strength"), [], TODAY)
    assert strength.workout_type == "strength"


def test_fallback_avoids_back_to_back_hard() -> None:
    recent = [{"day": str(TODAY - timedelta(days=1)), "training_load": 220}]
    rec = fallback_workout("hard", GoalConfig(focus="endurance"), recent, TODAY)
    assert rec.intensity == "easy"  # yesterday was hard -> keep today easy


def test_fallback_no_goal_still_returns_valid_workout() -> None:
    rec = fallback_workout("hard", GoalConfig(), [], TODAY)  # default focus
    assert rec.workout_type and rec.instructions and rec.why


# -- build_workout: fallback vs AI, and the clamp -----------------------------


class _Block:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _Msg:
    def __init__(self, text: str) -> None:
        self.content = [_Block(text)]


class _Messages:
    def __init__(self, text: str) -> None:
        self._text = text

    def create(self, **_kwargs: Any) -> _Msg:
        return _Msg(self._text)


class _Client:
    def __init__(self, text: str) -> None:
        self.messages = _Messages(text)


def _factory(text: str) -> Any:
    return lambda api_key: _Client(text)


def test_build_workout_without_key_uses_fallback() -> None:
    rec = build_workout(
        _no_key_settings(), GoalConfig(focus="endurance"), GOOD, [], {}, today=TODAY
    )
    assert rec.ai_generated is False
    assert rec.intensity in ("easy", "moderate", "hard")


def test_build_workout_ai_path_returns_model() -> None:
    body = (
        '{"summary":"You look recovered.",'
        '"insight":"Sleep and HRV are solid and load is manageable, so tempo fits today.",'
        '"workout_type":"tempo","intensity":"moderate","duration_min":40,'
        '"instructions":"15 min warm-up, 20 min tempo, cool down.",'
        '"why":"Recovered and endurance-focused.","watch_out":"Ease off if HR spikes."}'
    )
    rec = build_workout(
        Settings(),
        GoalConfig(focus="endurance"),
        GOOD,
        [],
        {},
        today=TODAY,
        client_factory=_factory(body),
    )
    assert rec.ai_generated is True
    assert rec.workout_type == "tempo"
    assert rec.intensity == "moderate"
    assert rec.summary == "You look recovered."
    assert rec.insight.startswith("Sleep and HRV")


def test_build_workout_clamps_ai_over_ceiling() -> None:
    # Poor-recovery day -> ceiling "rest"; the model tries to prescribe "hard".
    body = (
        '{"workout_type":"intervals","intensity":"hard","duration_min":60,'
        '"instructions":"6x800m hard.","why":"Feeling great.","watch_out":"None."}'
    )
    rec = build_workout(
        Settings(),
        GoalConfig(focus="endurance"),
        POOR,
        [],
        {},
        today=TODAY,
        client_factory=_factory(body),
    )
    assert rec.intensity == "rest"  # clamped down to the safety ceiling
    assert rec.workout_type == "rest"


def test_build_workout_bad_response_falls_back() -> None:
    rec = build_workout(
        Settings(),
        GoalConfig(focus="endurance"),
        GOOD,
        [],
        {},
        today=TODAY,
        client_factory=_factory("sorry, I cannot help with that"),
    )
    assert rec.ai_generated is False  # unparseable -> safe fallback


# -- message formatting -------------------------------------------------------


def _workout(**over: Any) -> WorkoutRecommendation:
    base: dict[str, Any] = {
        "workout_type": "easy_run",
        "intensity": "easy",
        "duration_min": 40,
        "instructions": "Easy 40 min, conversational.",
        "why": "Recovery is solid.",
        "watch_out": "Cut short if legs feel heavy.",
    }
    base.update(over)
    return WorkoutRecommendation(**base)


def test_format_morning_message_layout() -> None:
    workout = _workout(
        summary="You look recovered.",
        insight="Sleep and HRV are solid; a light aerobic day keeps you on track.",
    )
    latest = {
        "sleep_seconds": 25920,  # 7h 12m
        "sleep_score": 78,
        "deep_seconds": 3900,
        "resting_hr": 52,
        "hrv_last_night_avg": 66,
        "hrv_status": "BALANCED",
        "body_battery_high": 84,
        "vo2max_running": 48.2,
        "training_readiness": 72,
        "steps": 8240,
        "active_calories": 540,
    }
    brief = {
        **GOOD,
        "weather": {"available": True, "temp_high_f": 92.0, "dew_point_f": 74.0},
        "heat": {"available": True, "severity": "high", "advice": "run early + hydrate"},
    }
    recent = [{"day": str(TODAY - timedelta(days=1)), "name": "Easy Run", "distance_mi": 3.2}]
    title, text = format_morning_message(
        brief, GoalConfig(focus="half_marathon"), workout, latest, recent, today=TODAY
    )
    assert "Morning Readiness Brief" in title
    assert "You look recovered." in text  # AI summary
    assert "Insights:" in text  # AI insight section
    assert "Readiness 84/100 (green)" in text
    assert "Sleep 7h 12m" in text and "deep" in text
    assert "HRV 66ms (balanced)" in text and "RHR 52bpm" in text
    assert "VO2max 48" in text and "Garmin readiness 72" in text
    assert "8,240 steps" in text and "540 active cal" in text
    assert "Weather:" in text and "92°F" in text and "run early" in text
    assert "Last session: Easy Run 3.2 mi" in text
    assert "Half marathon" in text
    assert "Easy 40 min" in text and "Recovery is solid." in text


def test_format_omits_missing_metrics_gracefully() -> None:
    # Empty metrics + no weather: no crash, and nothing fabricated.
    title, text = format_morning_message(MISSING, GoalConfig(), _workout(), {}, [], today=TODAY)
    assert "Morning Readiness Brief" in title
    assert "VO2max" not in text and "Sleep" not in text and "Weather:" not in text


def test_fallback_sets_summary_and_insight() -> None:
    rec = fallback_workout("rest", GoalConfig(focus="endurance"), [], TODAY)
    assert rec.summary and rec.insight  # non-empty deterministic text


# -- weekly training summary ---------------------------------------------------


def _act(days_ago: int, miles: float, load: float, vert_m: float = 0.0) -> dict[str, Any]:
    return {
        "day": TODAY - timedelta(days=days_ago),
        "distance_m": miles * 1609.344,
        "duration_s": miles * 600,  # ~10 min/mile
        "elevation_gain_m": vert_m,
        "training_load": load,
    }


def test_week_summary_totals_and_prior_baseline() -> None:
    acts = [_act(i, 5.0, 100.0, vert_m=100.0) for i in range(7, 35)]  # 4 steady weeks
    acts += [_act(2, 10.0, 220.0, vert_m=300.0), _act(1, 5.0, 80.0, vert_m=50.0)]
    week = _week_summary(acts, TODAY)
    assert week["this_week"]["miles"] == pytest.approx(15.0, abs=0.1)
    assert week["this_week"]["hard_days"] == 1
    assert week["this_week"]["vert_ft"] == round(350 * 3.28084)
    assert week["prior_4wk_weekly_avg"]["miles"] == pytest.approx(35.0, abs=0.5)
    assert week["days_since_last_hard"] == 2
    assert week["consecutive_active_days"] == 2  # active yesterday + day before


def test_week_summary_empty_history() -> None:
    week = _week_summary([], TODAY)
    assert week["this_week"]["miles"] == 0.0
    assert week["days_since_last_hard"] is None
    assert week["consecutive_active_days"] == 0
    assert "prior_4wk_weekly_avg" not in week


# -- staleness detection --------------------------------------------------------


def test_merge_metrics_marks_fresh_overnight_data() -> None:
    m = _merge_metrics({"sleep_seconds": 25000, "resting_hr": 50}, {"steps": 9000})
    assert m["overnight_source"] == "today"
    assert m["overnight_stale"] is False
    assert m["sleep_seconds"] == 25000 and m["steps"] == 9000


def test_merge_metrics_flags_stale_fallback() -> None:
    m = _merge_metrics({}, {"sleep_seconds": 24000})
    assert m["overnight_source"] == "yesterday"
    assert m["overnight_stale"] is True
    assert m["sleep_seconds"] == 24000  # still shown, but marked

    empty = _merge_metrics({}, {})
    assert empty["overnight_source"] == "missing"
    assert empty["overnight_stale"] is True


# -- confidence + watch tomorrow -------------------------------------------------


FRESH_VITALS: dict[str, Any] = {
    "overnight_source": "today",
    "hrv_last_night_avg": 55,
    "resting_hr": 50,
    "sleep_seconds": 27000,
}


def test_data_confidence_levels() -> None:
    scored = {"band": "green", "score": 80}
    assert _data_confidence(scored, FRESH_VITALS) == "high"
    assert _data_confidence(scored, {"overnight_source": "today", "resting_hr": 50}) == "moderate"
    assert _data_confidence(scored, {"overnight_source": "yesterday"}) == "low"
    assert _data_confidence({"band": "unknown", "score": None}, FRESH_VITALS) == "low"


def test_build_workout_stamps_confidence_and_watch_tomorrow() -> None:
    rec = build_workout(
        _no_key_settings(), GoalConfig(focus="endurance"), GOOD, [], FRESH_VITALS, today=TODAY
    )
    assert rec.confidence == "high"
    assert rec.watch_tomorrow  # deterministic fallback fills it


def test_build_workout_ai_watch_tomorrow_kept_confidence_overridden() -> None:
    body = (
        '{"workout_type":"tempo","intensity":"moderate","duration_min":40,'
        '"instructions":"Tempo.","why":"Recovered.","watch_out":"Ease off.",'
        '"watch_tomorrow":"Check HRV after the tempo.","confidence":"high"}'
    )
    rec = build_workout(
        Settings(),
        GoalConfig(focus="endurance"),
        GOOD,
        [],
        {},  # no vitals at all -> deterministic confidence is low, whatever the model says
        today=TODAY,
        client_factory=_factory(body),
    )
    assert rec.watch_tomorrow == "Check HRV after the tempo."
    assert rec.confidence == "low"


# -- prompt payload context -------------------------------------------------------


def test_prompt_payload_includes_event_week_and_freshness() -> None:
    brief = {**GOOD, "week": {"this_week": {"miles": 15.0, "hard_days": 1}}}
    payload = _prompt_payload(
        GoalConfig(focus="endurance"), "hard", "ok", brief, [], {"overnight_source": "today"}
    )
    assert payload["goal_event"]["name"] == "Whitney"
    assert payload["goal_event"]["days_until"] == 24
    assert payload["week"]["this_week"]["miles"] == 15.0
    assert payload["data_freshness"]["overnight_data_from"] == "today"


def test_prompt_payload_without_event_is_null() -> None:
    payload = _prompt_payload(GoalConfig(), "easy", "ok", POOR, [], {})
    assert payload["goal_event"] is None
    assert payload["data_freshness"]["overnight_data_from"] == "unknown"


# -- message rendering: staleness, watch tomorrow, confidence ---------------------


def test_message_shows_stale_warning_watch_tomorrow_and_confidence() -> None:
    workout = _workout(watch_tomorrow="Check resting HR.", confidence="low")
    latest = {"overnight_source": "yesterday", "sleep_seconds": 25920, "resting_hr": 52}
    _, text = format_morning_message(GOOD, GoalConfig(), workout, latest, [], today=TODAY)
    assert "from yesterday" in text  # stale warning leads the current state
    assert "Watch tomorrow:\nCheck resting HR." in text
    assert "Confidence: low" in text


def test_message_no_stale_warning_when_fresh() -> None:
    latest = {"overnight_source": "today", "sleep_seconds": 25920}
    _, text = format_morning_message(GOOD, GoalConfig(), _workout(), latest, [], today=TODAY)
    assert "No sync yet" not in text and "missing" not in text
