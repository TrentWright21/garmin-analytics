"""Infra tests: the rate limiter and the SQLite backup job."""

from __future__ import annotations

from pathlib import Path

import pytest

import app.db.engine as db
from app.config import get_settings
from app.db.backup import backup_database
from app.ratelimit import RateLimiter


def test_rate_limiter_fixed_window() -> None:
    rl = RateLimiter(max_calls=2, window_s=10.0)
    assert rl.retry_after("k", now=0.0) is None  # 1st
    assert rl.retry_after("k", now=1.0) is None  # 2nd
    blocked = rl.retry_after("k", now=2.0)  # 3rd over budget
    assert blocked is not None and 0 < blocked <= 10
    # Once the window has passed, the bucket refills.
    assert rl.retry_after("k", now=12.0) is None


def test_rate_limiter_keys_are_independent() -> None:
    rl = RateLimiter(max_calls=1, window_s=10.0)
    assert rl.retry_after("a", now=0.0) is None
    assert rl.retry_after("b", now=0.0) is None  # different bucket, still allowed
    assert rl.retry_after("a", now=0.0) is not None  # 'a' now over budget


def test_backup_creates_snapshot_and_rotates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GA_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    get_settings.cache_clear()
    db.reset_engine_for_tests()
    db.get_engine()  # create the DB file + tables

    backups = tmp_path / "backups"
    backups.mkdir()
    for i in range(5):  # pre-seed older snapshots
        (backups / f"test-{i:04d}.db").write_bytes(b"x")

    dest = backup_database(keep=2)
    assert dest is not None and dest.exists()
    assert len(list(backups.glob("test-*.db"))) == 2  # rotated down to keep=2

    get_settings.cache_clear()
    db.reset_engine_for_tests()


def test_backup_noop_without_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GA_DATABASE_URL", f"sqlite:///{tmp_path}/missing.db")
    get_settings.cache_clear()
    db.reset_engine_for_tests()
    assert backup_database() is None  # nothing to back up yet
    get_settings.cache_clear()
    db.reset_engine_for_tests()
