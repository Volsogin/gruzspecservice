"""E-mail delivery: SMTP in production, `.eml` files in dev (when SMTP_HOST is not set)."""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
import uuid
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from pathlib import Path

from app.integrations.notifiers.base import OutgoingMessage, SendError, SendResult

logger = logging.getLogger(__name__)


def build_email(message: OutgoingMessage, sender: str) -> EmailMessage:
    email = EmailMessage()
    email["From"] = sender
    email["To"] = message.recipient
    email["Subject"] = message.subject or "ГРУЗСПЕЦСЕРВИС"
    email["Date"] = format_datetime(datetime.now(UTC))
    email["Message-ID"] = make_msgid(domain=sender.rsplit("@", 1)[-1].rstrip(">") or "localhost")
    email.set_content(message.text)
    if message.html:
        email.add_alternative(message.html, subtype="html")
    return email


class SmtpEmailNotifier:
    channel = "email"

    def __init__(
        self,
        host: str,
        port: int,
        sender: str,
        user: str | None,
        password: str | None,
        starttls: bool,
        use_ssl: bool,
        timeout: float,
    ) -> None:
        self.host, self.port, self.sender = host, port, sender
        self.user, self.password = user, password
        self.starttls, self.use_ssl, self.timeout = starttls, use_ssl, timeout

    def _send_sync(self, email: EmailMessage) -> None:
        context = ssl.create_default_context()
        smtp: smtplib.SMTP
        if self.use_ssl:
            smtp = smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout, context=context)
        else:
            smtp = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
        with smtp:
            if self.starttls and not self.use_ssl:
                smtp.starttls(context=context)
            if self.user and self.password:
                smtp.login(self.user, self.password)
            smtp.send_message(email)

    async def send(self, message: OutgoingMessage) -> SendResult:
        email = build_email(message, self.sender)
        try:
            await asyncio.to_thread(self._send_sync, email)
        except smtplib.SMTPRecipientsRefused as exc:
            raise SendError("recipient refused", permanent=True) from exc
        except (smtplib.SMTPException, OSError) as exc:
            raise SendError(f"smtp error: {type(exc).__name__}") from exc
        return SendResult(external_id=str(email["Message-ID"]))


class FileEmailNotifier:
    """Writes each e-mail as an `.eml` file — open it in any mail client to preview."""

    channel = "email"

    def __init__(self, directory: Path, sender: str) -> None:
        self.directory = directory
        self.sender = sender

    async def send(self, message: OutgoingMessage) -> SendResult:
        email = build_email(message, self.sender)
        self.directory.mkdir(parents=True, exist_ok=True)
        name = f"{datetime.now(UTC):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}.eml"
        await asyncio.to_thread((self.directory / name).write_bytes, bytes(email))
        logger.info("email_saved_to_file", extra={"file": name, "subject": message.subject})
        return SendResult(external_id=name)
