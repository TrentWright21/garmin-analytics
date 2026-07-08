"""Compose and send the morning message from the existing daily brief.

``format_brief`` is a pure function (dict in -> title + text out) so it is
unit-testable without the network. ``send_morning_briefing`` is the scheduled
job's entry point: build the brief, format it, optionally have Claude polish the
wording, and push it. Every step degrades gracefully — a missing section is
skipped, a polish failure falls back to the plain text, and an unconfigured
channel simply no-ops.
"""

from __future__ import annotations

from typing import Any

from app.config import AppConfig, Settings
from app.logging import get_logger
from app.notify import NotifyError, build_notifier

log = get_logger(__name__)

_POLISH_MODEL = "claude-opus-4-8"
_BAND_EMOJI = {"green": "🟢", "yellow": "🟡", "red": "🔴"}


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


def send_morning_briefing(settings: Settings, cfg: AppConfig) -> bool:
    """Build and send today's brief. Returns True if a message was delivered."""
    notifier = build_notifier(settings)
    if notifier is None:
        log.info("notify.skipped", reason="channel_not_configured")
        return False

    # Imported here to avoid a circular import (briefing route imports config).
    from app.api.routes.briefing import build_briefing

    brief = build_briefing()
    title, text = format_brief(brief)
    if cfg.notify.ai_polish:
        text = polish_message(settings, text)

    try:
        notifier.send(title, text)
    except NotifyError as exc:
        log.warning("notify.send_failed", err=str(exc))
        return False
    return True
