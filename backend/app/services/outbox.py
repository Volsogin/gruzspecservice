"""Outbox dispatcher: claims due rows, renders and delivers them, retries with backoff.

Claiming uses a short "lease" transaction (status=processing + lease deadline), then each message
is delivered outside of any DB transaction, so slow SMTP never blocks writers. Crashed workers'
leases expire and rows are picked up again.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.db.base import utcnow
from app.db.models import ChatMessage, Lead, OutboxMessage
from app.integrations.notifiers.base import Notifier, OutgoingMessage, SendError
from app.integrations.notifiers.telegram import TelegramClient
from app.services import notifications as n
from app.services.site_settings import load_settings

logger = logging.getLogger(__name__)

LEASE = timedelta(minutes=5)


def backoff(attempt: int) -> timedelta:
    return timedelta(seconds=min(3600, 10 * 2 ** max(0, attempt - 1)))


class OutboxDispatcher:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        notifiers: dict[str, Notifier],
        settings: Settings,
        telegram: TelegramClient | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.notifiers = notifiers
        self.settings = settings
        self.telegram = telegram
        self.kick_event = asyncio.Event()
        self._handlers: dict[str, Callable[[AsyncSession, OutboxMessage], Awaitable[None]]] = {
            n.OPERATOR_LEAD_CREATED: self._operator_lead_created,
            n.OPERATOR_LEAD_REFRESH: self._operator_lead_refresh,
            n.OPERATOR_CHAT_MESSAGE: self._operator_chat_message,
            n.CLIENT_LEAD_CREATED: self._client_lead_created,
            n.CLIENT_STATUS_CHANGED: self._client_status_changed,
        }

    def kick(self) -> None:
        """Wake the worker right after a commit (instead of waiting for the next poll)."""
        self.kick_event.set()

    async def _claim(self, limit: int) -> list[int]:
        now = utcnow()
        async with self.session_factory() as session:
            query = (
                select(OutboxMessage.id)
                .where(
                    or_(OutboxMessage.status == "pending", OutboxMessage.status == "processing"),
                    OutboxMessage.next_attempt_at <= now,
                )
                .order_by(OutboxMessage.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            ids = list((await session.scalars(query)).all())
            if ids:
                await session.execute(
                    update(OutboxMessage)
                    .where(OutboxMessage.id.in_(ids))
                    .values(status="processing", next_attempt_at=now + LEASE)
                )
            await session.commit()
        return ids

    async def process_batch(self, limit: int = 20) -> int:
        """Deliver up to `limit` due messages. Returns how many were attempted."""
        ids = await self._claim(limit)
        for msg_id in ids:
            await self._process_one(msg_id)
        return len(ids)

    async def drain(self, max_rounds: int = 10) -> None:
        """Process until nothing is due (used by tests and `make outbox`)."""
        for _ in range(max_rounds):
            if not await self.process_batch():
                return

    async def _process_one(self, msg_id: int) -> None:
        async with self.session_factory() as session:
            msg = await session.get(OutboxMessage, msg_id)
            if msg is None or msg.status != "processing":
                return
            handler = self._handlers.get(msg.kind)
            try:
                if handler is None:
                    raise SendError(f"no handler for {msg.kind}", permanent=True)
                await handler(session, msg)
            except SendError as exc:
                self._fail(msg, str(exc), permanent=exc.permanent)
            except Exception as exc:
                logger.exception("outbox_handler_crashed", extra={"outbox_id": msg.id, "kind": msg.kind})
                self._fail(msg, f"{type(exc).__name__}: {exc}"[:200], permanent=False)
            else:
                msg.status, msg.sent_at, msg.last_error = "sent", utcnow(), None
                msg.attempts += 1
            await session.commit()

    def _fail(self, msg: OutboxMessage, error: str, *, permanent: bool) -> None:
        msg.attempts += 1
        msg.last_error = error[:500]
        if permanent or msg.attempts >= self.settings.outbox_max_attempts:
            msg.status = "dead"
            logger.error("outbox_dead", extra={"outbox_id": msg.id, "kind": msg.kind, "error": error[:200]})
        else:
            msg.status = "pending"
            msg.next_attempt_at = utcnow() + backoff(msg.attempts)
            logger.warning(
                "outbox_retry",
                extra={"outbox_id": msg.id, "kind": msg.kind, "attempt": msg.attempts, "error": error[:200]},
            )

    def _notifier(self, channel: str) -> Notifier:
        notifier = self.notifiers.get(channel)
        if notifier is None:
            raise SendError(f"channel {channel} is not configured", permanent=True)
        return notifier

    async def _load_lead(self, session: AsyncSession, msg: OutboxMessage) -> Lead:
        lead = await session.scalar(
            select(Lead)
            .where(Lead.id == msg.lead_id)
            .options(selectinload(Lead.attachments), selectinload(Lead.estimate))
        )
        if lead is None:
            raise SendError("lead not found", permanent=True)
        return lead

    # --- handlers --------------------------------------------------------------------------------
    async def _operator_lead_created(self, session: AsyncSession, msg: OutboxMessage) -> None:
        lead = await self._load_lead(session, msg)
        to = str(msg.payload["to"])
        if msg.channel == "telegram":
            result = await self._notifier("telegram").send(
                OutgoingMessage(
                    channel="telegram",
                    recipient=to,
                    text="",
                    html=n.render_operator_lead(lead, self.settings, html_mode=True),
                    buttons=n.operator_buttons(lead),
                )
            )
            if result.external_id and result.external_id.isdigit():
                lead.operator_tg_message_id = int(result.external_id)
            return
        text = n.render_operator_lead(lead, self.settings, html_mode=False)
        subject = f"Новая заявка {lead.number}: {lead.type} — {lead.vehicle_brand or ''}".strip(" —")
        await self._notifier(msg.channel).send(
            OutgoingMessage(channel=msg.channel, recipient=to, text=text, subject=subject)
        )

    async def _operator_lead_refresh(self, session: AsyncSession, msg: OutboxMessage) -> None:
        lead = await self._load_lead(session, msg)
        if self.telegram is None or not lead.operator_tg_message_id:
            return
        await self.telegram.edit_message_text(
            msg.payload["to"],
            lead.operator_tg_message_id,
            n.render_operator_lead(lead, self.settings, html_mode=True),
            n.operator_buttons(lead),
        )

    async def _operator_chat_message(self, session: AsyncSession, msg: OutboxMessage) -> None:
        chat_msg = await session.get(ChatMessage, int(msg.payload["chat_message_id"]))
        if chat_msg is None:
            raise SendError("chat message not found", permanent=True)
        header = f"💬 Чат {chat_msg.session_id.hex[:8]} — ответьте реплаем на это сообщение"
        result = await self._notifier("telegram").send(
            OutgoingMessage(
                channel="telegram",
                recipient=str(msg.payload["to"]),
                text="",
                html=f"<b>{n._e(header)}</b>\n{n._e(chat_msg.content)}",
            )
        )
        if result.external_id and result.external_id.isdigit():
            chat_msg.tg_message_id = int(result.external_id)

    async def _client_lead_created(self, session: AsyncSession, msg: OutboxMessage) -> None:
        lead = await self._load_lead(session, msg)
        company = (await load_settings(session)).company_name
        subject, text, html_body = n.render_client_created(lead, self.settings, company)
        await self._notifier("email").send(
            OutgoingMessage(
                channel="email", recipient=str(msg.payload["to"]), text=text, subject=subject, html=html_body
            )
        )

    async def _client_status_changed(self, session: AsyncSession, msg: OutboxMessage) -> None:
        lead = await self._load_lead(session, msg)
        company = (await load_settings(session)).company_name
        html_mode = msg.channel == "telegram"
        subject, text = n.render_client_status(lead, msg.payload, self.settings, company, html_mode=html_mode)
        await self._notifier(msg.channel).send(
            OutgoingMessage(
                channel=msg.channel,
                recipient=str(msg.payload["to"]),
                subject=subject,
                text=text,
                html=text if html_mode else None,
            )
        )

    # --- worker loop -------------------------------------------------------------------------------
    async def run_forever(self, stop: asyncio.Event) -> None:
        logger.info("outbox_worker_started")
        while not stop.is_set():
            self.kick_event.clear()  # clear first: a kick during processing triggers one more pass
            try:
                while await self.process_batch():
                    pass
            except Exception:
                logger.exception("outbox_worker_error")
            with suppress(TimeoutError):
                await asyncio.wait_for(self.kick_event.wait(), timeout=self.settings.outbox_poll_seconds)
        logger.info("outbox_worker_stopped")
