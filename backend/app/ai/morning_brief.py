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

from app.analytics.readiness import GREEN_MIN, YELLOW_MIN
from app.config import DEFAULT_DATA_DIR, AppConfig, GoalConfig, Settings
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

    workout_type: (
        str  # easy_run|long_run|intervals|tempo|recovery|strength|cross_training|long_hike|rest
    )
    intensity: Intensity
    duration_min: int | None = None
    instructions: str
    why: str
    watch_out: str
    summary: str = ""  # one-line readiness headline (AI or fallback)
    insight: str = ""  # short interpretation of the metrics (AI or fallback)
    watch_tomorrow: str = ""  # the one signal to check tomorrow (AI or fallback)
    confidence: str = ""  # high|moderate|low — always stamped deterministically
    ai_generated: bool = False


def _rank(intensity: Intensity) -> int:
    return _ORDER.index(intensity)


def _clamp(intensity: Intensity, ceiling: Intensity) -> Intensity:
    """Never allow an intensity harder than the safety ceiling."""
    return intensity if _rank(intensity) <= _rank(ceiling) else ceiling


# Risk-flag codes that derive from the training-load series. They all restate
# one underlying fact ("you trained a lot lately"), so the ceiling counts the
# worst of them ONCE instead of summing them — otherwise a single load spike
# (which also drags the readiness band down via its load penalty) forced rest
# days while HRV, resting HR, and sleep were all fine.
_LOAD_FLAG_CODES = frozenset({"LOAD_SPIKE", "MONOTONY", "RAPID_RAMP", "DEEP_FATIGUE"})

# Hard-day detection for the back-to-back spacing rule and the weekly summary.
# Garmin Training Effect is the primary signal (it measures intensity directly):
# a hard session label or meaningful anaerobic TE. Sessions without TE data fall
# back to the training-load proxy.
_HARD_LOAD = 150.0
_HARD_ANAEROBIC_TE = 2.5
_HARD_TE_LABELS = frozenset(
    {
        "TEMPO",
        "THRESHOLD",
        "LACTATE_THRESHOLD",
        "VO2MAX",
        "ANAEROBIC",
        "ANAEROBIC_CAPACITY",
        "SPEED",
    }
)


def _is_hard_session(session: dict[str, Any]) -> bool:
    """True if one session looks like a hard effort. TE first, load as fallback."""
    label = str(session.get("te_label") or "").upper()
    if label in _HARD_TE_LABELS:
        return True
    anaerobic = session.get("anaerobic_te")
    if isinstance(anaerobic, (int, float)) and anaerobic >= _HARD_ANAEROBIC_TE:
        return True
    if session.get("aerobic_te") is not None or anaerobic is not None:
        # TE data present and says easy — trust it over the load-volume proxy.
        return False
    load = session.get("training_load")
    return isinstance(load, (int, float)) and load >= _HARD_LOAD


def _physio_band(readiness: dict[str, Any]) -> str:
    """The readiness band with the training-load penalty stripped back out.

    ``daily_readiness`` subtracts a load penalty (ACWR / deep TSB) from the
    physiological score before banding. The ceiling scores load on its own
    axis, so here we recover the physiology-only band from score + penalty to
    avoid counting the same load signal on both axes.
    """
    band = str(readiness.get("band", "unknown"))
    score = readiness.get("score")
    penalty = readiness.get("load_penalty") or 0.0
    if score is None or not penalty:
        return band
    base = min(100.0, float(score) + float(penalty))
    return "green" if base >= GREEN_MIN else "yellow" if base >= YELLOW_MIN else "red"


def _hard_effort_on(recent: list[dict[str, Any]], day: date) -> bool:
    """True if any session on ``day`` looks like a hard effort."""
    return any(str(s.get("day")) == str(day) and _is_hard_session(s) for s in recent)


def intensity_ceiling(
    readiness: dict[str, Any],
    risk: dict[str, Any],
    recovery: dict[str, Any],
    recent: list[dict[str, Any]] | None = None,
    today: date | None = None,
) -> tuple[Intensity, str]:
    """Hardest intensity allowed today, from recovery signals. Pure + auditable.

    Two independent axes, so one cause is never counted twice:

    * **Physiology** — how the body responded: the load-penalty-free readiness
      band, physiological risk flags (HRV, resting HR, sleep), and an
      unrecovered last session. These stack: 1 -> easy, 2 -> recovery, 3+ -> rest.
    * **Load** — how much training piled up: the *worst single* load-family
      flag (LOAD_SPIKE / MONOTONY / RAPID_RAMP / DEEP_FATIGUE), never summed.
      With clean physiology: red -> easy, yellow -> moderate.

    On top of both: a deterministic spacing rule — a hard effort yesterday caps
    today at easy (no back-to-back hard days), enforced in code on the AI and
    fallback paths alike. ``recent``/``today`` are optional so older callers
    and tests that only score the signals keep working.

    Missing readiness (fresh install / no data) is treated conservatively as
    ``easy`` — enough to move, never a hard session on unknown recovery.
    """
    band = readiness.get("band")
    if band in (None, "unknown"):
        return "easy", "Not enough recent data to judge recovery — keep it easy."

    physio = 0
    load_axis = 0
    reasons: list[str] = []

    physio_band = _physio_band(readiness)
    if physio_band == "red":
        physio += 2
        reasons.append("readiness red")
    elif physio_band == "yellow":
        physio += 1
        reasons.append("readiness yellow")

    for flag in risk.get("flags", []):
        title = str(flag.get("title", "risk flag"))
        severity = 2 if flag.get("severity") == "red" else 1
        if flag.get("code") in _LOAD_FLAG_CODES:
            load_axis = max(load_axis, severity)
        else:
            physio += severity
        reasons.append(title)

    if recovery.get("available") and recovery.get("recovered") is False:
        physio += 1
        reasons.append("last session still settling")

    if physio >= 3:
        ceiling: Intensity = "rest"
    elif physio == 2:
        ceiling = "recovery"
    elif physio == 1 or load_axis >= 2:
        ceiling = "easy"
    elif load_axis == 1:
        ceiling = "moderate"
    else:
        ceiling = "hard"

    if (
        today is not None
        and recent
        and _rank(ceiling) > _rank("easy")
        and _hard_effort_on(recent, today - timedelta(days=1))
    ):
        ceiling = "easy"
        reasons.append("hard workout yesterday — no back-to-back hard days")

    reason = "; ".join(reasons) if reasons else "recovery signals look good"
    return ceiling, reason


# -- rule-based fallback (used with no API key or on any LLM error) ------------

_ENDURANCE = {"marathon", "half_marathon", "15k", "10k", "5k", "endurance", "climb"}
# Climb/summit goals get vert + time-on-feet on quality days, not tempo runs.
_CLIMB = {"climb", "hike", "summit", "mountaineering"}


def _yesterday_was_hard(recent: list[dict[str, Any]], today: date) -> bool:
    """True if any session yesterday looked like a hard effort."""
    return _hard_effort_on(recent, today - timedelta(days=1))


_FALLBACK_SUMMARY: dict[Intensity, str] = {
    "rest": "Recovery is low today - prioritize rest.",
    "recovery": "You're a bit run down - keep it to active recovery.",
    "easy": "You're okay but not sharp - keep today easy.",
    "moderate": "You're recovered, but training load is piling up - keep today controlled.",
    "hard": "You look recovered - good for quality if your goal supports it.",
}
_FALLBACK_INSIGHT: dict[Intensity, str] = {
    "rest": "Several signals are down, so absorbing recent training beats adding more load.",
    "recovery": "Signals are soft; gentle movement aids recovery without adding stress.",
    "easy": "Build aerobic volume today and save the intensity for a fresher day.",
    "moderate": "Your body has responded well, but recent volume is already elevated; "
    "a steady day adds fitness without stacking risk on top of the load.",
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
    if ceiling == "moderate":
        # Physiology is fine but the training-load axis is flagged: volume ok,
        # no intensity on top of an already-elevated load.
        return WorkoutRecommendation(
            workout_type="easy_run" if endurance else "cross_training",
            intensity="moderate",
            duration_min=40,
            instructions="Steady 35-45 min at a controlled effort. No surges, no racing.",
            why="You're recovered, but recent load is elevated - add volume, not intensity.",
            watch_out="If it stops feeling comfortable, drop back to fully easy.",
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
    if focus in _CLIMB:
        return WorkoutRecommendation(
            workout_type="long_hike",
            intensity="moderate",
            duration_min=90,
            instructions=(
                "Long vert-focused hike: 60-120 min of steady climbing, weighted pack if "
                "training for a loaded summit. No trail handy? Stairs or steep treadmill "
                "incline work."
            ),
            why="You're recovered and your goal is a climb - vertical gain and time on "
            "feet build summit fitness better than running speed.",
            watch_out="Keep the climbing effort conversational; ease the descents if "
            "knees or ankles complain.",
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
  moving the session indoors. When best_run_window is given, name that window as
  the time to head out.
- Adjust to condition: poor sleep / low body battery / poor recovery -> easier or
  recovery; high readiness with supportive recent load -> harder; high training
  load -> avoid piling on intensity; little recent training -> ease back in.
- Use the goal event countdown when one is given: far out -> build volume; close
  in -> sharpen and protect freshness. Reference it when it shapes the choice.
- Respect the weekly context: if this week's volume already exceeds the 4-week
  average, don't pile on; if a hard day happened in the last 2 days, keep today
  easy regardless of how good the recovery numbers look.
- If data_freshness says the overnight data is from yesterday or missing, say so
  and be more conservative — do not treat stale numbers as this morning's.
- garmin_view holds Garmin's own verdicts (training status, native recovery timer,
  acute load). When Garmin disagrees with the computed metrics, reconcile the
  disagreement out loud (e.g. "Garmin calls this week unproductive, but your form
  is rising...") instead of ignoring either side.
- Only use numbers you are given. If a key metric is missing, say so rather than
  guessing. Fitness guidance, not medical advice. Keep it concise and phone-readable.

Return ONLY a JSON object (no prose, no markdown) with exactly these keys:
  "summary": one short sentence on overall readiness (e.g. "You look recovered").
  "insight": 2-3 sentences interpreting the data (fatigue/recovery/sleep/readiness/
             training + weather). Concrete, specific to today's numbers, no fluff.
  "workout_type": one of easy_run, long_run, intervals, tempo, recovery,
                  strength, cross_training, long_hike, rest
  "intensity": one of rest, recovery, easy, moderate, hard  (<= the ceiling)
  "duration_min": integer minutes, or null for a rest day
  "instructions": 1-2 sentences, specific and actionable
  "why": 1 sentence explaining the workout choice from the data
  "watch_out": 1 sentence — a safer fallback if the athlete feels off today
  "watch_tomorrow": 1 short sentence — the single most useful signal to check
                    tomorrow morning, given today's data and workout
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
    event = brief.get("event") or {}
    return {
        "goal": {"focus": goal.focus, "note": goal.note},
        "goal_event": (
            {
                "name": event.get("name"),
                "date": event.get("date"),
                "days_until": event.get("days_until"),
                "weeks_until": event.get("weeks_until"),
                "kind": event.get("kind"),
            }
            if event.get("available")
            else None
        ),
        "week": brief.get("week"),
        "data_freshness": {"overnight_data_from": latest.get("overnight_source", "unknown")},
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
        "garmin_view": {
            "training_status": latest.get("training_status"),
            "recovery_time_h": _min_to_hours(latest.get("recovery_time_min")),
            "acute_load": latest.get("acute_load_garmin"),
            "acwr": latest.get("acwr_garmin"),
            "hrv_weekly_avg": latest.get("hrv_weekly_avg"),
        },
        "sleep": {
            "hours": _sleep_hours(latest.get("sleep_seconds")),
            "score": latest.get("sleep_score"),
            "deep_hours": _sleep_hours(latest.get("deep_seconds")),
            "rem_hours": _sleep_hours(latest.get("rem_seconds")),
            "awake_hours": _sleep_hours(latest.get("awake_seconds")),
            "body_battery_recharge": latest.get("body_battery_change"),
            "restless_moments": latest.get("restless_moments"),
            "skin_temp_deviation_c": latest.get("skin_temp_dev_c"),
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
        "best_run_window": (
            {
                "label": window.get("label"),
                "avg_temp_f": window.get("avg_temp_f"),
                "avg_dew_point_f": window.get("avg_dew_point_f"),
            }
            if (window := brief.get("run_window") or {}).get("available")
            else None
        ),
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


def _min_to_hours(minutes: Any) -> float | None:
    if not isinstance(minutes, (int, float)):
        return None
    return round(minutes / 60, 1)


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
    readiness = brief.get("readiness") or {}
    ceiling, reason = intensity_ceiling(
        readiness,
        brief.get("risk") or {},
        brief.get("recovery") or {},
        recent=recent,
        today=today,
    )
    rec = fallback_workout(ceiling, goal, recent, today)

    if settings.anthropic_api_key is not None or client_factory is not None:
        try:
            ai = _ai_workout(settings, goal, ceiling, reason, brief, recent, latest, client_factory)
            # Defence in depth: clamp whatever the model returned under the ceiling.
            ai.intensity = _clamp(ai.intensity, ceiling)
            if ai.intensity in ("rest", "recovery") and ai.workout_type not in (
                "rest",
                "recovery",
            ):
                ai.workout_type = ai.intensity
            ai.ai_generated = True
            rec = ai
        except Exception as exc:
            # Any AI or parse failure (network, API, bad JSON) falls back to the
            # safe rule-based workout so the morning message is never lost.
            log.warning("morning_brief.ai_failed", err=type(exc).__name__)

    # Confidence is stamped deterministically on BOTH paths (same philosophy as
    # the intensity clamp: honesty about data quality is not delegated to the LLM).
    rec.confidence = _data_confidence(readiness, latest)
    if not rec.watch_tomorrow.strip():
        rec.watch_tomorrow = _fallback_watch(readiness, rec.intensity)
    return rec


def _data_confidence(readiness: dict[str, Any], latest: dict[str, Any]) -> str:
    """Deterministic high/moderate/low grade of today's data quality. Pure.

    Low when the overnight data is stale/missing or readiness could not be
    scored; high only when readiness scored AND all three key vitals (HRV,
    resting HR, sleep) are present from last night; moderate in between.
    """
    if latest.get("overnight_source") in ("yesterday", "missing"):
        return "low"
    if readiness.get("band") in (None, "unknown") or readiness.get("score") is None:
        return "low"
    key_vitals = ("hrv_last_night_avg", "resting_hr", "sleep_seconds")
    present = sum(1 for k in key_vitals if latest.get(k) is not None)
    if present == len(key_vitals):
        return "high"
    return "moderate" if present >= 1 else "low"


_FALLBACK_WATCH: dict[Intensity, str] = {
    "rest": "Check whether resting HR has come back down toward baseline.",
    "recovery": "See if HRV rebounds overnight - that clears you for easy volume.",
    "easy": "Watch tomorrow's readiness score; an easy day usually lifts it.",
    "moderate": "Check how your legs respond to today before adding intensity.",
    "hard": "Watch tonight's sleep - recovery decides whether to stack another quality day.",
}


def _fallback_watch(readiness: dict[str, Any], intensity: Intensity) -> str:
    """Deterministic 'signal to watch tomorrow': the worst readiness driver when
    one is clearly down, else a sensible default for today's intensity."""
    drivers = readiness.get("drivers") or []
    if drivers:
        worst = drivers[0]
        if worst.get("verdict") == "low" and worst.get("label"):
            return f"Check {str(worst['label']).lower()} tomorrow morning - it's today's limiter."
    return _FALLBACK_WATCH[intensity]


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


# -- the day's workout, cached once per day -----------------------------------

# One recommendation per calendar day, shared by every consumer: the Telegram
# morning message computes fresh (post-sync) and overwrites; the dashboard's
# Today screen reads the cache first — so the page and the message can never
# disagree, and opening the page doesn't burn extra AI calls.
_WORKOUT_CACHE = DEFAULT_DATA_DIR / "todays_workout.json"


def save_workout_cache(rec: WorkoutRecommendation, today: date) -> None:
    """Persist the day's recommendation. Best-effort — never raises."""
    try:
        _WORKOUT_CACHE.parent.mkdir(parents=True, exist_ok=True)
        payload = {"date": str(today), "workout": rec.model_dump()}
        _WORKOUT_CACHE.write_text(json.dumps(payload), encoding="utf-8")
    except OSError as exc:
        log.warning("morning_brief.workout_cache_write_failed", err=str(exc))


def load_cached_workout(today: date) -> dict[str, Any] | None:
    """The cached recommendation, or None when missing/stale/unreadable."""
    try:
        raw = json.loads(_WORKOUT_CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or raw.get("date") != str(today):
        return None  # a previous day's plan is worse than none
    return raw


def todays_workout(settings: Settings, cfg: AppConfig, *, force: bool = False) -> dict[str, Any]:
    """The day's recommendation: cache hit when fresh, else compute + cache.

    ``force`` recomputes (the 06:30 sender uses it so the message always
    reflects post-sync data, then overwrites the cache for the page).
    """
    today = date.today()
    if not force:
        cached = load_cached_workout(today)
        if cached is not None:
            return cached
    brief, recent, latest = gather_context()
    rec = build_workout(settings, cfg.goal, brief, recent, latest, today=today)
    save_workout_cache(rec, today)
    return {"date": str(today), "workout": rec.model_dump()}


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
    "elevation_gain_m",
    "avg_hr",
    "training_load",
    "aerobic_te",
    "anaerobic_te",
    "te_label",
)

_FT_PER_M = 3.28084


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _week_summary(activities: list[dict[str, Any]], today: date) -> dict[str, Any]:
    """Weekly training context for the AI payload. Pure; totals in imperial.

    ``activities`` is up to ~5 weeks of activity dicts (day, distance_m,
    duration_s, elevation_gain_m, training_load). Returns this week's totals
    (the 7 days ending today), the prior 4 weeks' per-week averages when that
    history exists, and the spacing counters the coach needs: days since the
    last hard day and the current run of consecutive active days.
    """
    rows = [(d, r) for r in activities if (d := _as_date(r.get("day"))) is not None]
    week_start = today - timedelta(days=6)
    prior_start = today - timedelta(days=34)

    def _totals(chunk: list[tuple[date, dict[str, Any]]]) -> tuple[float, float, float, int]:
        miles = sum(float(r.get("distance_m") or 0) for _, r in chunk) / _METERS_PER_MILE
        hours = sum(float(r.get("duration_s") or 0) for _, r in chunk) / 3600.0
        vert = sum(float(r.get("elevation_gain_m") or 0) for _, r in chunk) * _FT_PER_M
        hard_days = {d for d, r in chunk if _is_hard_session(r)}
        return miles, hours, vert, len(hard_days)

    this_week = [(d, r) for d, r in rows if week_start <= d <= today]
    prior = [(d, r) for d, r in rows if prior_start <= d < week_start]

    miles, hours, vert, hard = _totals(this_week)
    out: dict[str, Any] = {
        "this_week": {
            "miles": round(miles, 1),
            "duration_h": round(hours, 1),
            "vert_ft": round(vert),
            "hard_days": hard,
        }
    }
    if prior:
        p_miles, p_hours, p_vert, p_hard = _totals(prior)
        out["prior_4wk_weekly_avg"] = {
            "miles": round(p_miles / 4, 1),
            "duration_h": round(p_hours / 4, 1),
            "vert_ft": round(p_vert / 4),
            "hard_days": round(p_hard / 4, 1),
        }

    hard_days_all = {d for d, r in rows if _is_hard_session(r)}
    out["days_since_last_hard"] = (today - max(hard_days_all)).days if hard_days_all else None

    # Consecutive active days ending yesterday: 0 means yesterday was a rest day.
    active = {d for d, _ in rows}
    streak = 0
    cursor = today - timedelta(days=1)
    while cursor in active:
        streak += 1
        cursor -= timedelta(days=1)
    out["consecutive_active_days"] = streak
    return out


def gather_context() -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Load today's brief, ~5 weeks of activities, and last night's metrics.

    Returns ``(brief, recent_activities, latest_metrics)``; the brief also
    gains a ``week`` block (this week's totals vs the prior 4-week average) for
    the AI payload and, later, the message. The only function here that reads
    the database; everything else is pure so it can be unit-tested.
    """
    from app.analytics import engine as ax
    from app.api.routes.briefing import build_briefing

    today = date.today()
    brief = build_briefing()

    acts = ax.load_activities(*_range(35))
    recent: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []
    if not acts.is_empty():
        present = [c for c in _ACT_COLS if c in acts.columns]
        all_rows = acts.sort("start_time_local").select(present).to_dicts()
        for row in all_rows[-8:]:
            row = dict(row)
            dist = row.get("distance_m")
            row["distance_mi"] = round(dist / _METERS_PER_MILE, 2) if dist else None
            recent.append({k: v for k, v in row.items() if v is not None})
    brief["week"] = _week_summary(all_rows, today)

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
    "body_battery_change",
    "restless_moments",
    "skin_temp_dev_c",
)
_DAY_TOTAL_KEYS = ("steps", "active_calories", "total_calories", "intensity_minutes", "floors_up")
_CURRENT_KEYS = (
    "training_readiness",
    "vo2max_running",
    "weight_kg",
    "training_status",
    "recovery_time_min",
    "acute_load_garmin",
    "hrv_weekly_avg",
    "acwr_garmin",
)


def _merge_metrics(today_row: dict[str, Any], yesterday_row: dict[str, Any]) -> dict[str, Any]:
    """One metrics dict. Overnight + current fields prefer today's row (last night)
    but fall back to yesterday's so a not-yet-synced morning still shows the most
    recent values; day-total fields (steps/calories) come from yesterday's complete
    day, never today's partial one.

    The fallback is marked, never silent: ``overnight_source`` records where the
    overnight numbers came from ("today" | "yesterday" | "missing") and
    ``overnight_stale`` is True whenever they are NOT from last night — the
    message and the AI payload both surface it.
    """
    metrics: dict[str, Any] = {}
    for k in (*_OVERNIGHT_KEYS, *_CURRENT_KEYS):
        val = today_row.get(k)
        metrics[k] = val if val is not None else yesterday_row.get(k)
    for k in _DAY_TOTAL_KEYS:
        metrics[k] = yesterday_row.get(k)

    if any(today_row.get(k) is not None for k in _OVERNIGHT_KEYS):
        metrics["overnight_source"] = "today"
    elif any(yesterday_row.get(k) is not None for k in _OVERNIGHT_KEYS):
        metrics["overnight_source"] = "yesterday"
    else:
        metrics["overnight_source"] = "missing"
    metrics["overnight_stale"] = metrics["overnight_source"] != "today"
    return metrics
