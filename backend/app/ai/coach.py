"""AI Coach: Claude answers questions about the user's own Garmin trends.

Architecture: tool use, not prompt-stuffing. Each tool below is a thin
wrapper around the EXISTING analytics functions in ``app.analytics.engine``
— loaders bridge DB -> Polars, the pure functions compute, and the wrapper
compacts the already-computed numbers into small JSON so Claude reasons over
real values it fetched itself. No analytics logic is duplicated here.

The tools are plain functions (directly callable in tests); ``COACH_TOOLS``
wraps them with the SDK's ``beta_tool`` for the tool-runner loop. The
Anthropic client is injected via ``client_factory`` so tests never touch the
network.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import anthropic
from anthropic import beta_tool
from anthropic.lib.tools import BetaFunctionTool
from anthropic.types.beta import BetaMessageParam, BetaThinkingConfigAdaptiveParam

from app.analytics import engine as ax
from app.analytics import fitness, readiness, session
from app.analytics.physiology import estimate_hr_max
from app.config import Settings, get_app_config

MODEL = "claude-opus-4-8"
MAX_TOKENS = 16000

NOT_CONFIGURED_MESSAGE = (
    "The AI Coach is not configured. Add GA_ANTHROPIC_API_KEY=sk-ant-... to the "
    ".env file in the project folder (get a key at https://platform.claude.com), "
    "then restart the app. Everything else works without it."
)

SYSTEM_PROMPT = """\
You are Coach, the in-app training assistant of Waypoint, a personal analytics
dashboard for the user's Garmin data. You advise the one runner whose data this
is, using their own numbers.

Rules:
- Ground every number in tool results from this conversation. Never invent,
  estimate, or recall values the tools did not return. If data is missing or
  the sample is small, say so plainly.
- Call tools before answering anything about the user's data or trends.
- Be honest about uncertainty; a 30-day history supports weaker conclusions
  than a year.
- Keep answers brief and practical: a few sentences or a short list, with one
  clear recommendation when advice is asked for. The dashboard already shows
  charts - you add interpretation, not data dumps.
- Use imperial units (miles, min/mile pace, degrees F) unless asked otherwise,
  converting from the metric values in tool output.
- You are a running/endurance coach, not a medical professional. If asked
  about symptoms, injury, illness, or medication, say you cannot give medical
  advice and recommend seeing a professional; you may still discuss training
  load in general terms.
"""


class CoachNotConfiguredError(RuntimeError):
    """Raised when the Coach is used without GA_ANTHROPIC_API_KEY set."""


def _range(days: int) -> tuple[date, date]:
    end = date.today()
    return end - timedelta(days=days - 1), end


def _round(value: Any, ndigits: int = 1) -> Any:
    """Round floats for compact JSON; pass everything else through."""
    if isinstance(value, float):
        return round(value, ndigits)
    return value


def _compact(row: dict[str, Any]) -> dict[str, Any]:
    """Drop nulls and round floats so tool output stays small."""
    return {k: _round(v) for k, v in row.items() if v is not None}


def _js(obj: Any) -> str:
    return json.dumps(obj, default=str, separators=(",", ":"))


# -- tools (plain functions; wrapped for the runner at the bottom) -------------

_DAILY_COLS = [
    "day",
    "steps",
    "resting_hr",
    "hrv_last_night_avg",
    "sleep_score",
    "sleep_seconds",
    "avg_stress",
    "body_battery_high",
    "training_readiness",
    "vo2max_running",
    "weight_kg",
]


def get_daily_metrics(days: int = 30) -> str:
    """Day-by-day health metrics for the most recent N days.

    Returns one row per day with steps, resting HR, overnight HRV, sleep score
    and duration (seconds), stress, Body Battery peak, Garmin training
    readiness, running VO2max, and weight (kg). Use for questions about
    specific recent days or short-term patterns.

    Args:
        days: How many days back to include, 1-365. Keep small (7-60) unless
            the question truly needs more.
    """
    days = max(1, min(days, 365))
    start, end = _range(days)
    df = ax.load_daily(start, end)
    if df.is_empty():
        return _js({"days": days, "rows": [], "note": "no data in range"})
    cols = [c for c in _DAILY_COLS if c in df.columns]
    rows = [_compact(r) for r in df.sort("day").select(cols).to_dicts()]
    return _js({"days": days, "rows": rows})


def get_rolling_trends(days: int = 90) -> str:
    """Rolling-average trends: where each key metric stands now vs ~30 days ago.

    For each metric returns the current 7-day and 30-day rolling means plus the
    7-day mean from roughly 30 days earlier, so direction and size of change
    are directly comparable. Metrics: steps, resting HR, HRV, sleep score,
    stress, Body Battery, training readiness, VO2max, weight (kg).

    Args:
        days: History window to compute over, 45-365 (default 90).
    """
    days = max(45, min(days, 365))
    start, end = _range(days)
    df = ax.rolling_trends(ax.load_daily(start, end))
    if df.is_empty():
        return _js({"trends": {}, "note": "no data in range"})
    df = df.sort("day")
    last = df.tail(1).to_dicts()[0]
    prior = df[max(0, df.height - 31)].to_dicts()[0]
    trends: dict[str, dict[str, Any]] = {}
    for metric in ax.TREND_METRICS:
        entry = {
            "now_7d_avg": _round(last.get(f"{metric}_r7")),
            "now_30d_avg": _round(last.get(f"{metric}_r30")),
            "7d_avg_30_days_ago": _round(prior.get(f"{metric}_r7")),
        }
        if any(v is not None for v in entry.values()):
            trends[metric] = {k: v for k, v in entry.items() if v is not None}
    return _js({"as_of": str(last["day"]), "window_days": days, "trends": trends})


def get_training_load(days: int = 90) -> str:
    """Training load: daily ACWR and weekly Foster monotony/strain.

    Returns the last 14 days of load with acute (7-day EWMA, the PMC's ATL)
    and chronic (28-day EWMA) values and their ratio (ACWR), all over the same
    daily-load series as the Performance Management Chart. Reference: ACWR
    sweet spot ~0.8-1.3; treat higher values as a caution to add easy days,
    not an injury prediction. Monotony >2.0 with high load predicts overtraining.

    Args:
        days: History window to compute over, 42-365 (default 90).
    """
    days = max(42, min(days, 365))
    start, end = _range(days)
    load = ax.load_training_load(start, end)
    if load.is_empty():
        return _js({"note": "no activities in range"})
    acwr_rows = [_compact(r) for r in ax.acwr(load).tail(14).to_dicts()]
    # monotony is a trailing-7d daily series; sample one row per week (newest
    # first, then restore order) to keep this the "last 4 weeks" view.
    mono = ax.monotony(load)
    if not mono.is_empty():
        mono = mono.reverse().gather_every(7).head(4).reverse()
    mono_rows = [_compact(r) for r in mono.to_dicts()]
    return _js(
        {
            "acwr_last_14_days": acwr_rows,
            "weekly_monotony_strain": mono_rows,
            "reference": {
                "acwr_definition": "7d EWMA acute / 28d EWMA chronic, one shared load series",
                "acwr_sweet_spot": "0.8-1.3",
                "acwr_caution": ">1.5 sustained — a heuristic caution, not an injury prediction",
                "monotony_risk": ">2.0 with high weekly load",
            },
        }
    )


def get_insights() -> str:
    """Auto-generated findings from up to a year of data.

    Rule-based, pre-computed observations (resting-HR change, sleep vs Body
    Battery, HRV fatigue flag, temperature vs pace). May be empty with short
    history - that means no finding cleared its evidence bar, not that
    nothing is happening.
    """
    start, end = _range(365)
    daily = ax.load_daily(start, end)
    acts = ax.load_activities(start, end)
    return _js({"insights": ax.generate_insights(daily, acts)})


def get_recent_activities(limit: int = 10) -> str:
    """The user's most recent workouts, newest last.

    Per activity: date, type, name, distance (m), duration (s), elevation
    gain (m), avg/max HR, avg temperature (C), and Garmin training load.

    Args:
        limit: Number of most recent activities to return, 1-50 (default 10).
    """
    limit = max(1, min(limit, 50))
    start, end = _range(365)
    df = ax.load_activities(start, end)
    if df.is_empty():
        return _js({"activities": [], "note": "no activities in the last year"})
    cols = [
        "day",
        "activity_type",
        "name",
        "distance_m",
        "duration_s",
        "elevation_gain_m",
        "avg_hr",
        "max_hr",
        "avg_temp_c",
        "training_load",
    ]
    present = [c for c in cols if c in df.columns]
    rows = [_compact(r) for r in df.sort("start_time_local").tail(limit).select(present).to_dicts()]
    return _js({"activities": rows})


def _hr_max() -> float:
    configured = get_app_config().athlete.hr_max
    return estimate_hr_max(ax.load_activities(), ax.load_daily(), configured=configured)


def get_fitness_form(days: int = 180) -> str:
    """Fitness / Fatigue / Form from the Performance Management Chart.

    Returns the latest CTL (Fitness, 42-day load average), ATL (Fatigue, 7-day),
    TSB (Form = CTL-ATL), the 7-day ramp rate, a form-state label, and a plain
    interpretation. Use for "how fit am I", "am I fresh/overreached", peaking,
    or ramp-rate questions.

    Args:
        days: History window to build the model over, 28-365 (default 180).
    """
    days = max(28, min(days, 365))
    start, end = _range(days)
    load = ax.load_training_load(start, end)
    return _js(fitness.fitness_summary(load))


def get_readiness_detail() -> str:
    """Today's Red/Yellow/Green readiness with its ranked drivers.

    Returns the 0-100 score, the band (green/yellow/red), each visible component
    (HRV, resting HR, sleep, Body Battery, stress), the drivers worst-first, any
    training-load penalty, and a one-line recommendation. Use for "how ready am
    I today", "should I do my hard workout", daily go/no-go questions.
    """
    start, end = _range(90)
    daily = ax.load_daily(start, end)
    load = ax.load_training_load(start, end)
    return _js(readiness.daily_readiness(daily, load, today=end))


def get_risk_flags() -> str:
    """Overtraining / injury-risk flags with the evidence behind each.

    Returns an overall risk band plus any fired flags (load spike / ACWR, HRV
    suppression, elevated resting HR, monotony, sleep-vs-load mismatch, rapid
    ramp, deep fatigue), each with a severity and the numbers that triggered it.
    Use for "am I overtraining", "injury risk", "is my load safe" questions.
    """
    start, end = _range(90)
    daily = ax.load_daily(start, end)
    acts = ax.load_activities(start, end)
    load = ax.training_load_for(acts)
    return _js(readiness.risk_flags(daily, acts, load))


def get_intensity_distribution(days: int = 42) -> str:
    """Aerobic vs anaerobic training distribution (polarized-training view).

    Buckets each session by average HR into easy/moderate/hard, sums the time in
    each, and reports percentages plus a verdict (polarized / grey-zone-heavy /
    too-hard / all-easy). Use for "am I running too hard on easy days", "is my
    intensity balanced", "80/20" questions.

    Args:
        days: Window to summarize, 7-365 (default 42).
    """
    days = max(7, min(days, 365))
    start, end = _range(days)
    return _js(fitness.intensity_distribution(ax.load_activities(start, end), _hr_max()))


def get_briefing() -> str:
    """Today's full morning brief in one call: the go/no-go daily snapshot.

    Aggregates readiness (Red/Yellow/Green + drivers), injury-risk flags,
    Fitness/Fatigue/Form, today's local weather with a dew-point heat advisory
    for running, the training streak, a recovery timer (hours since the last
    session and when the athlete is recovered), and the countdown to the goal
    event. Use for "give me my morning briefing", "what should I do today",
    or any broad "how am I doing right now" question.
    """
    from app.api.routes.briefing import build_briefing

    return _js(build_briefing())


def get_workout_analysis(activity_id: int) -> str:
    """Deep analysis of one workout by its Garmin activity id.

    Returns effort/zone, efficiency factor, a physiological breakdown, comparison
    to the user's baseline for similar sessions (pace & efficiency deltas),
    aerobic decoupling when lap data exists, and specific insights. Get the
    activity_id from get_recent_activities first. Use for "how was my run on X",
    "break down my last workout", "was that a good session".

    Args:
        activity_id: Garmin activity id from get_recent_activities.
    """
    activity = ax.load_activity(activity_id)
    if activity is None:
        return _js({"error": "activity not found", "activity_id": activity_id})
    history = ax.load_activities()
    return _js(session.analyze_session(activity, history, _hr_max()))


COACH_TOOLS: list[BetaFunctionTool[Any]] = [
    beta_tool(get_daily_metrics),
    beta_tool(get_rolling_trends),
    beta_tool(get_training_load),
    beta_tool(get_insights),
    beta_tool(get_recent_activities),
    beta_tool(get_fitness_form),
    beta_tool(get_readiness_detail),
    beta_tool(get_risk_flags),
    beta_tool(get_intensity_distribution),
    beta_tool(get_briefing),
    beta_tool(get_workout_analysis),
]


# -- the coach itself ---------------------------------------------------------


def is_configured(settings: Settings) -> bool:
    return settings.anthropic_api_key is not None


class Coach:
    """Runs one conversational turn against Claude with the analytics tools.

    ``client_factory`` is injectable so tests can substitute a fake client -
    the test suite must never make real API calls.
    """

    def __init__(
        self,
        settings: Settings,
        client_factory: Callable[..., anthropic.Anthropic] = anthropic.Anthropic,
    ) -> None:
        if settings.anthropic_api_key is None:
            raise CoachNotConfiguredError(NOT_CONFIGURED_MESSAGE)
        self._client = client_factory(api_key=settings.anthropic_api_key.get_secret_value())

    def reply(self, history: list[dict[str, str]], user_message: str) -> str:
        """One turn: replay stored history, add the new message, run tools, answer.

        The API is stateless; ``history`` is the conversation so far as
        ``{"role": ..., "content": ...}`` dicts loaded from the DB (the store
        only ever writes the roles "user" and "assistant").
        """
        messages: list[BetaMessageParam] = [
            {"role": "assistant" if m["role"] == "assistant" else "user", "content": m["content"]}
            for m in history
        ]
        messages.append({"role": "user", "content": user_message})
        runner = self._client.beta.messages.tool_runner(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            thinking=BetaThinkingConfigAdaptiveParam(type="adaptive"),
            system=SYSTEM_PROMPT,
            tools=COACH_TOOLS,
            messages=messages,
        )
        final = runner.until_done()
        parts = [block.text for block in final.content if block.type == "text"]
        return "\n\n".join(parts).strip()
