"""Weather model (M9).

Deliberately a SEPARATE table from ``daily_metrics``: weather comes from a
different source (Open-Meteo, not Garmin) with its own provenance, so keeping it
apart preserves ``daily_metrics`` as a pure Garmin projection. Analytics that
want both (e.g. humidity-vs-HR) join them in the loader layer.

Like ``daily_metrics`` this is a rebuildable projection of the append-only raw
layer — one wide row per calendar day, nullable everywhere. Temperatures are
stored in Celsius to match ``activities.avg_temp_c``; the API layer converts to
Fahrenheit for the imperial UI.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Float
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.core import Base


class DailyWeather(Base):
    __tablename__ = "daily_weather"

    day: Mapped[date] = mapped_column(Date, primary_key=True)

    temp_high_c: Mapped[float | None] = mapped_column(Float)
    temp_low_c: Mapped[float | None] = mapped_column(Float)
    apparent_high_c: Mapped[float | None] = mapped_column(Float)
    # Humidity + dew point sampled at the hottest hour of the day — the moment
    # that governs an afternoon run's heat stress, not the 24h mean.
    humidity_pct: Mapped[float | None] = mapped_column(Float)
    dew_point_c: Mapped[float | None] = mapped_column(Float)
    wind_kph: Mapped[float | None] = mapped_column(Float)
