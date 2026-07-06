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

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

# Import all model modules so their tables register on Base.metadata before
# create_all runs (chat models live in a separate module from the core ones).
from app.db.models import chat as _chat_models  # noqa: F401
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
        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


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
