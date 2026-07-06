"""Coach chat persistence models.

These are NOT Garmin data — they store the AI Coach conversation so a chat
can continue across stateless API requests. They share the same declarative
``Base`` as the core models, so ``Base.metadata.create_all`` picks them up
with no separate migration. Ordinary mutable tables: unlike ``raw_api_data``,
titles and ``updated_at`` are meant to change.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.core import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # uuid4 hex
    title: Mapped[str | None] = mapped_column(String(255))  # derived from first message
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)  # bumped on each message


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation", "conversation_id", "id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("conversations.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(16))  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)
