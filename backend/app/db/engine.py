"""Engine + session factory, and the raw-layer repository.

SQLite now; swapping to PostgreSQL later is just a GA_DATABASE_URL change —
nothing in here is SQLite-specific.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

# Import all model modules so their tables register on Base.metadata before
# create_all runs (chat + weather models live in separate modules from core).
from app.db.models import chat as _chat_models  # noqa: F401
from app.db.models import weather as _weather_models  # noqa: F401
from app.db.models.core import Base, RawApiData

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine, _session_factory
    if _engine is None:
        url = get_settings().database_url
        if url.startswith("sqlite:///"):
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(url)
        Base.metadata.create_all(_engine)  # Alembic arrives with the Postgres move
        _add_missing_columns(_engine)
        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def _add_missing_columns(engine: Engine) -> None:
    """Dumb, idempotent forward migration: ADD COLUMN for model columns the DB
    lacks. ``create_all`` only creates missing *tables*, so additive schema
    changes (e.g. Phase 1b's new DailyMetrics/Activity columns) need this until
    Alembic arrives with the Postgres move. All model columns added this way
    must be nullable; anything fancier (renames, drops, types) waits for Alembic.
    """
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                col_type = column.type.compile(engine.dialect)
                ddl = f'ALTER TABLE {table.name} ADD COLUMN "{column.name}" {col_type}'
                conn.execute(text(ddl))


@contextmanager
def session_scope() -> Iterator[Session]:
    get_engine()
    assert _session_factory is not None
    session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine_for_tests() -> None:
    global _engine, _session_factory
    _engine = None
    _session_factory = None


# -- raw layer -------------------------------------------------------------


def payload_hash(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def store_raw(session: Session, endpoint: str, metric_date: date | None, payload: Any) -> bool:
    """Insert a raw payload unless an identical one already exists.

    Returns True if a new row was written. Never updates, never deletes.
    """
    h = payload_hash(payload)
    exists = session.execute(
        select(RawApiData.id).where(
            RawApiData.endpoint == endpoint,
            RawApiData.metric_date == metric_date,
            RawApiData.payload_hash == h,
        )
    ).first()
    if exists:
        return False
    session.add(
        RawApiData(
            endpoint=endpoint,
            metric_date=metric_date,
            fetched_at=datetime.now(UTC),
            payload_hash=h,
            payload_json=json.dumps(payload, default=str),
        )
    )
    return True


def latest_raw(session: Session, endpoint: str, metric_date: date) -> Any | None:
    """Most recently fetched payload for one endpoint+day (Garmin revisions win)."""
    row = session.execute(
        select(RawApiData)
        .where(RawApiData.endpoint == endpoint, RawApiData.metric_date == metric_date)
        # id is the tie-breaker: when two revisions land in the same microsecond
        # (fetched_at ties), the later-inserted row still wins deterministically.
        .order_by(RawApiData.fetched_at.desc(), RawApiData.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    return json.loads(row.payload_json) if row else None


def latest_raw_any(session: Session, endpoint: str) -> Any | None:
    """Most recently fetched payload for an endpoint, regardless of date.

    Weather payloads each span a whole date range (one archive/forecast call
    covers many days), so they are read by "newest for this endpoint" rather
    than per-day like the Garmin endpoints.
    """
    row = session.execute(
        select(RawApiData)
        .where(RawApiData.endpoint == endpoint)
        .order_by(RawApiData.fetched_at.desc(), RawApiData.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    return json.loads(row.payload_json) if row else None
