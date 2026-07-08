"""Compose and send the morning message from the existing daily brief.

``format_brief`` is a pure function (dict in -> title + text out) so it is
unit-testable without the network. ``send_morning_briefing`` is the scheduled
job's entry point: build the brief, format it, optionally have Claude polish the
wording, and push it. Every step degrades gracefully — a missing section is
skipped, a polish failure falls back to the plain text, and an unconfigured
channel simply no-ops.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.config import DEFAULT_DATA_DIR, AppConfig, GoalConfig, Settings
from app.logging import get_logger
from app.notify import NotifyError, build_notifier

log = get_logger(__name__)

_POLISH_MODEL = "claude-opus-4-8"
_BAND_EMOJI = {"green": "🟢", "yellow": "🟡", "red": "🔴"}

# One-per-day guard: the ISO date of the last successful auto-send. Lives under
# data/ (mounted + persistent in Docker) so a restart near 06:30 can't double-send.
_STATE_FILE = DEFAULT_DATA_DIR / "last_morning_brief.txt"


def _already_sent_today(today: str) -> bool:
    try:
        return _STATE_FILE.read_text(encoding="utf-8").strip() == today
    except OSError:
        return False


def _mark_sent_today(today: str) -> None:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(today, encoding="utf-8")
    except OSError as exc:
        log.warning("notify.mark_failed", err=str(exc))


def _line(brief: dict[str, Any]) -> list[str]:
    """Build the plain-text body lines from a build_briefing() result."""
    out: list[str] = []

    r = brief.get("readiness") or {}
    if r.get("score") is not None:
        band = str(r.get("band", "")).lower()
        emoji = _BAND_EMOJI.get(band, "")
        out.append(f"{emoji} Readiness {r.get('score')}/100 ({band or 'n/a'})".strip())
        if r.get("recommendation"):
            out.append(f"  {r['recommendation']}")

    risk = brief.get("risk") or {}
    if risk.get("flag_count"):
        titles = ", ".join(f.get("title", "?") for f in risk.get("flags", [])[:3])
        out.append(f"⚠ Risk: {risk.get('risk_band', '?')} — {titles}")

    fit = brief.get("fitness") or {}
    if fit.get("available") and fit.get("form_tsb") is not None:
        state = fit.get("form_state", "")
        out.append(f"Form (TSB) {fit['form_tsb']:+.0f} {state}".rstrip())

    rec = brief.get("recovery") or {}
    if rec.get("available") and rec.get("pct_recovered") is not None:
        status = "recovered" if rec.get("recovered") else "still recovering"
        out.append(f"Recovery {rec.get('pct_recovered')}% ({status})")

    weather = brief.get("weather") or {}
    if weather.get("available") and weather.get("temp_high_f") is not None:
        parts = [f"High {weather['temp_high_f']}°F"]
        if weather.get("dew_point_f") is not None:
            parts.append(f"dew {weather['dew_point_f']}°F")
        out.append("Weather: " + ", ".join(parts))
    heat = brief.get("heat") or {}
    if heat.get("available") and heat.get("severity") in ("high", "extreme") and heat.get("advice"):
        out.append(f"🥵 {heat['advice']}")

    ev = brief.get("event") or {}
    if ev.get("available") and ev.get("days_until") is not None:
        out.append(f"📅 {ev.get('name', 'Goal')}: {ev['days_until']} days out")

    return out


def format_brief(brief: dict[str, Any]) -> tuple[str, str]:
    """Return (title, text) for the morning push. Never raises."""
    title = f"Waypoint — {brief.get('date', 'today')}"
    lines = _line(brief)
    text = "\n".join(lines) if lines else "No data yet — run a sync to populate your briefing."
    return title, text


def polish_message(settings: Settings, raw_text: str) -> str:
    """Best-effort: rewrite the brief as a short coach note via Claude.

    Returns ``raw_text`` unchanged on any error or if no API key is set, so the
    morning message is never lost to an LLM hiccup.
    """
    if settings.anthropic_api_key is None:
        return raw_text
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key.get_secret_value())
        msg = client.messages.create(
            model=_POLISH_MODEL,
            max_tokens=400,
            system=(
                "You are a concise running coach. Rewrite the bullet-point training "
                "briefing below into a short, warm good-morning note (3-5 sentences, "
                "no preamble, no markdown). Keep every number exactly as given; do not "
                "invent data. End with one clear suggestion for today."
            ),
            messages=[{"role": "user", "content": raw_text}],
        )
        parts = [b.text for b in msg.content if b.type == "text"]
        polished = "\n\n".join(parts).strip()
        return polished or raw_text
    except Exception as exc:
        # Polish is optional — any failure (network, API, parse) falls back to
        # the plain brief so the morning message is never lost.
        log.warning("notify.polish_failed", err=type(exc).__name__)
        return raw_text


# -- the full Morning Readiness Brief (current state + AI workout) -------------


def _fmt_sleep(seconds: Any) -> str | None:
    if not isinstance(seconds, (int, float)) or seconds <= 0:
        return None
    total = int(seconds)
    return f"{total // 3600}h {total % 3600 // 60:02d}m"


def _metric_line(latest: dict[str, Any]) -> str | None:
    """Sleep / HRV / RHR / Body Battery / stress, skipping whatever is missing."""
    parts: list[str] = []
    sleep = _fmt_sleep(latest.get("sleep_seconds"))
    if sleep:
        score = latest.get("sleep_score")
        parts.append(f"Sleep {sleep}" + (f" (score {int(score)})" if score is not None else ""))
    if latest.get("hrv_last_night_avg") is not None:
        parts.append(f"HRV {int(latest['hrv_last_night_avg'])}ms")
    if latest.get("resting_hr") is not None:
        parts.append(f"RHR {int(latest['resting_hr'])}bpm")
    if latest.get("body_battery_high") is not None:
        parts.append(f"Body Battery {int(latest['body_battery_high'])}")
    if latest.get("avg_stress") is not None:
        parts.append(f"Stress {int(latest['avg_stress'])}")
    return " · ".join(parts) if parts else None


def _last_activity_line(recent: list[dict[str, Any]], today: date) -> str | None:
    if not recent:
        return None
    last = recent[-1]
    label = last.get("name") or last.get("activity_type") or "Activity"
    when = "Yesterday" if str(last.get("day")) == str(today - timedelta(days=1)) else "Last"
    dist = last.get("distance_mi")
    return f"{when}: {label}" + (f" {dist} mi" if dist else "")


def _current_state_lines(brief: dict[str, Any], latest: dict[str, Any], today: date) -> list[str]:
    lines: list[str] = []
    r = brief.get("readiness") or {}
    if r.get("score") is not None:
        band = str(r.get("band", "")).lower()
        emoji = _BAND_EMOJI.get(band, "")
        lines.append(f"{emoji} Readiness {r.get('score')}/100 ({band or 'n/a'})".strip())
    metric = _metric_line(latest)
    if metric:
        lines.append(metric)
    risk = brief.get("risk") or {}
    if risk.get("flag_count"):
        titles = ", ".join(f.get("title", "?") for f in risk.get("flags", [])[:3])
        lines.append(f"⚠ Risk ({risk.get('risk_band', '?')}): {titles}")
    rec = brief.get("recovery") or {}
    if rec.get("available") and rec.get("pct_recovered") is not None:
        status = "recovered" if rec.get("recovered") else "still recovering"
        lines.append(f"Recovery {rec.get('pct_recovered')}% ({status})")
    return lines


def _pretty_goal(goal: GoalConfig, brief: dict[str, Any]) -> str:
    focus = goal.focus.replace("_", " ").strip()
    focus = focus[:1].upper() + focus[1:] if focus else "General fitness"
    text = focus + (f" — {goal.note}" if goal.note else "")
    ev = brief.get("event") or {}
    if ev.get("available") and ev.get("days_until") is not None:
        text += f"\n\U0001f4c5 {ev.get('name', 'Goal event')}: {ev['days_until']} days out"
    return text


def format_morning_message(
    brief: dict[str, Any],
    goal: GoalConfig,
    workout: Any,
    latest: dict[str, Any],
    recent: list[dict[str, Any]],
    today: date | None = None,
) -> tuple[str, str]:
    """Assemble the phone-readable brief in the fixed section layout. Never raises."""
    today = today or date.today()
    title = f"Morning Readiness Brief — {brief.get('date', today)}"

    state = _current_state_lines(brief, latest, today)
    last = _last_activity_line(recent, today)
    if last:
        state.append(last)
    if not state:
        state = ["No data yet — run a sync to populate your briefing."]

    dur = f" — {workout.duration_min} min" if workout.duration_min else ""
    wtype = str(workout.workout_type).replace("_", " ")
    wtype = wtype[:1].upper() + wtype[1:]

    blocks = [
        "Current State:\n" + "\n".join(state),
        "Goal:\n" + _pretty_goal(goal, brief),
        f"Today's Workout:\n{wtype}{dur}\n{workout.instructions}",
        "Why:\n" + str(workout.why),
        "Watch out:\n" + str(workout.watch_out),
    ]
    return title, "\n\n".join(blocks)


def compose_morning_message(settings: Settings, cfg: AppConfig) -> tuple[str, str]:
    """Gather today's data, get the (AI or fallback) workout, and format the brief."""
    from app.ai.morning_brief import build_workout, gather_context

    brief, recent, latest = gather_context()
    workout = build_workout(settings, cfg.goal, brief, recent, latest)
    return format_morning_message(brief, cfg.goal, workout, latest, recent)


def send_morning_briefing(settings: Settings, cfg: AppConfig, *, force: bool = False) -> bool:
    """Build and send today's brief. Returns True if a message was delivered.

    ``force`` bypasses the once-per-day guard (used by the manual CLI test); the
    scheduled job leaves it False so a restart near 06:30 can't double-send.
    """
    notifier = build_notifier(settings)
    if notifier is None:
        log.info("notify.skipped", reason="channel_not_configured")
        return False

    today = str(date.today())
    if not force and _already_sent_today(today):
        log.info("notify.skipped", reason="already_sent_today")
        return False

    title, text = compose_morning_message(settings, cfg)
    if cfg.notify.ai_polish:
        text = polish_message(settings, text)

    try:
        notifier.send(title, text)
    except NotifyError as exc:
        log.warning("notify.send_failed", err=str(exc))
        return False
    _mark_sent_today(today)
    log.info("morning_message.sent", date=today)
    return True
