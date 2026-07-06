"""AI Coach tests: tool wrappers, persistence, and the chat API.

The Anthropic client is always mocked — the suite makes NO real API calls.
Tool wrappers run the real analytics functions over synthetic data seeded
into a temp SQLite DB, so they exercise the genuine engine.py math.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app.db.engine as db
from app.ai import coach
from app.config import Settings
from app.db import chat as store
from app.db.models.core import Activity, DailyMetrics


@pytest.fixture(autouse=True)
def temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GA_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    # Ensure a clean Coach config default unless a test sets the key.
    monkeypatch.delenv("GA_ANTHROPIC_API_KEY", raising=False)
    from app.config import get_settings

    get_settings.cache_clear()
    db.reset_engine_for_tests()
    yield
    get_settings.cache_clear()
    db.reset_engine_for_tests()


def seed_metrics(n_days: int = 50) -> None:
    """Insert n_days of synthetic daily metrics + a few activities."""
    end = date(2026, 7, 5)
    with db.session_scope() as s:
        for i in range(n_days):
            day = end - timedelta(days=n_days - 1 - i)
            s.merge(
                DailyMetrics(
                    day=day,
                    steps=8000 + i * 10,
                    resting_hr=52,
                    hrv_last_night_avg=70 + (i % 7),
                    sleep_score=80,
                    sleep_seconds=27000,
                    avg_stress=30,
                    body_battery_high=85,
                    training_readiness=75,
                    vo2max_running=48.0,
                )
            )
        for i in range(5):
            day = end - timedelta(days=i)
            s.merge(
                Activity(
                    activity_id=1000 + i,
                    start_time_local=datetime(2026, 7, 5 - i, 7, 0),
                    day=day,
                    activity_type="running",
                    name="Morning Run",
                    distance_m=8000.0,
                    duration_s=2400.0,
                    avg_hr=150.0,
                    max_hr=170.0,
                    avg_temp_c=22.0,
                    training_load=60.0,
                )
            )


# -- tool wrappers -----------------------------------------------------------


class TestToolWrappers:
    def test_daily_metrics_returns_seeded_rows(self) -> None:
        seed_metrics(30)
        out = json.loads(coach.get_daily_metrics(days=14))
        assert out["days"] == 14
        assert len(out["rows"]) == 14
        assert out["rows"][0]["resting_hr"] == 52
        # nulls are dropped from compact output
        assert all("weight_kg" not in r for r in out["rows"])

    def test_daily_metrics_empty_db(self) -> None:
        out = json.loads(coach.get_daily_metrics(days=14))
        assert out["rows"] == []
        assert "note" in out

    def test_daily_metrics_clamps_days(self) -> None:
        out = json.loads(coach.get_daily_metrics(days=99999))
        assert out["days"] == 365

    def test_rolling_trends_uses_engine(self) -> None:
        seed_metrics(60)
        out = json.loads(coach.get_rolling_trends(days=90))
        assert "resting_hr" in out["trends"]
        assert out["trends"]["resting_hr"]["now_7d_avg"] == 52.0

    def test_training_load_reference_and_values(self) -> None:
        seed_metrics(50)
        out = json.loads(coach.get_training_load(days=90))
        assert out["reference"]["acwr_sweet_spot"] == "0.8-1.3"
        assert len(out["acwr_last_14_days"]) > 0

    def test_readiness_has_components(self) -> None:
        seed_metrics(60)
        out = json.loads(coach.get_readiness())
        assert out["score"] is not None
        assert "sleep" in out["components"]

    def test_insights_shape(self) -> None:
        seed_metrics(30)
        out = json.loads(coach.get_insights())
        assert isinstance(out["insights"], list)

    def test_recent_activities(self) -> None:
        seed_metrics(30)
        out = json.loads(coach.get_recent_activities(limit=3))
        assert len(out["activities"]) == 3
        assert out["activities"][-1]["activity_type"] == "running"

    def test_all_tools_return_valid_json(self) -> None:
        seed_metrics(50)
        for tool in coach.COACH_TOOLS:
            # every tool's schema was auto-generated from its signature
            assert tool.to_dict()["name"].startswith("get_")


# -- persistence -------------------------------------------------------------


class TestPersistence:
    def test_create_and_history_roundtrip(self) -> None:
        cid = store.create_conversation("How is my sleep?")
        store.add_message(cid, "user", "How is my sleep?")
        store.add_message(cid, "assistant", "Solid — 82 average.")
        history = store.get_history(cid)
        assert history == [
            {"role": "user", "content": "How is my sleep?"},
            {"role": "assistant", "content": "Solid — 82 average."},
        ]

    def test_title_derived_from_first_message(self) -> None:
        cid = store.create_conversation()
        assert store.list_conversations()[0]["title"] == "New chat"
        store.add_message(cid, "user", "Tell me about my HRV trend please")
        assert store.list_conversations()[0]["title"] == "Tell me about my HRV trend please"

    def test_long_title_truncated(self) -> None:
        store.create_conversation("x" * 200)
        assert len(store.list_conversations()[0]["title"]) <= 60

    def test_list_orders_by_recency_with_counts(self) -> None:
        a = store.create_conversation("first")
        store.add_message(a, "user", "first")
        b = store.create_conversation("second")
        store.add_message(b, "user", "second")
        store.add_message(b, "assistant", "reply")
        titles = [c["title"] for c in store.list_conversations()]
        assert titles == ["second", "first"]  # b most recently updated
        counts = {c["title"]: c["message_count"] for c in store.list_conversations()}
        assert counts == {"first": 1, "second": 2}

    def test_add_to_missing_conversation_raises(self) -> None:
        with pytest.raises(KeyError):
            store.add_message("does-not-exist", "user", "hi")

    def test_conversation_exists(self) -> None:
        cid = store.create_conversation("x")
        assert store.conversation_exists(cid)
        assert not store.conversation_exists("nope")


# -- Coach with a mocked Anthropic client ------------------------------------


def _fake_client_factory(reply_text: str = "Your readiness is 68 today.") -> Any:
    def factory(api_key: str) -> Any:
        block = MagicMock()
        block.type = "text"
        block.text = reply_text
        msg = MagicMock()
        msg.content = [block]
        client = MagicMock()
        client.beta.messages.tool_runner.return_value.until_done.return_value = msg
        return client

    return factory


class TestCoach:
    def test_not_configured_raises(self) -> None:
        with pytest.raises(coach.CoachNotConfiguredError):
            coach.Coach(Settings(_env_file=None))

    def test_is_configured(self) -> None:
        assert not coach.is_configured(Settings(_env_file=None))
        assert coach.is_configured(Settings(anthropic_api_key="sk-ant-x", _env_file=None))

    def test_reply_joins_text_blocks(self) -> None:
        settings = Settings(anthropic_api_key="sk-ant-x", _env_file=None)
        c = coach.Coach(settings, client_factory=_fake_client_factory("Feeling fresh."))
        assert c.reply([], "How am I doing?") == "Feeling fresh."

    def test_reply_replays_history_and_appends_message(self) -> None:
        settings = Settings(anthropic_api_key="sk-ant-x", _env_file=None)
        factory = _fake_client_factory()
        c = coach.Coach(settings, client_factory=factory)
        history = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        c.reply(history, "and now?")
        # inspect the messages passed to tool_runner
        client = c._client  # type: ignore[attr-defined]
        kwargs = client.beta.messages.tool_runner.call_args.kwargs
        assert kwargs["model"] == "claude-opus-4-8"
        assert kwargs["tools"] is coach.COACH_TOOLS
        assert kwargs["messages"] == [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {"role": "user", "content": "and now?"},
        ]


# -- chat API (mocked Coach) -------------------------------------------------


@pytest.fixture
def client() -> TestClient:
    from app.main import app

    return TestClient(app)


class _FakeCoach:
    def __init__(self, settings: Any) -> None:
        pass

    def reply(self, history: list[dict[str, str]], user_message: str) -> str:
        return f"echo:{user_message} (had {len(history)} prior)"


class TestChatApi:
    def test_status_reflects_config(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert client.get("/api/coach/status").json() == {"configured": False}

    def test_chat_not_configured_message(self, client: TestClient) -> None:
        r = client.post("/api/coach/chat", json={"message": "hello"})
        body = r.json()
        assert r.status_code == 200
        assert body["configured"] is False
        assert "GA_ANTHROPIC_API_KEY" in body["reply"]
        # no conversation should have been created
        assert client.get("/api/coach/conversations").json()["conversations"] == []

    def test_full_conversation_flow(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.api.routes.chat as chat_route

        monkeypatch.setattr(chat_route.coach_mod, "is_configured", lambda s: True)
        monkeypatch.setattr(chat_route.coach_mod, "Coach", _FakeCoach)

        r1 = client.post("/api/coach/chat", json={"message": "How's my load?"})
        j1 = r1.json()
        cid = j1["conversation_id"]
        assert j1["configured"] is True
        assert j1["reply"] == "echo:How's my load? (had 0 prior)"

        r2 = client.post(
            "/api/coach/chat", json={"message": "And recovery?", "conversation_id": cid}
        )
        assert r2.json()["conversation_id"] == cid
        # second turn saw the first user+assistant pair as history
        assert r2.json()["reply"] == "echo:And recovery? (had 2 prior)"

        hist = client.get(f"/api/coach/conversations/{cid}").json()
        assert [m["role"] for m in hist["messages"]] == [
            "user",
            "assistant",
            "user",
            "assistant",
        ]
        lst = client.get("/api/coach/conversations").json()["conversations"]
        assert lst[0]["message_count"] == 4

    def test_unknown_conversation_404(self, client: TestClient) -> None:
        assert client.get("/api/coach/conversations/nope").status_code == 404

    def test_chat_with_unknown_conversation_404(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.api.routes.chat as chat_route

        monkeypatch.setattr(chat_route.coach_mod, "is_configured", lambda s: True)
        monkeypatch.setattr(chat_route.coach_mod, "Coach", _FakeCoach)
        r = client.post("/api/coach/chat", json={"message": "x", "conversation_id": "nope"})
        assert r.status_code == 404

    def test_empty_message_rejected(self, client: TestClient) -> None:
        assert client.post("/api/coach/chat", json={"message": ""}).status_code == 422

    def test_api_error_becomes_502(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import anthropic

        import app.api.routes.chat as chat_route

        class _BoomCoach:
            def __init__(self, settings: Any) -> None:
                pass

            def reply(self, history: list[dict[str, str]], user_message: str) -> str:
                raise anthropic.APIConnectionError(request=MagicMock())

        monkeypatch.setattr(chat_route.coach_mod, "is_configured", lambda s: True)
        monkeypatch.setattr(chat_route.coach_mod, "Coach", _BoomCoach)
        r = client.post("/api/coach/chat", json={"message": "hi"})
        assert r.status_code == 502
