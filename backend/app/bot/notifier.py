"""Notification sink interface (doc §10.3).

The bot raises events — signals, fills, risk events, mode transitions, kill switch —
without knowing where they go. :class:`NullNotifier` is the default (tests + no
token). :class:`~app.bot.telegram.TelegramNotifier` is the real sink, gated on a
configured bot token (operator step).
"""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class Notifier(Protocol):
    """Anything that can deliver a one-line notification."""

    async def notify(self, text: str) -> None: ...


class NullNotifier:
    """Swallows notifications (records the last few for tests/inspection)."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def notify(self, text: str) -> None:
        self.sent.append(text)
        logger.debug("notify(null): %s", text)


def default_notifier() -> Notifier:
    """The configured sink: real Telegram when a token is set, else the null sink."""
    from app.core.config import settings

    if settings.telegram_enabled and settings.telegram_bot_token:
        from app.bot.telegram import TelegramNotifier

        return TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
    return NullNotifier()
