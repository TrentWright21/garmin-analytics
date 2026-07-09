"""Morning Readiness Brief tests: safety ceiling, workout logic, formatting.

All pure and offline: the ceiling and fallback are deterministic functions, and
the AI path is exercised with a fake Anthropic client (no network). These cover
the required cases: good-recovery day, poor-recovery day, missing metrics, no
configured goal, the intensity clamp, and a graceful fallback on a bad response.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.ai.morning_brief import (
    WorkoutRecommendation,
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


# -- rule-based fallback ------------------------------------------------------


def test_fallback_respects_each_ceiling() -> None:
    goal = GoalConfig(focus="endurance")
    assert fallback_workout("rest", goal, [], TODAY).intensity == "rest"
    assert fallback_workout("recovery", goal, [], TODAY).intensity == "recovery"
    assert fallback_workout("easy", goal, [], TODAY).intensity == "easy"


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
