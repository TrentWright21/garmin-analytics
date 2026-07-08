"""Notification channel for the automated morning message.

A thin ``Notifier`` protocol (send a title + text) with a Telegram
implementation. The channel is optional and best-effort: if it isn't
configured, ``build_notifier`` returns None and the scheduled job no-ops. The
message body is composed by the pure ``format_brief`` in ``message.py`` from the
existing ``build_briefing`` output — no analytics are duplicated here.
"""

from __future__ import annotations

from typing import Protocol

from app.config import Settings
from app.notify.telegram import TelegramNotifier


class NotifyError(Exception):
    """Any failure delivering a notification. Callers treat sends as best-effort."""


class Notifier(Protocol):
    """Anything that can push a short title + text to the user's phone."""

    def send(self, title: str, text: str) -> None:
        """Deliver one message. Raises NotifyError on failure."""
        ...


def is_configured(settings: Settings) -> bool:
    """True when the Telegram channel has both a bot token and a chat id."""
    return settings.telegram_bot_token is not None and bool(settings.telegram_chat_id)


def build_notifier(settings: Settings) -> Notifier | None:
    """Construct the configured notifier, or None if the channel isn't set up."""
    if not is_configured(settings):
        return None
    assert settings.telegram_bot_token is not None  # guarded by is_configured
    assert settings.telegram_chat_id is not None
    return TelegramNotifier(
        bot_token=settings.telegram_bot_token.get_secret_value(),
        chat_id=settings.telegram_chat_id,
    )


__all__ = ["Notifier", "NotifyError", "TelegramNotifier", "build_notifier", "is_configured"]
