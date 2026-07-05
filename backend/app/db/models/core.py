"""Database models.

Two layers:

* ``raw_api_data`` — append-only. Every Garmin response is stored verbatim
  with a content hash. Re-syncing identical data is a no-op; revised data
  (Garmin often revises sleep/HRV next day) inserts a NEW row. Rows are
  never updated or deleted. This is the "never overwrite" guarantee.
* ``daily_metrics`` / ``activities`` — normalized, rebuilt from raw at any
  time. These are what analytics read.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RawApiData(Base):
    __tablename__ = "raw_api_data"
    __table_args__ = (
        UniqueConstraint("endpoint", "metric_date", "payload_hash", name="uq_raw_dedupe"),
        Index("ix_raw_endpoint_date", "endpoint", "metric_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    endpoint: Mapped[str] = mapped_column(String(64))
    metric_date: Mapped[date | None] = mapped_column(Date)  # None for snapshots
    fetched_at: Mapped[datetime] = mapped_column(DateTime)
    payload_hash: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[str] = mapped_column(Text)


class DailyMetrics(Base):
    """One wide row per calendar day. Nullable everywhere: watches miss days."""

    __tablename__ = "daily_metrics"

    day: Mapped[date] = mapped_column(Date, primary_key=True)

    steps: Mapped[int | None] = mapped_column(Integer)
    total_calories: Mapped[float | None] = mapped_column(Float)
    active_calories: Mapped[float | None] = mapped_column(Float)
    floors_up: Mapped[float | None] = mapped_column(Float)
    intensity_minutes: Mapped[int | None] = mapped_column(Integer)

    resting_hr: Mapped[int | None] = mapped_column(Integer)
    min_hr: Mapped[int | None] = mapped_column(Integer)
    max_hr: Mapped[int | None] = mapped_column(Integer)

    avg_stress: Mapped[int | None] = mapped_column(Integer)
    max_stress: Mapped[int | None] = mapped_column(Integer)
    body_battery_high: Mapped[int | None] = mapped_column(Integer)
    body_battery_low: Mapped[int | None] = mapped_column(Integer)

    hrv_last_night_avg: Mapped[int | None] = mapped_column(Integer)
    hrv_status: Mapped[str | None] = mapped_column(String(32))

    sleep_score: Mapped[int | None] = mapped_column(Integer)
    sleep_seconds: Mapped[int | None] = mapped_column(Integer)
    deep_seconds: Mapped[int | None] = mapped_column(Integer)
    light_seconds: Mapped[int | None] = mapped_column(Integer)
    rem_seconds: Mapped[int | None] = mapped_column(Integer)
    awake_seconds: Mapped[int | None] = mapped_column(Integer)
    sleep_start_local: Mapped[datetime | None] = mapped_column(DateTime)
    sleep_end_local: Mapped[datetime | None] = mapped_column(DateTime)

    training_readiness: Mapped[int | None] = mapped_column(Integer)
    vo2max_running: Mapped[float | None] = mapped_column(Float)
    weight_kg: Mapped[float | None] = mapped_column(Float)
    respiration_avg: Mapped[float | None] = mapped_column(Float)
    spo2_avg: Mapped[float | None] = mapped_column(Float)


class Activity(Base):
    __tablename__ = "activities"

    activity_id: Mapped[int] = mapped_column(Integer, primary_key=True)  # Garmin's ID
    start_time_local: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    day: Mapped[date | None] = mapped_column(Date, index=True)
    activity_type: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str | None] = mapped_column(String(255))

    distance_m: Mapped[float | None] = mapped_column(Float)
    duration_s: Mapped[float | None] = mapped_column(Float)
    elevation_gain_m: Mapped[float | None] = mapped_column(Float)

    avg_hr: Mapped[float | None] = mapped_column(Float)
    max_hr: Mapped[float | None] = mapped_column(Float)
    calories: Mapped[float | None] = mapped_column(Float)
    avg_cadence: Mapped[float | None] = mapped_column(Float)
    avg_temp_c: Mapped[float | None] = mapped_column(Float)
    training_load: Mapped[float | None] = mapped_column(Float)
    vo2max: Mapped[float | None] = mapped_column(Float)
