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
from app.config import Settings

MODEL = "claude-opus-4-8"
MAX_TOKENS = 16000

NOT_CONFIGURED_MESSAGE = (
    "The AI Coach is not configured. Add GA_ANTHROPIC_API_KEY=sk-ant-... to the "
    ".env file in the project folder (get a key at https://platform.claude.com), "
    "then restart the app. Everything else works without it."
)

SYSTEM_PROMPT = """\
You are Coach, the in-app training assistant of a personal Garmin analytics
dashboard. You advise the one runner whose data this is, using their own
numbers.

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

    Returns the last 14 days of load with acute (7d) and chronic (28d)
    averages and their ratio (ACWR), plus the last 4 weeks of monotony and
    strain. Reference: ACWR sweet spot ~0.8-1.3, sustained >1.5 = elevated
    injury risk; monotony >2.0 with high load predicts overtraining.

    Args:
        days: History window to compute over, 42-365 (default 90).
    """
    days = max(42, min(days, 365))
    start, end = _range(days)
    load = ax.daily_training_load(ax.load_activities(start, end))
    if load.is_empty():
        return _js({"note": "no activities in range"})
    acwr_rows = [_compact(r) for r in ax.acwr(load).tail(14).to_dicts()]
    mono_rows = [_compact(r) for r in ax.monotony(load).tail(4).to_dicts()]
    return _js(
        {
            "acwr_last_14_days": acwr_rows,
            "weekly_monotony_strain": mono_rows,
            "reference": {
                "acwr_sweet_spot": "0.8-1.3",
                "acwr_elevated_risk": ">1.5 sustained",
                "monotony_risk": ">2.0 with high weekly load",
            },
        }
    )


def get_readiness() -> str:
    """Today's composite readiness score (0-100) with its visible components.

    Components (each 0-100): HRV vs personal 60-day baseline, last night's
    sleep score, Body Battery peak, and inverted stress. The score is the
    component average - not Garmin's black-box number.
    """
    start, end = _range(90)
    return _js(ax.readiness_score(ax.load_daily(start, end)))


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


COACH_TOOLS: list[BetaFunctionTool[Any]] = [
    beta_tool(get_daily_metrics),
    beta_tool(get_rolling_trends),
    beta_tool(get_training_load),
    beta_tool(get_readiness),
    beta_tool(get_insights),
    beta_tool(get_recent_activities),
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
