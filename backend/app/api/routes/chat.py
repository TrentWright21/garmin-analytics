"""Coach chat API: converse with Claude about your own Garmin analytics.

Stateless: each turn loads the stored conversation, replays it into the
model, and persists the new user message + assistant reply. Returns JSON
(v1); streaming can layer on later. When GA_ANTHROPIC_API_KEY is unset every
endpoint still responds — the chat endpoint returns a clear "not configured"
message instead of an error, so the rest of the dashboard is unaffected.
"""

from __future__ import annotations

from typing import Any

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.ai import coach as coach_mod
from app.config import get_settings
from app.db import chat as store
from app.logging import get_logger
from app.ratelimit import RateLimiter, rate_limiter

log = get_logger(__name__)
router = APIRouter(prefix="/api/coach")

# Each chat turn can spend Anthropic credits — cap the rate so a runaway client
# can't rack up cost. 20/min is generous for a person typing.
_chat_limiter = RateLimiter(max_calls=20, window_s=60.0)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None


@router.get("/status")
def status() -> dict[str, bool]:
    """Whether the AI Coach has an API key configured (drives the setup hint)."""
    return {"configured": coach_mod.is_configured(get_settings())}


@router.get("/conversations")
def list_conversations() -> dict[str, Any]:
    """Past conversations, most-recently-updated first."""
    return {"conversations": store.list_conversations()}


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str) -> dict[str, Any]:
    """Full message history for one conversation."""
    if not store.conversation_exists(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return {"id": conversation_id, "messages": store.get_messages(conversation_id)}


@router.post("/chat", dependencies=[Depends(rate_limiter(_chat_limiter))])
def chat(req: ChatRequest) -> dict[str, Any]:
    """Send a message; get the assistant's reply. Creates a conversation if none given."""
    settings = get_settings()

    # Not configured: answer helpfully instead of erroring, and don't start a
    # conversation that can't get a real reply.
    if not coach_mod.is_configured(settings):
        return {
            "configured": False,
            "conversation_id": req.conversation_id,
            "reply": coach_mod.NOT_CONFIGURED_MESSAGE,
        }

    conversation_id = req.conversation_id
    if conversation_id is None:
        conversation_id = store.create_conversation(req.message)
    elif not store.conversation_exists(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found.")

    # Prior turns to replay; then persist this user message so it survives even
    # if the model call fails.
    history = store.get_history(conversation_id)
    store.add_message(conversation_id, "user", req.message)

    try:
        reply = coach_mod.Coach(settings).reply(history, req.message)
    except anthropic.APIStatusError as exc:
        log.warning("coach.api_error", status=exc.status_code)
        raise HTTPException(
            status_code=502,
            detail="The AI Coach couldn't reach Claude just now. Please try again.",
        ) from exc
    except anthropic.APIError as exc:
        log.warning("coach.api_error", err=type(exc).__name__)
        raise HTTPException(
            status_code=502,
            detail="The AI Coach couldn't reach Claude just now. Please try again.",
        ) from exc

    store.add_message(conversation_id, "assistant", reply)
    return {"configured": True, "conversation_id": conversation_id, "reply": reply}
