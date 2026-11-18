"""Telegram bot updates: `/start <token>` binding, operator status buttons, operator chat replies.

The same `TelegramBot.handle_update()` serves both long polling (dev/demo) and the webhook.
"""

from __future__ import annotations

import asyncio
import html
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import ChatMessage, ClientChannel, Lead
from app.domain.statuses import STATUS_LABELS, LeadStatus, status_label
from app.integrations.notifiers.base import InlineButton, SendError, is_public_url
from app.integrations.notifiers.telegram import TelegramClient
from app.services.chat.live import LiveChatHub
from app.services.lead_status import change_status
from app.services.notifications import Routing, operator_buttons, render_operator_lead

logger = logging.getLogger(__name__)

WELCOME = (
    "Здравствуйте! Это бот ГРУЗСПЕЦСЕРВИС. Чтобы получать статус заявки, нажмите кнопку "
    "«Получать статус в Telegram» на сайте после отправки заявки."
)


class TelegramBot:
    def __init__(
        self,
        client: TelegramClient,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        live_chat: LiveChatHub,
        on_commit: Any = lambda: None,
    ) -> None:
        self.client = client
        self.session_factory = session_factory
        self.settings = settings
        self.live_chat = live_chat
        self.on_commit = on_commit
        self.routing = Routing.from_settings(settings)
        self._offset: int | None = None

    async def handle_update(self, update: dict[str, Any]) -> None:
        try:
            if cq := update.get("callback_query"):
                await self._on_callback(cq)
            elif msg := update.get("message"):
                await self._on_message(msg)
        except SendError as exc:
            logger.warning("telegram_reply_failed", extra={"error": str(exc)[:200]})

    # --- messages ------------------------------------------------------------------------------
    async def _on_message(self, msg: dict[str, Any]) -> None:
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        text = str(msg.get("text") or "")
        if chat_id is None:
            return
        if text.split("@", 1)[0].split(maxsplit=1)[0:1] == ["/chatid"]:
            await self._reply_chat_id(chat_id, chat)
            return
        if self.routing.operator_tg_chat_id is not None and chat_id == self.routing.operator_tg_chat_id:
            reply_to = (msg.get("reply_to_message") or {}).get("message_id")
            if reply_to and text and not text.startswith("/"):
                await self._operator_reply(int(reply_to), text, msg.get("from") or {})
            return
        if chat.get("type") != "private":
            return
        if text.startswith("/start"):
            parts = text.split(maxsplit=1)
            if len(parts) == 2:
                await self._bind(chat_id, parts[1].strip())
            else:
                await self.client.send_message(chat_id, html.escape(WELCOME))

    async def _reply_chat_id(self, chat_id: int, chat: dict[str, Any]) -> None:
        """Setup helper: tells the id to put into OPERATOR_TG_CHAT_ID (chat ids are not secret)."""
        is_operator_chat = chat_id == self.routing.operator_tg_chat_id
        text = f"ID этого чата: <code>{chat_id}</code>"
        if is_operator_chat:
            text += "\nЭтот чат уже подключён как чат операторов ✅"
        elif chat.get("type") in ("group", "supergroup"):
            text += f"\nЧтобы заявки приходили сюда, укажите в .env:\n<code>OPERATOR_TG_CHAT_ID={chat_id}</code>"
        logger.info("telegram_chat_id_requested", extra={"chat_type": chat.get("type")})
        await self.client.send_message(chat_id, text)

    async def _bind(self, chat_id: int, token: str) -> None:
        async with self.session_factory() as session:
            lead = await session.scalar(
                select(Lead).where(Lead.public_token == token[:64]).options(selectinload(Lead.channels))
            )
            if lead is None:
                await self.client.send_message(chat_id, "Заявка по этой ссылке не найдена. Проверьте ссылку на сайте.")
                return
            address = str(chat_id)
            if not any(c.kind == "telegram" and c.address == address for c in lead.channels):
                session.add(ClientChannel(lead_id=lead.id, kind="telegram", address=address))
                await session.commit()
            number, status = lead.number, lead.status
            tracking = self.settings.tracking_url(lead.public_token)
        logger.info("telegram_bound", extra={"lead_number": number})
        text = (
            f"Готово! Будем присылать сюда статус заявки <b>{html.escape(number)}</b>.\n"
            f"Сейчас: {html.escape(status_label(status))}."
        )
        if is_public_url(tracking):
            await self.client.send_message(chat_id, text, buttons=[[InlineButton("Открыть заявку", url=tracking)]])
        else:  # dev: Telegram rejects localhost URLs in buttons
            await self.client.send_message(chat_id, f"{text}\nЗаявка: {html.escape(tracking)}")

    async def _operator_reply(self, reply_to_message_id: int, text: str, sender: dict[str, Any]) -> None:
        async with self.session_factory() as session:
            original = await session.scalar(select(ChatMessage).where(ChatMessage.tg_message_id == reply_to_message_id))
            chat_session_id = original.session_id if original else None
            if chat_session_id is None:  # a reply to the lead card of a chat_handoff lead also works
                chat_session_id = await session.scalar(
                    select(Lead.chat_session_id).where(
                        Lead.operator_tg_message_id == reply_to_message_id, Lead.chat_session_id.is_not(None)
                    )
                )
            if chat_session_id is None:
                return
            operator_name = str(sender.get("first_name") or "Оператор")[:40]
            await self.live_chat.post_operator_message(session, chat_session_id, text, operator_name)
            await session.commit()

    # --- operator buttons ------------------------------------------------------------------------
    async def _on_callback(self, cq: dict[str, Any]) -> None:
        data = str(cq.get("data") or "")
        message = cq.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        user = cq.get("from") or {}
        if self.routing.operator_tg_chat_id is None or chat_id != self.routing.operator_tg_chat_id:
            await self.client.answer_callback_query(cq["id"], "Недоступно")
            return
        try:
            prefix, lead_hex, target = data.split(":", 2)
            lead_id = uuid.UUID(hex=lead_hex)
            if prefix != "st" or target not in {s.value for s in STATUS_LABELS}:
                raise ValueError(data)
        except ValueError:
            await self.client.answer_callback_query(cq["id"], "Неизвестная команда")
            return

        actor = f"telegram:{user.get('username') or user.get('id')}"
        async with self.session_factory() as session:
            try:
                lead = await change_status(session, lead_id, target, actor=actor, routing=self.routing)
            except AppError as exc:
                await self.client.answer_callback_query(cq["id"], exc.message)
                return
            if message.get("message_id"):
                lead.operator_tg_message_id = int(message["message_id"])
            await session.commit()
            text = render_operator_lead(lead, self.settings, html_mode=True)
            buttons = operator_buttons(lead)
        self.on_commit()
        await self.client.answer_callback_query(cq["id"], f"Статус: {STATUS_LABELS[LeadStatus(target)]}")
        if message.get("message_id"):
            await self.client.edit_message_text(chat_id, int(message["message_id"]), text, buttons)

    # --- long polling ----------------------------------------------------------------------------
    async def run_polling(self, stop: asyncio.Event) -> None:
        try:
            await self.client.delete_webhook()
        except SendError as exc:
            logger.error("telegram_polling_disabled", extra={"error": str(exc)[:200]})
            return
        logger.info("telegram_polling_started")
        while not stop.is_set():
            try:
                updates = await self.client.get_updates(self._offset, timeout=25)
            except SendError as exc:
                logger.warning("telegram_poll_error", extra={"error": str(exc)[:200]})
                await asyncio.sleep(5)
                continue
            for update in updates:
                self._offset = int(update["update_id"]) + 1
                try:
                    await self.handle_update(update)
                except Exception:
                    logger.exception("telegram_update_failed")
