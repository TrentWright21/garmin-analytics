"""AI metric-insight cache + usage log (redesign Phase 3, stage 6).

Ordinary mutable tables (NOT the append-only raw layer): they exist purely to
keep external AI cost under control — one caches generated summaries so the same
request never pays twice, the other records every insight request for auditing
spend. They share the core ``Base`` so ``create_all`` picks them up with no
separate migration. No raw health values are stored — only the metric key, a
data fingerprint, and the generated text.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.core import Base


class AiInsightCache(Base):
    __tablename__ = "ai_insight_cache"
    __table_args__ = (
        UniqueConstraint("metric_key", "range_days", "fingerprint", name="uq_ai_cache"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    metric_key: Mapped[str] = mapped_column(String(64))
    range_days: Mapped[int] = mapped_column(Integer)
    # sha256 of (key, range, latest-data signature, insight version): changes
    # when the underlying data materially changes, so the cache self-invalidates.
    fingerprint: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(64))
    insight: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class AiUsageLog(Base):
    __tablename__ = "ai_usage_log"
    __table_args__ = (Index("ix_ai_usage_created", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    metric_key: Mapped[str] = mapped_column(String(64))
    range_days: Mapped[int] = mapped_column(Integer)
    # local | cached | generated | refused | error — how the request was served.
    source: Mapped[str] = mapped_column(String(16))
    model: Mapped[str | None] = mapped_column(String(64))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime)
