"""Notifier interface shared by all delivery channels."""

from __future__ import annotations

import html
import ipaddress
import logging
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InlineButton:
    text: str
    callback_data: str | None = None
    url: str | None = None


@dataclass(frozen=True)
class OutgoingMessage:
    channel: str
    recipient: str
    text: str
    subject: str | None = None
    html: str | None = None
    buttons: list[list[InlineButton]] = field(default_factory=list)
    reply_to_message_id: int | None = None


@dataclass(frozen=True)
class SendResult:
    external_id: str | None = None


_LOCAL_SUFFIXES = (".local", ".localhost", ".test", ".internal", ".lan")


def is_public_url(url: str) -> bool:
    """Telegram rejects buttons/links to localhost and private hosts ("Wrong HTTP URL")."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return "." in host and host != "localhost" and not host.endswith(_LOCAL_SUFFIXES)
    return ip.is_global


def telegram_link(url: str, title: str) -> str:
    """HTML link if Telegram will accept it, otherwise the bare URL as text (dev on localhost)."""
    escaped = html.escape(url, quote=True)
    return f'<a href="{escaped}">{html.escape(title, quote=False)}</a>' if is_public_url(url) else escaped


class SendError(Exception):
    """Delivery failed. `permanent=True` means retrying will not help (e.g. bot blocked by user)."""

    def __init__(self, message: str, *, permanent: bool = False) -> None:
        super().__init__(message)
        self.permanent = permanent


class Notifier(Protocol):
    channel: str

    async def send(self, message: OutgoingMessage) -> SendResult: ...


class LogNotifier:
    """Dev fallback: writes the message to the log instead of delivering it."""

    def __init__(self, channel: str) -> None:
        self.channel = channel

    async def send(self, message: OutgoingMessage) -> SendResult:
        logger.info("notification_dev_fallback", extra={"channel": self.channel, "text": message.text[:500]})
        return SendResult(external_id=None)
