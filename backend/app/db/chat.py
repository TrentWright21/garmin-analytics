"""Coach conversation store: create, append, and replay chat history.

The Coach API is stateless, so each turn replays the stored messages. These
helpers use the shared ``session_scope`` from ``app.db.engine`` and return
plain dicts (not ORM objects) so callers never touch a detached session.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select

from app.db.engine import session_scope
from app.db.models.chat import Conversation, Message

_TITLE_MAX = 60


def _title_from(text: str) -> str:
    """A short, human-readable title from the first user message."""
    clean = " ".join(text.split())
    return clean[: _TITLE_MAX - 1] + "…" if len(clean) > _TITLE_MAX else clean or "New chat"


def create_conversation(first_message: str | None = None) -> str:
    """Create a conversation and return its id. Title seeds from the first message."""
    cid = uuid4().hex
    now = datetime.now(UTC)
    with session_scope() as s:
        s.add(
            Conversation(
                id=cid,
                title=_title_from(first_message) if first_message else None,
                created_at=now,
                updated_at=now,
            )
        )
    return cid


def conversation_exists(conversation_id: str) -> bool:
    with session_scope() as s:
        return s.get(Conversation, conversation_id) is not None


def add_message(conversation_id: str, role: str, content: str) -> None:
    """Append one message and bump the conversation's ``updated_at``.

    If the conversation still has no title, seed it from this message.
    """
    now = datetime.now(UTC)
    with session_scope() as s:
        conv = s.get(Conversation, conversation_id)
        if conv is None:
            raise KeyError(conversation_id)
        s.add(
            Message(
                conversation_id=conversation_id,
                role=role,
                content=content,
                created_at=now,
            )
        )
        conv.updated_at = now
        if conv.title is None:
            conv.title = _title_from(content)


def get_messages(conversation_id: str) -> list[dict[str, Any]]:
    """All messages for a conversation, oldest first."""
    with session_scope() as s:
        rows = (
            s.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.id)
            )
            .scalars()
            .all()
        )
        return [
            {"role": m.role, "content": m.content, "created_at": m.created_at.isoformat()}
            for m in rows
        ]


def get_history(conversation_id: str) -> list[dict[str, str]]:
    """Role/content pairs for replay into the model (no timestamps)."""
    return [{"role": m["role"], "content": m["content"]} for m in get_messages(conversation_id)]


def list_conversations() -> list[dict[str, Any]]:
    """All conversations, most-recently-updated first, with message counts."""
    with session_scope() as s:
        counts: dict[str, int] = {
            cid: n
            for cid, n in s.execute(
                select(Message.conversation_id, func.count(Message.id)).group_by(
                    Message.conversation_id
                )
            ).all()
        }
        convs = (
            s.execute(select(Conversation).order_by(Conversation.updated_at.desc())).scalars().all()
        )
        return [
            {
                "id": c.id,
                "title": c.title or "New chat",
                "created_at": c.created_at.isoformat(),
                "updated_at": c.updated_at.isoformat(),
                "message_count": counts.get(c.id, 0),
            }
            for c in convs
        ]
