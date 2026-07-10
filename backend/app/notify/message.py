"""Compose and send the morning message from the existing daily brief.

``format_brief`` is a pure function (dict in -> title + text out) so it is
unit-testable without the network. ``send_morning_briefing`` is the scheduled
job's entry point: build the brief, format it, optionally have Claude polish the
wording, and push it. Every step degrades gracefully — a missing section is
skipped, a polish failure falls back to the plain text, and an unconfigured
channel simply no-ops.
"""

from __future__ import annotations

from datetime import date
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


def _sleep_line(latest: dict[str, Any]) -> str | None:
    sleep = _fmt_sleep(latest.get("sleep_seconds"))
    if not sleep:
        return None
    parts = [f"Sleep {sleep}"]
    if latest.get("sleep_score") is not None:
        parts.append(f"score {int(latest['sleep_score'])}")
    deep = _fmt_sleep(latest.get("deep_seconds"))
    if deep:
        parts.append(f"deep {deep}")
    rem = _fmt_sleep(latest.get("rem_seconds"))
    if rem:
        parts.append(f"REM {rem}")
    return " · ".join(parts)


def _vitals_line(latest: dict[str, Any]) -> str | None:
    parts: list[str] = []
    hrv = latest.get("hrv_last_night_avg")
    if hrv is not None:
        status = latest.get("hrv_status")
        parts.append(f"HRV {int(hrv)}ms" + (f" ({str(status).lower()})" if status else ""))
    if latest.get("resting_hr") is not None:
        parts.append(f"RHR {int(latest['resting_hr'])}bpm")
    if latest.get("body_battery_high") is not None:
        battery = f"Body Battery {int(latest['body_battery_high'])}"
        if latest.get("body_battery_change") is not None:
            battery += f" ({int(latest['body_battery_change']):+d} overnight)"
        parts.append(battery)
    if latest.get("avg_stress") is not None:
        parts.append(f"Stress {int(latest['avg_stress'])}")
    return " · ".join(parts) if parts else None


def _activity_totals_line(latest: dict[str, Any]) -> str | None:
    parts: list[str] = []
    if latest.get("steps") is not None:
        parts.append(f"{int(latest['steps']):,} steps")
    if latest.get("active_calories") is not None:
        parts.append(f"{int(latest['active_calories'])} active cal")
    if latest.get("intensity_minutes") is not None:
        parts.append(f"{int(latest['intensity_minutes'])} intensity min")
    return "Yesterday: " + " · ".join(parts) if parts else None


_GOOD_TRAINING_STATUSES = frozenset({"PRODUCTIVE", "PEAKING"})


def _pretty_status(phrase: str) -> str:
    """Humanize a Garmin feedback phrase: ``UNPRODUCTIVE_5`` -> ``Unproductive``."""
    words = [w for w in phrase.split("_") if w and not w.isdigit()]
    return " ".join(words).capitalize() if words else phrase


def _fitness_line(brief: dict[str, Any], latest: dict[str, Any]) -> str | None:
    parts: list[str] = []
    if latest.get("vo2max_running") is not None:
        parts.append(f"VO2max {round(float(latest['vo2max_running']))}")
    if latest.get("training_readiness") is not None:
        parts.append(f"Garmin readiness {int(latest['training_readiness'])}")
    status = str(latest.get("training_status") or "")
    if status and status.split("_")[0] not in _GOOD_TRAINING_STATUSES:
        parts.append(f"Garmin status: {_pretty_status(status)}")
    fit = brief.get("fitness") or {}
    if fit.get("available") and fit.get("form_tsb") is not None:
        state = fit.get("form_state", "")
        label = f"Form {float(fit['form_tsb']):+.0f}" + (f" ({state})" if state else "")
        parts.append(label)
    return " · ".join(parts) if parts else None


def _weather_line(brief: dict[str, Any]) -> str | None:
    weather = brief.get("weather") or {}
    if not weather.get("available") or weather.get("temp_high_f") is None:
        return None
    parts = [f"High {float(weather['temp_high_f']):.0f}°F"]
    if weather.get("apparent_high_f") is not None:
        parts.append(f"feels {float(weather['apparent_high_f']):.0f}°F")
    if weather.get("dew_point_f") is not None:
        parts.append(f"dew {float(weather['dew_point_f']):.0f}°F")
    line = "Weather: " + " · ".join(parts)
    heat = brief.get("heat") or {}
    if heat.get("available") and heat.get("severity") in ("high", "extreme") and heat.get("advice"):
        line += f" · 🥵 {heat['advice']}"
    return line


def _pace_str(distance_mi: Any, duration_s: Any) -> str | None:
    """Minutes-per-mile pace, e.g. ``9:41/mi``. None when not computable."""
    if not isinstance(distance_mi, (int, float)) or distance_mi <= 0:
        return None
    if not isinstance(duration_s, (int, float)) or duration_s <= 0:
        return None
    sec_per_mi = duration_s / distance_mi
    if sec_per_mi > 30 * 60:  # slower than 30:00/mi — pace is meaningless
        return None
    return f"{int(sec_per_mi // 60)}:{int(sec_per_mi % 60):02d}/mi"


def _last_activity_line(recent: list[dict[str, Any]]) -> str | None:
    if not recent:
        return None
    last = recent[-1]
    label = last.get("name") or last.get("activity_type") or "Activity"
    parts = [f"Last session: {label}"]
    dist = last.get("distance_mi")
    if dist:
        parts.append(f"{dist} mi")
    pace = _pace_str(dist, last.get("duration_s"))
    if pace:
        parts.append(pace)
    aerobic = last.get("aerobic_te")
    if isinstance(aerobic, (int, float)) and aerobic > 0:
        parts.append(f"TE {aerobic:.1f} aerobic")
    return " · ".join(parts)


def _current_state_lines(brief: dict[str, Any], latest: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    r = brief.get("readiness") or {}
    if r.get("score") is not None:
        band = str(r.get("band", "")).lower()
        emoji = _BAND_EMOJI.get(band, "")
        lines.append(f"{emoji} Readiness {r.get('score')}/100 ({band or 'n/a'})".strip())
    for line in (
        _sleep_line(latest),
        _vitals_line(latest),
        _activity_totals_line(latest),
        _fitness_line(brief, latest),
        _weather_line(brief),
    ):
        if line:
            lines.append(line)
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


def _staleness_line(latest: dict[str, Any]) -> str | None:
    """A plain warning when the overnight numbers are not from last night."""
    source = latest.get("overnight_source")
    if source == "yesterday":
        return "⚠ No sync yet this morning — sleep/HRV shown are from yesterday."
    if source == "missing":
        return "⚠ Overnight data is missing — this morning's sync may have failed."
    return None


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

    state = _current_state_lines(brief, latest)
    last = _last_activity_line(recent)
    if last:
        state.append(last)
    if state:
        stale = _staleness_line(latest)
        if stale:
            state.insert(0, stale)
    else:
        state = ["No data yet — run a sync to populate your briefing."]

    dur = f" — {workout.duration_min} min" if workout.duration_min else ""
    wtype = str(workout.workout_type).replace("_", " ")
    wtype = wtype[:1].upper() + wtype[1:]

    sections: list[str] = []
    summary = str(getattr(workout, "summary", "") or "").strip()
    if summary:
        sections.append(summary)
    sections.append("Current State:\n" + "\n".join(state))
    sections.append("Goal:\n" + _pretty_goal(goal, brief))
    insight = str(getattr(workout, "insight", "") or "").strip()
    if insight:
        sections.append("Insights:\n" + insight)
    sections.append(f"Today's Workout:\n{wtype}{dur}\n{workout.instructions}")
    sections.append("Why:\n" + str(workout.why))
    sections.append("Watch out:\n" + str(workout.watch_out))
    watch_next = str(getattr(workout, "watch_tomorrow", "") or "").strip()
    if watch_next:
        sections.append("Watch tomorrow:\n" + watch_next)
    confidence = str(getattr(workout, "confidence", "") or "").strip()
    if confidence:
        sections.append(f"Confidence: {confidence}")
    return title, "\n\n".join(sections)


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
