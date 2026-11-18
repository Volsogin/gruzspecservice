"""Max messenger channel — DEMO STUB (listed in ARCHITECTURE.md → "Заглушки").

Max bots, like Telegram bots, can only write to users who started the bot themselves, so the
design mirrors Telegram: a deep link `https://max.ru/<bot>?start=<public_token>` and a webhook
that binds the chat to the lead. Binding is not implemented yet, therefore no `max` client
channels are ever created and this notifier is never called in the main flow.
"""

from __future__ import annotations

import logging

from app.integrations.notifiers.base import OutgoingMessage, SendError, SendResult

logger = logging.getLogger(__name__)


class MaxNotifierStub:
    channel = "max"

    async def send(self, message: OutgoingMessage) -> SendResult:
        logger.warning("max_channel_not_implemented")
        raise SendError("Max channel is not implemented", permanent=True)
