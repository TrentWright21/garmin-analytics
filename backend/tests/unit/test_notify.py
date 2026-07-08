"""Notifier tests: message formatting, Telegram transport, orchestration.

No real network: httpx.post is monkeypatched, and the send orchestration uses a
recording fake notifier. format_brief is pure and tested on a synthetic brief.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import app.db.engine as db
from app.config import AppConfig, Settings, get_settings
from app.notify import build_notifier, is_configured
from app.notify.message import format_brief, send_morning_briefing
from app.notify.telegram import TelegramNotifier

BRIEF: dict[str, Any] = {
    "date": "2026-07-07",
    "readiness": {"score": 82, "band": "green", "recommendation": "Train as planned."},
    "risk": {"risk_band": "yellow", "flag_count": 1, "flags": [{"title": "Load spike"}]},
    "fitness": {"available": True, "form_tsb": -5.0, "form_state": "fresh"},
    "recovery": {"available": True, "pct_recovered": 90, "recovered": True},
    "weather": {"available": True, "temp_high_f": 92.0, "dew_point_f": 74.0},
    "heat": {"available": True, "severity": "high", "advice": "Run early + hydrate"},
    "event": {"available": True, "name": "Whitney", "days_until": 26},
}


def test_format_brief_includes_key_facts() -> None:
    title, text = format_brief(BRIEF)
    assert title.endswith("2026-07-07")
    assert "82" in text and "green" in text
    assert "Load spike" in text  # risk surfaced
    assert "Whitney" in text and "26" in text  # event countdown
    assert "Run early" in text  # heat advice


def test_format_brief_empty_is_graceful() -> None:
    _title, text = format_brief({"date": "2026-07-07"})
    assert "No data" in text


class _FakeResp:
    def __init__(self, status: int, payload: dict[str, Any] | None = None) -> None:
        self.status_code = status
        self._payload = payload or {}
        self.text = ""

    def json(self) -> dict[str, Any]:
        return self._payload


def test_telegram_send_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: dict[str, Any] = {}

    def fake_post(url: str, json: dict[str, Any], timeout: float) -> _FakeResp:
        sent["url"] = url
        sent["json"] = json
        return _FakeResp(200, {"ok": True})

    monkeypatch.setattr("app.notify.telegram.httpx.post", fake_post)
    TelegramNotifier("BOTTOKEN", "42").send("Title", "Body")
    assert "/botBOTTOKEN/sendMessage" in sent["url"]
    assert sent["json"]["chat_id"] == "42"
    assert "Title" in sent["json"]["text"] and "Body" in sent["json"]["text"]


def test_telegram_send_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.notify import NotifyError

    monkeypatch.setattr(
        "app.notify.telegram.httpx.post",
        lambda *a, **k: _FakeResp(400, {"description": "chat not found"}),
    )
    with pytest.raises(NotifyError, match="chat not found"):
        TelegramNotifier("t", "c").send("x", "y")


def test_build_notifier_requires_both_secrets() -> None:
    assert not is_configured(Settings(telegram_bot_token="t"))  # type: ignore[arg-type]
    assert build_notifier(Settings(telegram_bot_token="t")) is None  # type: ignore[arg-type]
    full = Settings(telegram_bot_token="t", telegram_chat_id="c")  # type: ignore[arg-type]
    assert is_configured(full)
    assert isinstance(build_notifier(full), TelegramNotifier)


def test_send_morning_briefing_unconfigured_returns_false() -> None:
    assert send_morning_briefing(Settings(), AppConfig()) is False


def test_send_morning_briefing_delivers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GA_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    get_settings.cache_clear()
    db.reset_engine_for_tests()

    delivered: list[tuple[str, str]] = []

    class Recorder:
        def send(self, title: str, text: str) -> None:
            delivered.append((title, text))

    monkeypatch.setattr("app.notify.message.build_notifier", lambda _s: Recorder())
    ok = send_morning_briefing(Settings(), AppConfig())
    assert ok is True
    assert len(delivered) == 1

    get_settings.cache_clear()
    db.reset_engine_for_tests()
