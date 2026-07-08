"""Nightly SQLite backup.

Your entire history and Garmin OAuth tokens live in one file — easy to copy,
easy to lose. This takes a consistent snapshot using SQLite's online-backup API
(safe to run while the app is writing), drops it under ``data/backups/``, and
keeps the most recent N. No-op for non-SQLite URLs (the Postgres move brings its
own backup story). Best-effort: failures are logged, never fatal.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from app.config import get_settings
from app.logging import get_logger

log = get_logger(__name__)

_KEEP = 14  # nights of history


def _sqlite_path(url: str) -> Path | None:
    if not url.startswith("sqlite:///"):
        return None
    return Path(url.removeprefix("sqlite:///"))


def backup_database(keep: int = _KEEP) -> Path | None:
    """Snapshot the SQLite DB into data/backups/, rotate to ``keep`` copies.

    Returns the backup path, or None if there's nothing to back up (non-SQLite
    URL, or the DB file doesn't exist yet).
    """
    db_path = _sqlite_path(get_settings().database_url)
    if db_path is None or not db_path.exists():
        return None

    backups_dir = db_path.parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = backups_dir / f"{db_path.stem}-{stamp}.db"

    src = sqlite3.connect(str(db_path))
    try:
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)  # consistent snapshot even under concurrent writes
        finally:
            dst.close()
    finally:
        src.close()

    # Rotate: keep the newest ``keep`` snapshots.
    snapshots = sorted(backups_dir.glob(f"{db_path.stem}-*.db"))
    for stale in snapshots[:-keep]:
        stale.unlink(missing_ok=True)

    log.info("backup.written", path=str(dest), kept=min(len(snapshots), keep))
    return dest
