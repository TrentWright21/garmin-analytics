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

    # Garmin's own daily verdicts (from training_readiness / training_status
    # payloads): the native recovery timer, its acute-load number, the
    # training-status feedback phrase (e.g. "UNPRODUCTIVE_5"), and Garmin's own
    # acute:chronic workload ratio (cross-checks our EWMA-based ACWR).
    training_status: Mapped[str | None] = mapped_column(String(64))
    recovery_time_min: Mapped[int | None] = mapped_column(Integer)
    acute_load_garmin: Mapped[int | None] = mapped_column(Integer)
    hrv_weekly_avg: Mapped[int | None] = mapped_column(Integer)
    acwr_garmin: Mapped[float | None] = mapped_column(Float)

    # Overnight extras from the sleep payload's top level (outside the DTO):
    # Body Battery recharge, restlessness, and skin-temperature deviation
    # (an illness early-warning signal).
    body_battery_change: Mapped[int | None] = mapped_column(Integer)
    restless_moments: Mapped[int | None] = mapped_column(Integer)
    skin_temp_dev_c: Mapped[float | None] = mapped_column(Float)


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

    # Garmin Training Effect + speed + HR-zone seconds (from the activity-list
    # payload). te_label is Garmin's session classification, e.g. TEMPO/RECOVERY.
    aerobic_te: Mapped[float | None] = mapped_column(Float)
    anaerobic_te: Mapped[float | None] = mapped_column(Float)
    te_label: Mapped[str | None] = mapped_column(String(64))
    avg_speed_mps: Mapped[float | None] = mapped_column(Float)
    zone_1_s: Mapped[float | None] = mapped_column(Float)
    zone_2_s: Mapped[float | None] = mapped_column(Float)
    zone_3_s: Mapped[float | None] = mapped_column(Float)
    zone_4_s: Mapped[float | None] = mapped_column(Float)
    zone_5_s: Mapped[float | None] = mapped_column(Float)


class RacePrediction(Base):
    """Garmin's daily race-time predictions (seconds), one row per day.

    Built from the ``race_predictions`` snapshot payloads; the payload's own
    ``calendarDate`` keys the row. A rebuildable projection like the other
    normalized tables.
    """

    __tablename__ = "race_predictions"

    day: Mapped[date] = mapped_column(Date, primary_key=True)

    time_5k_s: Mapped[int | None] = mapped_column(Integer)
    time_10k_s: Mapped[int | None] = mapped_column(Integer)
    time_half_s: Mapped[int | None] = mapped_column(Integer)
    time_marathon_s: Mapped[int | None] = mapped_column(Integer)
