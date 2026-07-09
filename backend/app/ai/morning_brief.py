"""Morning Readiness Brief: an AI-recommended workout with deterministic safety.

``build_briefing`` (app.api.routes.briefing) already computes the current-state
snapshot — readiness band, injury-risk flags, fitness/form, recovery timer. This
module turns that snapshot, the athlete's configured goal, and their recent
training into a concrete workout recommendation for today.

Safety is **deterministic, not delegated to the LLM**. ``intensity_ceiling`` maps
the readiness band + risk flags + recovery state to the hardest intensity allowed
today. The LLM only fills in the specifics *within* that ceiling, and its answer
is clamped back to the ceiling before it is ever sent. With no API key — or on
any LLM error — a rule-based fallback produces a sane, safe workout, so the
morning message is never lost.

Clean separation (each piece is unit-testable in isolation):
  * data collection   -> ``gather_context`` (the only DB-touching function)
  * readiness scoring  -> reused from app.analytics (readiness/risk/recovery)
  * ceiling / safety   -> ``intensity_ceiling`` (pure)
  * recommendation     -> ``build_workout`` (pure inputs; AI + fallback)
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel

from app.config import GoalConfig, Settings
from app.logging import get_logger

log = get_logger(__name__)

Intensity = Literal["rest", "recovery", "easy", "moderate", "hard"]
# Ordered easiest -> hardest; index gives a comparable rank for clamping.
_ORDER: tuple[Intensity, ...] = ("rest", "recovery", "easy", "moderate", "hard")
_MODEL = "claude-opus-4-8"
_MAX_TOKENS = 800

_METERS_PER_MILE = 1609.344


class WorkoutRecommendation(BaseModel):
    """One day's prescription. ``intensity`` is always clamped to the ceiling."""

    workout_type: str  # easy_run|long_run|intervals|tempo|recovery|strength|cross_training|rest
    intensity: Intensity
    duration_min: int | None = None
    instructions: str
    why: str
    watch_out: str
    summary: str = ""  # one-line readiness headline (AI or fallback)
    insight: str = ""  # short interpretation of the metrics (AI or fallback)
    ai_generated: bool = False


def _rank(intensity: Intensity) -> int:
    return _ORDER.index(intensity)


def _clamp(intensity: Intensity, ceiling: Intensity) -> Intensity:
    """Never allow an intensity harder than the safety ceiling."""
    return intensity if _rank(intensity) <= _rank(ceiling) else ceiling


def intensity_ceiling(
    readiness: dict[str, Any],
    risk: dict[str, Any],
    recovery: dict[str, Any],
) -> tuple[Intensity, str]:
    """Hardest intensity allowed today, from recovery signals. Pure + auditable.

    Counts "bad signals" (red readiness, each risk flag, an unrecovered last
    session) and maps the total to a ceiling::

        0 -> hard (quality allowed)   2 -> recovery
        1 -> easy                     3+ -> rest

    Missing readiness (fresh install / no data) is treated conservatively as
    ``easy`` — enough to move, never a hard session on unknown recovery.
    """
    band = readiness.get("band")
    if band in (None, "unknown"):
        return "easy", "Not enough recent data to judge recovery — keep it easy."

    bad = 0
    reasons: list[str] = []
    if band == "red":
        bad += 2
        reasons.append("readiness red")
    elif band == "yellow":
        bad += 1
        reasons.append("readiness yellow")

    for flag in risk.get("flags", []):
        title = str(flag.get("title", "risk flag"))
        if flag.get("severity") == "red":
            bad += 2
            reasons.append(title)
        else:
            bad += 1
            reasons.append(title)

    if recovery.get("available") and recovery.get("recovered") is False:
        bad += 1
        reasons.append("last session still settling")

    if bad >= 3:
        ceiling: Intensity = "rest"
    elif bad == 2:
        ceiling = "recovery"
    elif bad == 1:
        ceiling = "easy"
    else:
        ceiling = "hard"

    reason = "; ".join(reasons) if reasons else "recovery signals look good"
    return ceiling, reason


# -- rule-based fallback (used with no API key or on any LLM error) ------------

_ENDURANCE = {"marathon", "half_marathon", "15k", "10k", "5k", "endurance", "climb"}


def _yesterday_was_hard(recent: list[dict[str, Any]], today: date) -> bool:
    """True if the most recent session was yesterday and looked like a hard effort."""
    if not recent:
        return False
    last = recent[-1]
    day = last.get("day")
    if str(day) != str(today - timedelta(days=1)):
        return False
    load = last.get("training_load")
    return isinstance(load, (int, float)) and load >= 150


_FALLBACK_SUMMARY: dict[Intensity, str] = {
    "rest": "Recovery is low today - prioritize rest.",
    "recovery": "You're a bit run down - keep it to active recovery.",
    "easy": "You're okay but not sharp - keep today easy.",
    "hard": "You look recovered - good for quality if your goal supports it.",
}
_FALLBACK_INSIGHT: dict[Intensity, str] = {
    "rest": "Several signals are down, so absorbing recent training beats adding more load.",
    "recovery": "Signals are soft; gentle movement aids recovery without adding stress.",
    "easy": "Build aerobic volume today and save the intensity for a fresher day.",
    "hard": "Recovery supports a harder session; keep it aligned with your goal and recent load.",
}


def fallback_workout(
    ceiling: Intensity,
    goal: GoalConfig,
    recent: list[dict[str, Any]],
    today: date,
) -> WorkoutRecommendation:
    """Deterministic, goal-aware workout within the ceiling, with a plain summary
    + insight so the message reads the same shape as the AI path. Never raises.
    """
    rec = _fallback_core(ceiling, goal, recent, today)
    rec.summary = _FALLBACK_SUMMARY[ceiling]
    rec.insight = _FALLBACK_INSIGHT[ceiling]
    return rec


def _fallback_core(
    ceiling: Intensity,
    goal: GoalConfig,
    recent: list[dict[str, Any]],
    today: date,
) -> WorkoutRecommendation:
    """The workout body for each ceiling (summary/insight stamped by the caller)."""
    focus = goal.focus.lower().strip()
    endurance = focus in _ENDURANCE or "run" in focus

    if ceiling == "rest":
        return WorkoutRecommendation(
            workout_type="rest",
            intensity="rest",
            duration_min=None,
            instructions="Full rest day. Gentle mobility or a short walk only if you want to move.",
            why="Recovery signals are down today, so absorbing load beats training through it.",
            watch_out="Resist training through it; a rest day now protects the whole week.",
        )
    if ceiling == "recovery":
        return WorkoutRecommendation(
            workout_type="recovery",
            intensity="recovery",
            duration_min=25,
            instructions="20-30 min very easy: walk, spin, or gentle jog at conversational HR.",
            why="Recovery signals are soft, so keep blood moving without adding stress.",
            watch_out="If you still feel flat, make it a full rest day instead.",
        )
    if ceiling == "easy":
        return WorkoutRecommendation(
            workout_type="easy_run" if endurance else "cross_training",
            intensity="easy",
            duration_min=40,
            instructions="Easy aerobic effort, 30-45 min, fully conversational. Nothing fast.",
            why="Recovery is okay but not sharp, so build aerobic volume without intensity.",
            watch_out="If your legs feel heavy or HR runs high, cut it to 25 min easy.",
        )

    # ceiling == "hard": quality allowed, but avoid stacking hard days.
    if _yesterday_was_hard(recent, today):
        return WorkoutRecommendation(
            workout_type="easy_run" if endurance else "cross_training",
            intensity="easy",
            duration_min=40,
            instructions="Easy 30-45 min. Yesterday was a hard effort, so keep today aerobic.",
            why="You're recovered, but back-to-back hard days add injury risk, not fitness.",
            watch_out="Keep it truly easy; save the quality for a fresher day.",
        )
    if focus == "strength":
        return WorkoutRecommendation(
            workout_type="strength",
            intensity="moderate",
            duration_min=45,
            instructions="Full-body strength: compound lifts, 3-4 sets, 1-2 reps in reserve.",
            why="You're recovered and your goal is strength, so today suits quality work.",
            watch_out="Warm up thoroughly; stop a set if form breaks down.",
        )
    if endurance:
        return WorkoutRecommendation(
            workout_type="tempo",
            intensity="moderate",
            duration_min=40,
            instructions="15 min easy warm-up, 20 min comfortably-hard tempo, 5 min cool-down.",
            why="You're recovered and endurance-focused, so tempo builds threshold safely.",
            watch_out="Tempo is comfortably hard, not a race; drop to steady if HR spikes.",
        )
    return WorkoutRecommendation(
        workout_type="easy_run",
        intensity="moderate",
        duration_min=40,
        instructions="35-45 min steady, with 4 relaxed strides at the end if you feel good.",
        why="You're recovered, so a steady session fits general fitness well today.",
        watch_out="Keep it controlled; no need to push into hard breathing.",
    )


# -- AI recommendation (within the ceiling; falls back on any failure) ---------

_SYSTEM = """\
You are Coach, a direct, honest endurance/running coach writing this athlete's
morning brief. You are given their recovery + training metrics, recent workouts,
today's weather, and their goal.

Hard rules:
- A SAFETY CEILING is provided (rest < recovery < easy < moderate < hard). NEVER
  prescribe an intensity above the ceiling, whatever the goal. If the ceiling is
  rest or recovery, prescribe rest or active recovery only.
- Interpret the data; don't just restate numbers. Reason about fatigue, recovery,
  sleep, readiness, and training direction, keeping the goal and recent load in mind.
- Use today's weather: if it's hot/humid or bad, suggest going earlier, easier, or
  moving the session indoors.
- Adjust to condition: poor sleep / low body battery / poor recovery -> easier or
  recovery; high readiness with supportive recent load -> harder; high training
  load -> avoid piling on intensity; little recent training -> ease back in.
- Only use numbers you are given. If a key metric is missing, say so rather than
  guessing. Fitness guidance, not medical advice. Keep it concise and phone-readable.

Return ONLY a JSON object (no prose, no markdown) with exactly these keys:
  "summary": one short sentence on overall readiness (e.g. "You look recovered").
  "insight": 2-3 sentences interpreting the data (fatigue/recovery/sleep/readiness/
             training + weather). Concrete, specific to today's numbers, no fluff.
  "workout_type": one of easy_run, long_run, intervals, tempo, recovery,
                  strength, cross_training, rest
  "intensity": one of rest, recovery, easy, moderate, hard  (<= the ceiling)
  "duration_min": integer minutes, or null for a rest day
  "instructions": 1-2 sentences, specific and actionable
  "why": 1 sentence explaining the workout choice from the data
  "watch_out": 1 sentence — a safer fallback if the athlete feels off today
"""


def _prompt_payload(
    goal: GoalConfig,
    ceiling: Intensity,
    ceiling_reason: str,
    brief: dict[str, Any],
    recent: list[dict[str, Any]],
    latest: dict[str, Any],
) -> dict[str, Any]:
    """Compact, JSON-serializable context for the model. Pure. Missing values are
    passed through as null so the model can see (and say) what is unavailable."""
    readiness = brief.get("readiness") or {}
    risk = brief.get("risk") or {}
    fitness = brief.get("fitness") or {}
    recovery = brief.get("recovery") or {}
    weather = brief.get("weather") or {}
    heat = brief.get("heat") or {}
    return {
        "goal": {"focus": goal.focus, "note": goal.note},
        "safety_ceiling": ceiling,
        "ceiling_reason": ceiling_reason,
        "readiness": {
            "score": readiness.get("score"),
            "band": readiness.get("band"),
            "drivers": readiness.get("drivers", [])[:3],
            "garmin_training_readiness": latest.get("training_readiness"),
        },
        "risk_flags": [
            {"title": f.get("title"), "severity": f.get("severity")} for f in risk.get("flags", [])
        ],
        "training_load": {
            "fitness_ctl": fitness.get("fitness_ctl"),
            "fatigue_atl_acute_load": fitness.get("fatigue_atl"),
            "form_tsb": fitness.get("form_tsb"),
            "form_state": fitness.get("form_state"),
            "ramp_flag": fitness.get("ramp_flag"),
        },
        "recovery": {
            "recovered": recovery.get("recovered"),
            "pct_recovered": recovery.get("pct_recovered"),
        },
        "sleep": {
            "hours": _sleep_hours(latest.get("sleep_seconds")),
            "score": latest.get("sleep_score"),
            "deep_hours": _sleep_hours(latest.get("deep_seconds")),
            "rem_hours": _sleep_hours(latest.get("rem_seconds")),
            "awake_hours": _sleep_hours(latest.get("awake_seconds")),
        },
        "vitals": {
            "resting_hr": latest.get("resting_hr"),
            "hrv_avg": latest.get("hrv_last_night_avg"),
            "hrv_status": latest.get("hrv_status"),
            "body_battery_high": latest.get("body_battery_high"),
            "avg_stress": latest.get("avg_stress"),
            "vo2max": latest.get("vo2max_running"),
            "respiration_avg": latest.get("respiration_avg"),
        },
        "yesterday": {
            "steps": latest.get("steps"),
            "active_calories": latest.get("active_calories"),
            "intensity_minutes": latest.get("intensity_minutes"),
        },
        "weather_today": _weather_payload(weather, heat) if weather.get("available") else None,
        "recent_activities": recent[-8:],
    }


def _weather_payload(weather: dict[str, Any], heat: dict[str, Any]) -> dict[str, Any]:
    return {
        "high_f": weather.get("temp_high_f"),
        "low_f": weather.get("temp_low_f"),
        "feels_like_f": weather.get("apparent_high_f"),
        "humidity_pct": weather.get("humidity_pct"),
        "dew_point_f": weather.get("dew_point_f"),
        "wind_mph": weather.get("wind_mph"),
        "heat_severity": heat.get("severity") if heat.get("available") else None,
        "heat_advice": heat.get("advice") if heat.get("available") else None,
    }


def _sleep_hours(seconds: Any) -> float | None:
    if not isinstance(seconds, (int, float)) or seconds <= 0:
        return None
    return round(seconds / 3600, 1)


def build_workout(
    settings: Settings,
    goal: GoalConfig,
    brief: dict[str, Any],
    recent: list[dict[str, Any]],
    latest: dict[str, Any],
    *,
    today: date | None = None,
    client_factory: Callable[..., Any] | None = None,
) -> WorkoutRecommendation:
    """Recommend today's workout: deterministic ceiling, AI specifics, safe fallback.

    Pure with respect to I/O except the optional Claude call — all data comes in
    as arguments so tests drive it with synthetic frames and a mocked client.
    """
    today = today or date.today()
    ceiling, reason = intensity_ceiling(
        brief.get("readiness") or {},
        brief.get("risk") or {},
        brief.get("recovery") or {},
    )
    fallback = fallback_workout(ceiling, goal, recent, today)

    if settings.anthropic_api_key is None and client_factory is None:
        return fallback

    try:
        rec = _ai_workout(settings, goal, ceiling, reason, brief, recent, latest, client_factory)
    except Exception as exc:
        # Any AI or parse failure (network, API, bad JSON) falls back to the safe
        # rule-based workout so the morning message is never lost.
        log.warning("morning_brief.ai_failed", err=type(exc).__name__)
        return fallback

    # Defence in depth: clamp whatever the model returned back under the ceiling.
    rec.intensity = _clamp(rec.intensity, ceiling)
    if rec.intensity in ("rest", "recovery") and rec.workout_type not in ("rest", "recovery"):
        rec.workout_type = rec.intensity
    rec.ai_generated = True
    return rec


def _ai_workout(
    settings: Settings,
    goal: GoalConfig,
    ceiling: Intensity,
    ceiling_reason: str,
    brief: dict[str, Any],
    recent: list[dict[str, Any]],
    latest: dict[str, Any],
    client_factory: Callable[..., Any] | None,
) -> WorkoutRecommendation:
    """Single Claude call -> validated WorkoutRecommendation. Raises on any problem."""
    import anthropic

    factory: Callable[..., Any] = client_factory or anthropic.Anthropic
    key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else "test"
    client: Any = factory(api_key=key)
    payload = _prompt_payload(goal, ceiling, ceiling_reason, brief, recent, latest)
    msg: Any = client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        system=_SYSTEM,
        messages=[{"role": "user", "content": json.dumps(payload, default=str)}],
    )
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    return WorkoutRecommendation.model_validate_json(_json_object(text))


def _json_object(text: str) -> str:
    """Extract the first {...} block so stray prose/markdown fences don't break parsing."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object found in model response")
    return text[start : end + 1]


# -- data collection (the only DB-touching function) --------------------------


def _range(days: int) -> tuple[date, date]:
    end = date.today()
    return end - timedelta(days=days - 1), end


_ACT_COLS = (
    "day",
    "activity_type",
    "name",
    "distance_m",
    "duration_s",
    "avg_hr",
    "training_load",
)


def gather_context() -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Load today's brief, the last 14 days of activities, and last night's metrics.

    Returns ``(brief, recent_activities, latest_metrics)``. The only function here
    that reads the database; everything else is pure so it can be unit-tested.
    """
    from app.analytics import engine as ax
    from app.api.routes.briefing import build_briefing

    today = date.today()
    brief = build_briefing()

    acts = ax.load_activities(*_range(14))
    recent: list[dict[str, Any]] = []
    if not acts.is_empty():
        present = [c for c in _ACT_COLS if c in acts.columns]
        for row in acts.sort("start_time_local").tail(8).select(present).to_dicts():
            dist = row.get("distance_m")
            row["distance_mi"] = round(dist / _METERS_PER_MILE, 2) if dist else None
            recent.append({k: v for k, v in row.items() if v is not None})

    # Overnight metrics (sleep/HRV/RHR) come from today's row; day-total metrics
    # (steps/calories/intensity) from yesterday's complete day.
    daily = ax.load_daily(*_range(4))
    rows = {str(r["day"]): r for r in daily.to_dicts()} if not daily.is_empty() else {}
    metrics = _merge_metrics(rows.get(str(today), {}), rows.get(str(today - timedelta(days=1)), {}))
    return brief, recent, metrics


_OVERNIGHT_KEYS = (
    "resting_hr",
    "hrv_last_night_avg",
    "hrv_status",
    "sleep_seconds",
    "sleep_score",
    "deep_seconds",
    "light_seconds",
    "rem_seconds",
    "awake_seconds",
    "body_battery_high",
    "avg_stress",
    "respiration_avg",
    "spo2_avg",
)
_DAY_TOTAL_KEYS = ("steps", "active_calories", "total_calories", "intensity_minutes", "floors_up")
_CURRENT_KEYS = ("training_readiness", "vo2max_running", "weight_kg")


def _merge_metrics(today_row: dict[str, Any], yesterday_row: dict[str, Any]) -> dict[str, Any]:
    """One metrics dict. Overnight + current fields prefer today's row (last night)
    but fall back to yesterday's so a not-yet-synced morning still shows the most
    recent values; day-total fields (steps/calories) come from yesterday's complete
    day, never today's partial one."""
    metrics: dict[str, Any] = {}
    for k in (*_OVERNIGHT_KEYS, *_CURRENT_KEYS):
        val = today_row.get(k)
        metrics[k] = val if val is not None else yesterday_row.get(k)
    for k in _DAY_TOTAL_KEYS:
        metrics[k] = yesterday_row.get(k)
    return metrics
