"""Tier-2/3 AI metric insight: cached, cost-capped, explicit-request only.

This sits *on top of* the local (Tier-1) `insight_engine` — which always works
with no API. Here the flow is deliberately stingy:

* A generated summary is cached by a **data fingerprint**; the same request
  never pays twice, and the cache self-invalidates when the data changes.
* Generation happens **only on an explicit request** (the "Generate deeper
  analysis" button -> POST), never on a page load (GET only reads cache).
* Every request is gated by ``AiInsightConfig``: enabled flag, an API key, a
  minimum-history requirement, and a hard per-day call cap. Every request is
  logged for spend auditing.
* The model is cheap (Haiku by default), the output-token ceiling is strict,
  and the prompt sends a compact **summary** — never raw daily records.

If anything is off/thin/over-cap/erroring, this returns ``available: False``
with a reason and the UI falls back to the local insights.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from app.config import AiInsightConfig, Settings
from app.db.engine import session_scope
from app.db.models.insights import AiInsightCache, AiUsageLog
from app.logging import get_logger

log = get_logger(__name__)

_INSIGHT_VERSION = "v1"  # bump to invalidate every cached insight at once

_SYSTEM = (
    "You are a concise sports-analytics assistant explaining ONE of the athlete's "
    "own metrics. Use only the numbers provided. Write 2-4 short sentences in plain "
    "language: what the current value and recent trend mean for training and recovery, "
    "and one practical takeaway. Reference their own baseline, not population norms. "
    "Do NOT give medical diagnoses or claim certainty; this is not medical advice."
)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _fingerprint(detail: dict[str, Any]) -> str:
    stats = detail.get("stats") or {}
    sig = "|".join(
        str(x)
        for x in (
            detail.get("key"),
            detail.get("range_days"),
            detail.get("as_of"),
            detail.get("current"),
            stats.get("avg"),
            _INSIGHT_VERSION,
        )
    )
    return hashlib.sha256(sig.encode()).hexdigest()[:32]


def _data_points(detail: dict[str, Any]) -> int:
    return sum(1 for p in (detail.get("series") or []) if p.get("value") is not None)


def _has_key(settings: Settings, client_factory: Callable[..., Any] | None) -> bool:
    return settings.anthropic_api_key is not None or client_factory is not None


def ai_insight(
    settings: Settings,
    cfg: AiInsightConfig,
    detail: dict[str, Any],
    *,
    generate: bool,
    client_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Return an AI insight for a metric-detail payload.

    ``generate=False`` (GET) only reads a fresh cache — never spends. ``True``
    (POST, the button) may generate, subject to every cost gate.
    """
    key = str(detail.get("key"))
    range_days = int(detail.get("range_days") or 0)
    enabled = cfg.enabled and _has_key(settings, client_factory)
    enough = bool(detail.get("available")) and _data_points(detail) >= cfg.min_days
    can_generate = enabled and enough and cfg.max_calls_per_day > 0

    base = {"enabled": enabled, "can_generate": can_generate}

    # A fresh cache is served to both GET and POST — no double-paying.
    cached = _read_cache(cfg, key, range_days, _fingerprint(detail))
    if cached is not None:
        _log(key, range_days, "cached", cached.model, None, None, None)
        return {
            **base,
            "available": True,
            "source": "cached",
            "insight": cached.insight,
            "model": cached.model,
            "generated_at": cached.created_at.isoformat(),
        }

    if not generate:
        # Page load: never generate. Say whether the button is worth showing.
        reason = None if can_generate else _why_not(enabled, enough, cfg)
        return {**base, "available": False, "source": None, "reason": reason}

    # Explicit button press -> the only path that can spend.
    if not enabled or not enough or cfg.max_calls_per_day <= 0:
        reason = _why_not(enabled, enough, cfg)
        _log(key, range_days, "refused", None, None, None, reason)
        return {**base, "available": False, "source": None, "reason": reason}

    if _generated_today() >= cfg.max_calls_per_day:
        _log(key, range_days, "refused", None, None, None, "daily_limit")
        return {**base, "available": False, "source": None, "reason": "daily_limit"}

    try:
        text, in_tok, out_tok = _call_model(settings, cfg, detail, client_factory)
    except Exception as exc:  # any API/parse failure -> local still works
        log.warning("ai_insight.failed", metric=key, err=type(exc).__name__)
        _log(key, range_days, "error", cfg.model, None, None, type(exc).__name__)
        return {**base, "available": False, "source": None, "reason": "error"}

    created = _write_cache(cfg, key, range_days, _fingerprint(detail), text)
    _log(key, range_days, "generated", cfg.model, in_tok, out_tok, None)
    return {
        **base,
        "available": True,
        "source": "generated",
        "insight": text,
        "model": cfg.model,
        "generated_at": created.isoformat(),
    }


def _why_not(enabled: bool, enough: bool, cfg: AiInsightConfig) -> str:
    if not enabled:
        return "disabled"
    if not enough:
        return "thin_history"
    if cfg.max_calls_per_day <= 0:
        return "disabled"
    return "unavailable"


# -- model call ---------------------------------------------------------------


def _compact_payload(detail: dict[str, Any]) -> dict[str, Any]:
    """A small, summary-only payload — never the raw daily series."""
    return {
        "metric": detail.get("label"),
        "unit": detail.get("unit"),
        "direction": detail.get("direction"),
        "range_days": detail.get("range_days"),
        "current": detail.get("current"),
        "status": detail.get("status"),
        "change_pct_vs_prev_7d": (detail.get("delta") or {}).get("pct"),
        "stats": detail.get("stats"),
        "baseline": detail.get("baseline"),
        "local_insights": detail.get("insights"),
        "relationships": [r.get("interpretation") for r in (detail.get("relationships") or [])],
    }


def _call_model(
    settings: Settings,
    cfg: AiInsightConfig,
    detail: dict[str, Any],
    client_factory: Callable[..., Any] | None,
) -> tuple[str, int | None, int | None]:
    """One cheap, bounded Claude call -> (text, input_tokens, output_tokens)."""
    import json

    import anthropic

    factory: Callable[..., Any] = client_factory or anthropic.Anthropic
    api_key = (
        settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else "test"
    )
    client: Any = factory(api_key=api_key)
    msg: Any = client.messages.create(
        model=cfg.model,
        max_tokens=cfg.max_output_tokens,
        system=_SYSTEM,
        messages=[{"role": "user", "content": json.dumps(_compact_payload(detail))}],
    )
    text = _extract_text(msg).strip()
    if not text:
        raise ValueError("empty model response")
    usage = getattr(msg, "usage", None)
    return text, getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None)


def _extract_text(msg: Any) -> str:
    blocks = getattr(msg, "content", None)
    if isinstance(blocks, list):
        return "".join(getattr(b, "text", "") for b in blocks)
    return str(blocks or "")


# -- persistence --------------------------------------------------------------


def _read_cache(
    cfg: AiInsightConfig, key: str, range_days: int, fingerprint: str
) -> AiInsightCache | None:
    cutoff = _now().timestamp() - cfg.cache_hours * 3600
    with session_scope() as s:
        row = s.execute(
            select(AiInsightCache).where(
                AiInsightCache.metric_key == key,
                AiInsightCache.range_days == range_days,
                AiInsightCache.fingerprint == fingerprint,
            )
        ).scalar_one_or_none()
        if row is None or row.created_at.timestamp() < cutoff:
            return None
        s.expunge(row)
        return row


def _write_cache(
    cfg: AiInsightConfig, key: str, range_days: int, fingerprint: str, text: str
) -> datetime:
    created = _now()
    with session_scope() as s:
        # Drop any stale row for this (key, range) so the unique constraint and
        # the "latest wins" reading both stay simple.
        for old in s.execute(
            select(AiInsightCache).where(
                AiInsightCache.metric_key == key, AiInsightCache.range_days == range_days
            )
        ).scalars():
            s.delete(old)
        s.add(
            AiInsightCache(
                metric_key=key,
                range_days=range_days,
                fingerprint=fingerprint,
                model=cfg.model,
                insight=text,
                created_at=created,
            )
        )
    return created


def _generated_today() -> int:
    day_start = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    with session_scope() as s:
        n = s.execute(
            select(func.count())
            .select_from(AiUsageLog)
            .where(AiUsageLog.source == "generated", AiUsageLog.created_at >= day_start)
        ).scalar_one()
    return int(n or 0)


def _log(
    key: str,
    range_days: int,
    source: str,
    model: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    error: str | None,
) -> None:
    with session_scope() as s:
        s.add(
            AiUsageLog(
                metric_key=key,
                range_days=range_days,
                source=source,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                error=error,
                created_at=_now(),
            )
        )
