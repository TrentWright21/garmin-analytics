"""Telegram Bot API notifier.

Sends a plain-text message via ``sendMessage``. Plain text (no Markdown) avoids
Telegram's fussy escaping rules for a message assembled from arbitrary numbers
and words. The bot token is a secret; the chat id identifies the destination
chat (get both by talking to @BotFather and @userinfobot — see DEPLOY.md).
"""

from __future__ import annotations

import httpx

from app.logging import get_logger

log = get_logger(__name__)

_API = "https://api.telegram.org"
_TIMEOUT_S = 15.0


class TelegramNotifier:
    """Push notifications to one Telegram chat via a bot."""

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._token = bot_token
        self._chat_id = chat_id

    def send(self, title: str, text: str) -> None:
        from app.notify import NotifyError

        body = f"{title}\n\n{text}" if title else text
        try:
            resp = httpx.post(
                f"{_API}/bot{self._token}/sendMessage",
                json={
                    "chat_id": self._chat_id,
                    "text": body,
                    "disable_web_page_preview": True,
                },
                timeout=_TIMEOUT_S,
            )
        except httpx.HTTPError as exc:
            raise NotifyError(f"Telegram request failed: {exc}") from exc
        if resp.status_code != 200:
            # Don't log the token; Telegram echoes a description on error.
            detail = ""
            try:
                detail = str(resp.json().get("description", ""))
            except ValueError:
                detail = resp.text[:200]
            raise NotifyError(f"Telegram API {resp.status_code}: {detail}")
        log.info("notify.sent", channel="telegram")
