"""Telegram bot: one bot for clients and operators.

Clients (private chat):
  * `/start <public_token>` from the website button → subscribe to that lead's statuses;
  * `/start` alone → auto-subscribe to leads where the client typed this @username in the form;
  * «📱 Поделиться номером» (Telegram's verified contact, not typed text!) → find leads by phone;
  * «📋 Мои заявки» → status, ask a question (goes to operators), cancel while the master hasn't left.
Operators:
  * `/operator <invite code>` → registered; new leads arrive as cards in the private chat;
  * «✋ Беру» → first presser becomes responsible, other cards switch to «Взял: …»;
  * status buttons → only for the responsible one; `/smena` toggles receiving new leads; `/moi` — my leads;
  * reply to a client question / website chat message / lead card → the answer goes back to the client.
The operators group (OPERATOR_TG_CHAT_ID) is the fallback when nobody is on shift.
`handle_update()` serves both long polling and the webhook.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.core.errors import AppError, RateLimited
from app.core.ratelimit import RateLimiter
from app.core.security import constant_time_equals
from app.db.base import utcnow
from app.db.models import ClientChannel, Lead, OperatorCard, TgClient, TgRelay
from app.domain.phone import InvalidPhone, format_phone, mask_phone, normalize_phone
from app.domain.statuses import LEAD_TYPE_LABELS, STATUS_LABELS, TERMINAL, LeadStatus, LeadType, status_label
from app.integrations.notifiers.base import InlineButton, SendError, is_public_url
from app.integrations.notifiers.telegram import TelegramClient
from app.services.chat.live import LiveChatHub
from app.services.lead_status import change_status
from app.services.notifications import Routing, enqueue_client_message, enqueue_operator_reply
from app.services.operators import operator_by_user, register_operator

logger = logging.getLogger(__name__)

SHARE_PHONE = "📱 Поделиться номером"  # still handled if a client sends their contact, but not offered
FIND_LEAD = "🔎 Найти заявку"
MY_LEADS = "📋 Мои заявки"
CLIENT_KEYBOARD = [[{"text": FIND_LEAD}, {"text": MY_LEADS}]]
FIND_ATTEMPTS_PER_HOUR = 6
_LEAD_NUMBER = re.compile(r"^\s*(?:gs|гс|№)?\s*[-–—]?\s*(\d{3,7})\s*$", re.IGNORECASE)
ASK_PHONE = (
    "Напишите телефон, который указывали в заявке, например <code>+7 900 123-45-67</code>.\n"
    "Потом спрошу номер заявки — он был на экране после отправки и в письме (например, GS-1003)."
)
CLIENT_CANCELLABLE = frozenset({LeadStatus.NEW.value, LeadStatus.ACCEPTED.value})
AUTO_BIND_DAYS = 30
MAX_LISTED = 5

CLIENT_HELP = (
    "Здравствуйте! Это бот грузового автосервиса <b>ГРУЗСПЕЦСЕРВИС</b>.\n\n"
    "Здесь можно следить за статусом заявки, задать вопрос оператору или отменить заявку.\n"
    "Нажмите «🔎 Найти заявку» — найду её по телефону и номеру заявки.\n\n"
    "Оставить новую заявку можно на сайте."
)
OPERATOR_HELP = (
    "Вы оператор ✅\n"
    "• Новые заявки приходят сюда карточками — нажмите «✋ Беру», чтобы стать ответственным.\n"
    "• Кнопки статусов есть только у ответственного.\n"
    "• Ответьте реплаем на вопрос клиента или на карточку — ответ уйдёт клиенту.\n"
    "• /smena — включить/выключить получение новых заявок, /moi — мои заявки в работе."
)


def _command(text: str) -> tuple[str, str]:
    """`/start@bot payload` → ("/start", "payload")."""
    head, _, rest = text.strip().partition(" ")
    return head.split("@", 1)[0].lower(), rest.strip()


class TelegramBot:
    def __init__(
        self,
        client: TelegramClient,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        live_chat: LiveChatHub,
        on_commit: Any = lambda: None,
        limiter: RateLimiter | None = None,
    ) -> None:
        self.client = client
        self.limiter = limiter or RateLimiter()
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

    async def _send(self, chat_id: int, text: str, **kwargs: Any) -> None:
        await self.client.send_message(chat_id, text, **kwargs)

    # --- messages ------------------------------------------------------------------------------
    async def _on_message(self, msg: dict[str, Any]) -> None:
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        user = msg.get("from") or {}
        text = str(msg.get("text") or "")
        if chat_id is None:
            return
        cmd, arg = _command(text) if text.startswith("/") else ("", "")
        if cmd == "/chatid":
            await self._reply_chat_id(chat_id, chat)
            return
        reply_to = (msg.get("reply_to_message") or {}).get("message_id")
        if chat.get("type") != "private":
            if chat_id == self.routing.operator_tg_chat_id and reply_to and text and not cmd:
                await self._relay_operator_reply(chat_id, int(reply_to), text, user)
            return
        if reply_to and text and not cmd and await self._relay_operator_reply(chat_id, int(reply_to), text, user):
            return
        if cmd == "/operator":
            await self._register_operator(chat_id, user, arg)
        elif cmd in ("/smena", "/shift"):
            await self._toggle_shift(chat_id, user, arg)
        elif cmd == "/moi":
            await self._operator_leads(chat_id, user)
        elif cmd == "/start":
            await self._start(chat_id, user, arg)
        elif cmd in ("/zayavki", "/orders") or text == MY_LEADS:
            await self._list_client_leads(chat_id)
        elif cmd == "/help":
            async with self.session_factory() as session:
                is_operator = await operator_by_user(session, user.get("id")) is not None
            await self._send(chat_id, OPERATOR_HELP if is_operator else CLIENT_HELP, reply_keyboard=CLIENT_KEYBOARD)
        elif text == FIND_LEAD:
            await self._send(chat_id, ASK_PHONE)
        elif msg.get("contact"):
            await self._on_contact(chat_id, user, msg["contact"])
        elif text and not cmd:
            await self._client_text(chat_id, user, text)

    async def _reply_chat_id(self, chat_id: int, chat: dict[str, Any]) -> None:
        """Setup helper: tells the id to put into OPERATOR_TG_CHAT_ID (chat ids are not secret)."""
        text = f"ID этого чата: <code>{chat_id}</code>"
        if chat_id == self.routing.operator_tg_chat_id:
            text += "\nЭтот чат уже подключён как чат операторов ✅"
        elif chat.get("type") in ("group", "supergroup"):
            text += f"\nЧтобы заявки приходили сюда, укажите в .env:\n<code>OPERATOR_TG_CHAT_ID={chat_id}</code>"
        else:
            text += "\nЭто личный чат. Операторам удобнее зарегистрироваться командой /operator &lt;код&gt;."
        logger.info("telegram_chat_id_requested", extra={"chat_type": chat.get("type")})
        await self._send(chat_id, text)

    # --- operators -----------------------------------------------------------------------------
    async def _register_operator(self, chat_id: int, user: dict[str, Any], code: str) -> None:
        expected = self.settings.operator_invite_code
        if expected is None:
            await self._send(chat_id, "Регистрация операторов выключена (не задан OPERATOR_INVITE_CODE).")
            return
        if not constant_time_equals(code, expected.get_secret_value()):
            logger.warning("operator_registration_rejected")
            await self._send(chat_id, "Неверный код приглашения.")
            return
        async with self.session_factory() as session:
            op, created = await register_operator(session, user, chat_id)
            await session.commit()
            name = op.name
        logger.info("operator_registered", extra={"new_operator": created})
        await self._send(chat_id, f"{html.escape(name)}, " + OPERATOR_HELP)

    async def _toggle_shift(self, chat_id: int, user: dict[str, Any], arg: str) -> None:
        async with self.session_factory() as session:
            op = await operator_by_user(session, user.get("id"))
            if op is None:
                await self._send(chat_id, "Команда для операторов. Регистрация: /operator &lt;код&gt;.")
                return
            op.on_shift = {"on": True, "вкл": True, "off": False, "выкл": False}.get(arg.lower(), not op.on_shift)
            await session.commit()
            state = op.on_shift
        await self._send(
            chat_id,
            "🟢 Вы на смене: новые заявки будут приходить сюда."
            if state
            else "⚪ Смена закрыта: новые заявки приходить не будут (ваши текущие остаются за вами).",
        )

    async def _operator_leads(self, chat_id: int, user: dict[str, Any]) -> None:
        async with self.session_factory() as session:
            op = await operator_by_user(session, user.get("id"))
            if op is None:
                await self._send(chat_id, "Команда для операторов. Регистрация: /operator &lt;код&gt;.")
                return
            leads = (
                await session.scalars(
                    select(Lead)
                    .where(Lead.assigned_operator_id == op.id, Lead.status.not_in([s.value for s in TERMINAL]))
                    .order_by(Lead.created_at)
                )
            ).all()
        if not leads:
            await self._send(
                chat_id, "У вас нет заявок в работе." + ("" if op.on_shift else " Смена закрыта (/smena).")
            )
            return
        lines = [
            f"<b>{html.escape(lead.number)}</b> — {html.escape(status_label(lead.status))} — "
            f"{html.escape(lead.name or '')} {html.escape(format_phone(lead.phone))}"
            for lead in leads
        ]
        await self._send(chat_id, "Ваши заявки в работе:\n" + "\n".join(lines))

    async def _relay_operator_reply(self, chat_id: int, reply_to: int, text: str, user: dict[str, Any]) -> bool:
        """An operator replied to a relayed message or a lead card → deliver to the website chat / client bot."""
        operator_name = str(user.get("first_name") or "Оператор")[:40]
        async with self.session_factory() as session:
            relay = await session.scalar(
                select(TgRelay).where(TgRelay.chat_id == chat_id, TgRelay.message_id == reply_to)
            )
            lead: Lead | None = None
            chat_session_id = relay.chat_session_id if relay else None
            client_chats: list[int] = [relay.client_chat_id] if relay and relay.client_chat_id else []
            if relay is not None and relay.lead_id is not None:
                lead = await session.get(Lead, relay.lead_id)
            if relay is None:
                card = await session.scalar(
                    select(OperatorCard).where(OperatorCard.chat_id == chat_id, OperatorCard.message_id == reply_to)
                )
                if card is None:
                    return False
                lead = await session.scalar(
                    select(Lead).where(Lead.id == card.lead_id).options(selectinload(Lead.channels))
                )
                if lead is None:
                    return False
                chat_session_id = lead.chat_session_id
                client_chats = [int(c.address) for c in lead.channels if c.kind == "telegram"]
            delivered = []
            if chat_session_id is not None and await self.live_chat.post_operator_message(
                session, chat_session_id, text, operator_name
            ):
                delivered.append("на сайт")
            if lead is not None:
                for client_chat in client_chats:
                    enqueue_operator_reply(session, lead, client_chat, text, operator_name)
                if client_chats:
                    delivered.append("в Telegram клиента")
            await session.commit()
            phone = format_phone(lead.phone) if lead is not None else None
        self.on_commit()
        if delivered:
            await self._send(chat_id, "✅ Ответ отправлен " + " и ".join(delivered) + ".", reply_to_message_id=reply_to)
        else:
            await self._send(
                chat_id,
                "У клиента нет Telegram и чата на сайте — позвоните ему"
                + (f": {html.escape(phone)}" if phone else "."),
                reply_to_message_id=reply_to,
            )
        return True

    # --- clients -------------------------------------------------------------------------------------
    async def _client(self, session: AsyncSession, chat_id: int, user: dict[str, Any]) -> TgClient:
        client = await session.get(TgClient, chat_id)
        if client is None:
            client = TgClient(chat_id=chat_id, tg_user_id=int(user.get("id") or chat_id))
            session.add(client)
        client.username = user.get("username") or None
        return client

    @staticmethod
    async def _bind(session: AsyncSession, lead: Lead, chat_id: int) -> bool:
        exists = await session.scalar(
            select(ClientChannel.id).where(
                ClientChannel.lead_id == lead.id,
                ClientChannel.kind == "telegram",
                ClientChannel.address == str(chat_id),
            )
        )
        if exists is None:
            session.add(ClientChannel(lead_id=lead.id, kind="telegram", address=str(chat_id)))
            return True
        return False

    @staticmethod
    async def _client_leads(session: AsyncSession, chat_id: int, *, active_only: bool) -> list[Lead]:
        query = (
            select(Lead)
            .join(ClientChannel, ClientChannel.lead_id == Lead.id)
            .where(ClientChannel.kind == "telegram", ClientChannel.address == str(chat_id))
        )
        if active_only:
            query = query.where(Lead.status.not_in([s.value for s in TERMINAL]))
        return list((await session.scalars(query.order_by(Lead.created_at.desc()).limit(MAX_LISTED))).all())

    async def _start(self, chat_id: int, user: dict[str, Any], token: str) -> None:
        bound_numbers: list[str] = []
        async with self.session_factory() as session:
            await self._client(session, chat_id, user)
            if token:
                lead = await session.scalar(select(Lead).where(Lead.public_token == token[:64]))
                if lead is None:
                    await session.commit()
                    await self._send(
                        chat_id,
                        "Заявка по этой ссылке не найдена. Проверьте ссылку на сайте.",
                        reply_keyboard=CLIENT_KEYBOARD,
                    )
                    return
                await self._bind(session, lead, chat_id)
                bound_numbers.append(lead.number)
                tracking = self.settings.tracking_url(lead.public_token)
                current = status_label(lead.status)
            elif username := user.get("username"):
                # The client typed this @username in the form → subscribe automatically.
                since = utcnow() - timedelta(days=AUTO_BIND_DAYS)
                leads = (
                    await session.scalars(
                        select(Lead).where(
                            func.lower(Lead.telegram_username) == str(username).lower(),
                            Lead.created_at >= since,
                            Lead.status.not_in([s.value for s in TERMINAL]),
                        )
                    )
                ).all()
                for lead in leads:
                    await self._bind(session, lead, chat_id)
                    bound_numbers.append(lead.number)
            await session.commit()
        if token:
            logger.info("telegram_bound", extra={"lead_number": bound_numbers[0], "via": "deep_link"})
            text = (
                f"Готово! Будем присылать сюда статус заявки <b>{html.escape(bound_numbers[0])}</b>.\n"
                f"Сейчас: {html.escape(current)}."
            )
            if is_public_url(tracking):
                await self._send(chat_id, text, buttons=[[InlineButton("Открыть заявку", url=tracking)]])
            else:  # dev: Telegram rejects localhost URLs in buttons
                await self._send(chat_id, f"{text}\nЗаявка: {html.escape(tracking)}")
            await self._send(
                chat_id,
                "Вопрос по заявке можно написать прямо сюда. Меню — кнопками ниже.",
                reply_keyboard=CLIENT_KEYBOARD,
            )
            return
        await self._send(chat_id, CLIENT_HELP, reply_keyboard=CLIENT_KEYBOARD)
        if bound_numbers:
            logger.info("telegram_bound", extra={"via": "username", "count": len(bound_numbers)})
            await self._send(
                chat_id,
                "Нашёл ваши заявки по Telegram-нику из формы: "
                + ", ".join(html.escape(n) for n in bound_numbers)
                + ". Статусы будут приходить сюда.",
            )
            await self._list_client_leads(chat_id)

    async def _on_contact(self, chat_id: int, user: dict[str, Any], contact: dict[str, Any]) -> None:
        # Telegram attaches user_id only to the sender's own contact shared via the button.
        if contact.get("user_id") != user.get("id"):
            await self._send(
                chat_id,
                "Отправьте, пожалуйста, свой номер кнопкой «📱 Поделиться номером».",
                reply_keyboard=CLIENT_KEYBOARD,
            )
            return
        try:
            phone = normalize_phone(str(contact.get("phone_number", "")))
        except InvalidPhone:
            await self._send(chat_id, "Бот работает с российскими номерами +7. Позвоните нам — поможем.")
            return
        async with self.session_factory() as session:
            client = await self._client(session, chat_id, user)
            client.phone, client.phone_verified_at = phone, utcnow()
            leads = (
                await session.scalars(
                    select(Lead).where(Lead.phone == phone, Lead.status.not_in([s.value for s in TERMINAL]))
                )
            ).all()
            for lead in leads:
                await self._bind(session, lead, chat_id)
            await session.commit()
            numbers = [lead.number for lead in leads]
        logger.info("telegram_contact_shared", extra={"leads": len(numbers)})
        if not numbers:
            await self._send(
                chat_id,
                f"Активных заявок на номер {html.escape(mask_phone(phone))} не нашёл. "
                "Оставьте заявку на сайте — статус будет приходить сюда.",
            )
            return
        await self._send(
            chat_id, f"Номер подтверждён ✅ Нашёл заявки: {', '.join(numbers)}. Статусы будут приходить сюда."
        )
        await self._list_client_leads(chat_id)

    async def _list_client_leads(self, chat_id: int) -> None:
        async with self.session_factory() as session:
            leads = await self._client_leads(session, chat_id, active_only=False)
        if not leads:
            await self._send(
                chat_id,
                "Пока не вижу ваших заявок. Нажмите «🔎 Найти заявку» — найду по телефону и номеру заявки.",
                reply_keyboard=CLIENT_KEYBOARD,
            )
            return
        for lead in leads:
            await self._send(chat_id, self._lead_line(lead), buttons=self._client_buttons(lead))

    @staticmethod
    def _lead_line(lead: Lead) -> str:
        return (
            f"<b>{html.escape(lead.number)}</b> · {html.escape(LEAD_TYPE_LABELS[LeadType(lead.type)])}\n"
            f"Статус: {html.escape(status_label(lead.status))}"
        )

    @staticmethod
    def _client_buttons(lead: Lead) -> list[list[InlineButton]]:
        hexid = lead.id.hex
        row = [InlineButton("🔄 Статус", callback_data=f"cl:s:{hexid}")]
        if LeadStatus(lead.status) not in TERMINAL:
            row.append(InlineButton("❓ Вопрос", callback_data=f"cl:q:{hexid}"))
        rows = [row]
        if lead.status in CLIENT_CANCELLABLE:
            rows.append([InlineButton("✖ Отменить заявку", callback_data=f"cl:x:{hexid}")])
        return rows

    @staticmethod
    def _typed_phone(text: str) -> str | None:
        """The whole message is a phone number (not a question that happens to contain one)."""
        if len(text) > 25 or sum(ch.isdigit() for ch in text) not in (10, 11):
            return None
        try:
            return normalize_phone(text)
        except InvalidPhone:
            return None

    async def _find_lead(self, chat_id: int, user: dict[str, Any], number: str) -> None:
        """Typed phone + lead number → bind. Rate-limited; the same answer for «no such lead» and «wrong phone»."""
        try:
            self.limiter.hit(f"tgfind:{chat_id}", FIND_ATTEMPTS_PER_HOUR, 3600)
        except RateLimited:
            await self._send(chat_id, "Слишком много попыток. Попробуйте через час или позвоните нам.")
            return
        async with self.session_factory() as session:
            client = await self._client(session, chat_id, user)
            lead = await session.scalar(select(Lead).where(Lead.number == number, Lead.phone == client.pending_phone))
            if lead is None:
                await session.commit()
                logger.info("telegram_find_lead_miss")
                await self._send(
                    chat_id,
                    f"Не нашёл заявку {html.escape(number)} с этим телефоном. Проверьте номер заявки "
                    "или нажмите «🔎 Найти заявку», чтобы ввести телефон заново.",
                )
                return
            await self._bind(session, lead, chat_id)
            client.phone, client.pending_phone = client.pending_phone, None
            await session.commit()
        logger.info("telegram_bound", extra={"lead_number": number, "via": "phone_and_number"})
        await self._send(
            chat_id,
            f"Нашёл заявку {html.escape(number)} ✅ Статусы будут приходить сюда.",
            reply_keyboard=CLIENT_KEYBOARD,
        )
        await self._list_client_leads(chat_id)

    async def _client_text(self, chat_id: int, user: dict[str, Any], text: str) -> None:
        """Free text from a client: phone / lead number for «Найти заявку», otherwise a question to operators."""
        if phone := self._typed_phone(text):
            async with self.session_factory() as session:
                client = await self._client(session, chat_id, user)
                client.pending_phone = phone
                await session.commit()
            await self._send(
                chat_id,
                f"Телефон {html.escape(mask_phone(phone))} ✅ Теперь напишите номер заявки, "
                "например <code>GS-1003</code>.",
            )
            return
        if match := _LEAD_NUMBER.match(text):
            async with self.session_factory() as session:
                pending = (await self._client(session, chat_id, user)).pending_phone
                await session.commit()
            if pending is None:
                await self._send(chat_id, "Сначала напишите телефон из заявки, затем её номер. " + ASK_PHONE)
            else:
                await self._find_lead(chat_id, user, f"GS-{match.group(1)}")
            return
        async with self.session_factory() as session:
            client = await self._client(session, chat_id, user)
            leads = await self._client_leads(session, chat_id, active_only=True)
            lead = next((x for x in leads if x.id == client.pending_question_lead_id), None)
            if lead is None and len(leads) == 1:
                lead = leads[0]
            if lead is None:
                await session.commit()
                if leads:
                    await self._send(chat_id, "По какой заявке вопрос? Нажмите «❓ Вопрос» у нужной заявки.")
                    for x in leads:
                        await self._send(chat_id, self._lead_line(x), buttons=self._client_buttons(x))
                elif await operator_by_user(session, user.get("id")) is not None:
                    await self._send(
                        chat_id,
                        "Чтобы ответить клиенту, ответьте реплаем на его сообщение или "
                        "на карточку заявки. /help — подсказка.",
                    )
                else:
                    await self._send(
                        chat_id,
                        "Не вижу ваших активных заявок. Нажмите «🔎 Найти заявку» или оставьте заявку на сайте.",
                        reply_keyboard=CLIENT_KEYBOARD,
                    )
                return
            client.pending_question_lead_id = lead.id
            sent = await enqueue_client_message(session, lead, chat_id, text, self.routing)
            await session.commit()
            number = lead.number
        self.on_commit()
        if sent:
            await self._send(chat_id, f"Передал вопрос по заявке {html.escape(number)} оператору. Ответ придёт сюда.")
        else:
            await self._send(chat_id, "Сейчас операторы не на связи в Telegram. Позвоните нам — ответим сразу.")

    # --- callbacks -------------------------------------------------------------------------------------
    async def _on_callback(self, cq: dict[str, Any]) -> None:
        data = str(cq.get("data") or "")
        message = cq.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        user = cq.get("from") or {}
        parts = data.split(":")
        try:
            if parts[0] == "cl" and len(parts) == 3:
                await self._client_callback(cq["id"], chat_id, parts[1], uuid.UUID(hex=parts[2]))
            elif parts[0] == "tk" and len(parts) == 2:
                await self._take(cq["id"], chat_id, user, uuid.UUID(hex=parts[1]))
            elif parts[0] == "st" and len(parts) == 3 and parts[2] in {s.value for s in STATUS_LABELS}:
                await self._operator_status(cq["id"], chat_id, user, uuid.UUID(hex=parts[1]), parts[2])
            else:
                raise ValueError(data)
        except ValueError:
            await self.client.answer_callback_query(cq["id"], "Неизвестная команда")

    async def _take(self, cq_id: str, chat_id: int | None, user: dict[str, Any], lead_id: uuid.UUID) -> None:
        """«Беру»: atomic first-wins assignment, then status → accepted."""
        is_group = chat_id is not None and chat_id == self.routing.operator_tg_chat_id
        async with self.session_factory() as session:
            op = await operator_by_user(session, user.get("id"))
            if op is None and not is_group:
                await self.client.answer_callback_query(cq_id, "Недоступно")
                return
            name = op.name if op else str(user.get("first_name") or user.get("username") or "оператор")
            taken = await session.execute(
                update(Lead)
                .where(Lead.id == lead_id, Lead.assignee_name.is_(None), Lead.status == LeadStatus.NEW.value)
                .values(assigned_operator_id=op.id if op else None, assignee_name=name[:120])
            )
            if getattr(taken, "rowcount", 0) != 1:
                current = await session.scalar(select(Lead.assignee_name).where(Lead.id == lead_id))
                await session.rollback()
                who = current or "другой оператор"
                await self.client.answer_callback_query(cq_id, f"Заявку уже взял {who}")
                return
            actor = f"telegram:{user.get('username') or user.get('id')}"
            try:
                lead = await change_status(
                    session, lead_id, LeadStatus.ACCEPTED.value, actor=actor, routing=self.routing
                )
            except AppError as exc:
                await session.rollback()
                await self.client.answer_callback_query(cq_id, exc.message)
                return
            await session.commit()
            number = lead.number
        self.on_commit()
        logger.info("lead_taken", extra={"lead_number": number, "by_operator": op is not None})
        await self.client.answer_callback_query(cq_id, f"Заявка {number} ваша")

    async def _operator_status(
        self, cq_id: str, chat_id: int | None, user: dict[str, Any], lead_id: uuid.UUID, target: str
    ) -> None:
        is_group = chat_id is not None and chat_id == self.routing.operator_tg_chat_id
        async with self.session_factory() as session:
            op = await operator_by_user(session, user.get("id"))
            lead = await session.get(Lead, lead_id)
            if lead is None or (op is None and not is_group):
                await self.client.answer_callback_query(cq_id, "Недоступно")
                return
            if not is_group and lead.assigned_operator_id not in (None, op.id if op else None):
                await self.client.answer_callback_query(cq_id, f"Заявку ведёт {lead.assignee_name}")
                return
            actor = f"telegram:{user.get('username') or user.get('id')}"
            try:
                await change_status(session, lead_id, target, actor=actor, routing=self.routing)
            except AppError as exc:
                await self.client.answer_callback_query(cq_id, exc.message)
                return
            await session.commit()
        self.on_commit()
        await self.client.answer_callback_query(cq_id, f"Статус: {STATUS_LABELS[LeadStatus(target)]}")

    async def _client_callback(self, cq_id: str, chat_id: int | None, action: str, lead_id: uuid.UUID) -> None:
        if chat_id is None:
            return
        async with self.session_factory() as session:
            lead = await session.scalar(
                select(Lead)
                .join(ClientChannel, ClientChannel.lead_id == Lead.id)
                .where(Lead.id == lead_id, ClientChannel.kind == "telegram", ClientChannel.address == str(chat_id))
                .options(selectinload(Lead.history))
            )
            if lead is None:  # only leads bound to this chat (deep link / verified phone / @username)
                await self.client.answer_callback_query(cq_id, "Заявка не найдена")
                return
            if action == "s":
                await self.client.answer_callback_query(cq_id)
                history = "\n".join(
                    f"• {h.created_at:%d.%m %H:%M} UTC — {html.escape(status_label(h.to_status))}"
                    for h in lead.history[-4:]
                )
                tracking = self.settings.tracking_url(lead.public_token)
                link = f"\n\nПодробнее: {html.escape(tracking)}"
                await self._send(
                    chat_id, f"{self._lead_line(lead)}\n\n{history}{link}", buttons=self._client_buttons(lead)
                )
            elif action == "q":
                client = await session.get(TgClient, chat_id)
                if client is None:
                    client = TgClient(chat_id=chat_id, tg_user_id=chat_id)
                    session.add(client)
                client.pending_question_lead_id = lead.id
                await session.commit()
                await self.client.answer_callback_query(cq_id)
                await self._send(chat_id, f"Напишите вопрос по заявке {html.escape(lead.number)} одним сообщением.")
            elif action == "x":
                await self.client.answer_callback_query(cq_id)
                if lead.status not in CLIENT_CANCELLABLE:
                    await self._send(
                        chat_id,
                        "Мастер уже выехал или работы начались — отменить можно только по телефону. Позвоните нам.",
                    )
                    return
                await self._send(
                    chat_id,
                    f"Отменить заявку {html.escape(lead.number)}?",
                    buttons=[
                        [
                            InlineButton("Да, отменить", callback_data=f"cl:y:{lead.id.hex}"),
                            InlineButton("Нет", callback_data=f"cl:s:{lead.id.hex}"),
                        ]
                    ],
                )
            elif action == "y":
                if lead.status not in CLIENT_CANCELLABLE:
                    await self.client.answer_callback_query(cq_id, "Уже нельзя отменить — позвоните нам")
                    return
                try:
                    lead = await change_status(
                        session,
                        lead.id,
                        LeadStatus.CANCELLED.value,
                        actor="client:telegram",
                        routing=self.routing,
                        comment="Отменено клиентом в Telegram",
                    )
                except AppError as exc:
                    await self.client.answer_callback_query(cq_id, exc.message)
                    return
                await enqueue_client_message(
                    session, lead, chat_id, "Клиент отменил заявку в боте.", self.routing, kind="cancelled"
                )
                await session.commit()
                self.on_commit()
                await self.client.answer_callback_query(cq_id, "Заявка отменена")
            else:
                await self.client.answer_callback_query(cq_id, "Неизвестная команда")

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
            for update_ in updates:
                self._offset = int(update_["update_id"]) + 1
                try:
                    await self.handle_update(update_)
                except Exception:
                    logger.exception("telegram_update_failed")
