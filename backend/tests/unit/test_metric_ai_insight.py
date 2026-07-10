"""Tier-2/3 AI metric insight: caching + cost caps, with a mocked client.

No real network calls: a recorder fake counts model invocations so the cache and
the daily cap can be asserted to actually prevent spend.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import app.db.engine as db
from app.ai import metric_insight as mai
from app.config import AiInsightConfig


@pytest.fixture(autouse=True)
def temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GA_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    from app.config import get_settings

    get_settings.cache_clear()
    db.reset_engine_for_tests()
    yield
    get_settings.cache_clear()
    db.reset_engine_for_tests()


class Recorder:
    """A fake anthropic client factory that counts .messages.create calls."""

    def __init__(self, text: str = "Your HRV is steady versus baseline.", raise_it: bool = False):
        self.text = text
        self.raise_it = raise_it
        self.calls = 0

    def factory(self, api_key: str | None = None):
        rec = self

        class _Messages:
            def create(self, **_: object):
                rec.calls += 1
                if rec.raise_it:
                    raise RuntimeError("boom")
                return SimpleNamespace(
                    content=[SimpleNamespace(text=rec.text)],
                    usage=SimpleNamespace(input_tokens=100, output_tokens=50),
                )

        return SimpleNamespace(messages=_Messages())


_SETTINGS = SimpleNamespace(anthropic_api_key=None)  # key comes via client_factory


def detail(points: int = 30, as_of: str = "2026-07-09", current: float = 60.0) -> dict:
    series = [{"day": f"2026-06-{i + 1:02d}", "value": 55.0 + i} for i in range(points)]
    return {
        "available": True,
        "key": "hrv_last_night_avg",
        "label": "HRV (overnight)",
        "unit": "ms",
        "direction": "higher-better",
        "range_days": 90,
        "as_of": as_of,
        "current": current,
        "status": "good",
        "delta": {"pct": -2.0, "vs": "previous 7 days"},
        "stats": {"avg": 58.0, "min": 50.0, "max": 70.0, "trend": "steady"},
        "baseline": {"avg30": 58.0, "z": 0.1, "normal": {"low": 50.0, "high": 66.0}},
        "series": series,
        "insights": ["Your 7-day average is trending downward."],
        "relationships": [
            {"key": "sleep_score", "label": "Sleep Score", "r": 0.4, "n": 30, "interpretation": "x"}
        ],
    }


def _cfg(**kw: object) -> AiInsightConfig:
    base = {"enabled": True, "min_days": 14, "max_calls_per_day": 5, "cache_hours": 18}
    base.update(kw)
    return AiInsightConfig(**base)  # type: ignore[arg-type]


def test_disabled_by_default_never_calls() -> None:
    rec = Recorder()
    out = mai.ai_insight(
        _SETTINGS, AiInsightConfig(), detail(), generate=True, client_factory=rec.factory
    )
    assert out["available"] is False and out["reason"] == "disabled"
    assert rec.calls == 0


def test_thin_history_refused() -> None:
    rec = Recorder()
    out = mai.ai_insight(
        _SETTINGS, _cfg(), detail(points=5), generate=True, client_factory=rec.factory
    )
    assert out["available"] is False and out["reason"] == "thin_history"
    assert rec.calls == 0


def test_generate_then_serve_from_cache() -> None:
    rec = Recorder()
    first = mai.ai_insight(_SETTINGS, _cfg(), detail(), generate=True, client_factory=rec.factory)
    assert first["available"] is True and first["source"] == "generated"
    assert first["insight"].startswith("Your HRV")
    assert rec.calls == 1

    # Same data -> served from cache, NO second call.
    again = mai.ai_insight(_SETTINGS, _cfg(), detail(), generate=True, client_factory=rec.factory)
    assert again["source"] == "cached" and rec.calls == 1

    # A GET (generate=False) also reads the cache without spending.
    got = mai.ai_insight(_SETTINGS, _cfg(), detail(), generate=False, client_factory=rec.factory)
    assert got["available"] is True and got["source"] == "cached" and rec.calls == 1


def test_get_without_cache_offers_button_but_does_not_generate() -> None:
    rec = Recorder()
    out = mai.ai_insight(_SETTINGS, _cfg(), detail(), generate=False, client_factory=rec.factory)
    assert out["available"] is False and out["can_generate"] is True and rec.calls == 0


def test_daily_cap_blocks_further_generation() -> None:
    rec = Recorder()
    cfg = _cfg(max_calls_per_day=1)
    mai.ai_insight(
        _SETTINGS, cfg, detail(as_of="2026-07-09"), generate=True, client_factory=rec.factory
    )
    assert rec.calls == 1
    # Different data (new fingerprint) so the cache misses -> the cap must bite.
    blocked = mai.ai_insight(
        _SETTINGS,
        cfg,
        detail(as_of="2026-07-10", current=61.0),
        generate=True,
        client_factory=rec.factory,
    )
    assert blocked["available"] is False and blocked["reason"] == "daily_limit"
    assert rec.calls == 1  # no second spend


def test_model_error_falls_back_and_logs() -> None:
    rec = Recorder(raise_it=True)
    out = mai.ai_insight(_SETTINGS, _cfg(), detail(), generate=True, client_factory=rec.factory)
    assert out["available"] is False and out["reason"] == "error"
    # An error row was logged for auditing.
    from sqlalchemy import select

    from app.db.models.insights import AiUsageLog

    with db.session_scope() as s:
        sources = [r.source for r in s.execute(select(AiUsageLog)).scalars()]
    assert "error" in sources
