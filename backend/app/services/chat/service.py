"""Chat assistant: LLM (OpenRouter + tools, streamed) with deterministic FAQ fallback and operator handoff.

Modes per turn, in order:
  1. session is with an operator (live chat, level B) → forward the message to operators' Telegram;
  2. we are waiting for a phone number after a handoff request → create the `chat_handoff` lead;
  3. the user explicitly asks for a human → handoff (no LLM involved, no persuasion);
  4. LLM available and within budget → LLM with tools;
  5. otherwise (no key, budget exhausted, provider down) → rule-based FAQ.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import AppError, NotFound, RateLimited, ValidationFailed
from app.core.ratelimit import RateLimiter
from app.core.security import hash_ip
from app.db.base import utcnow
from app.db.models import ChatMessage, ChatSession, Lead, PriceVehicleType
from app.domain.phone import extract_phone, mask_phone
from app.domain.topics import SUGGESTED_REPLIES, Topic, asks_for_operator, detect_topic
from app.integrations.geocoder.dgis import Geocoder
from app.integrations.llm.base import (
    ChatRequest,
    LLMProvider,
    LLMUnavailable,
    TextDelta,
    ToolCallsRequested,
    Usage,
)
from app.services.calculator import create_estimate, estimate_to_dict
from app.services.chat.budget import LlmBudget
from app.services.chat.knowledge import KnowledgeBase, faq_answer
from app.services.chat.live import LiveChatHub
from app.services.chat.prompts import AFFIRMATIVE, OPERATOR_OFFER_MARKERS, SYSTEM_PROMPT
from app.services.chat.tools import ChatTools, tool_definitions
from app.services.leads import LeadService, RequestContext, created_response
from app.services.notifications import Routing, enqueue_chat_forward
from app.services.operators import recipients_for

logger = logging.getLogger(__name__)

Event = dict[str, Any]
MAX_TOOL_ROUNDS = 3


@dataclass
class TurnContext:
    db: AsyncSession
    chat: ChatSession
    kb: KnowledgeBase
    text: str
    topic: Topic
    user_message: ChatMessage
    ip: str | None
    consent_now: bool = False
    topic_override: str | None = None
    handoff_text: str | None = None
    extra_events: list[Event] = field(default_factory=list)


def _session_dict(chat: ChatSession) -> dict[str, Any]:
    return {
        "session_id": str(chat.id),
        "status": chat.status,
        "topic": chat.topic,
        "has_phone": chat.phone is not None,
        "consent": chat.consent_at is not None,
        "lead_id": str(chat.lead_id) if chat.lead_id else None,
    }


def message_dict(m: ChatMessage) -> dict[str, Any]:
    return {
        "id": m.id,
        "role": m.role,
        "text": m.content,
        "topic": m.topic,
        "mode": m.mode,
        "suggested_replies": m.suggested_replies or [],
        "created_at": m.created_at.isoformat(),
        **({"operator_name": m.meta.get("operator_name")} if m.role == "operator" else {}),
    }


class ChatService:
    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        leads: LeadService,
        llm: LLMProvider | None,
        budget: LlmBudget,
        live: LiveChatHub,
        limiter: RateLimiter,
        geocoder: Geocoder | None = None,
        on_commit: Callable[[], None] = lambda: None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.leads = leads
        self.llm = llm
        self.budget = budget
        self.live = live
        self.limiter = limiter
        self.geocoder = geocoder
        self.on_commit = on_commit
        self.routing = Routing.from_settings(settings)

    async def live_chat_available(self, db: AsyncSession) -> bool:
        """Live chat works when someone can receive messages in Telegram: operators on shift or the group."""
        if not self.routing.telegram_enabled:
            return False
        return bool(await recipients_for(db, self.routing.operator_tg_chat_id))

    # --- sessions -------------------------------------------------------------------------------
    async def create_session(self, *, consent: bool, name: str | None, ip: str | None) -> dict[str, Any]:
        async with self.session_factory() as db:
            kb = await KnowledgeBase.load(db)
            chat = ChatSession(
                ip_hash=hash_ip(ip, self.settings.secret_key.get_secret_value()),
                name=(name or "").strip()[:120] or None,
            )
            if consent:
                chat.consent_at, chat.consent_version = utcnow(), kb.site.consent_version
            db.add(chat)
            await db.flush()
            greeting = (
                f"Здравствуйте! Я помощник {kb.site.company_name}. Помогу с ремонтом, ценами, "
                "выездом мастера и запчастями. Если нужен живой человек — просто напишите «оператор»."
            )
            msg = ChatMessage(
                session_id=chat.id,
                role="assistant",
                content=greeting,
                topic="other",
                mode="rule",
                suggested_replies=SUGGESTED_REPLIES[Topic.OTHER],
            )
            db.add(msg)
            await db.commit()
            return {
                **_session_dict(chat),
                "llm_enabled": self.llm is not None,
                "live_chat_available": await self.live_chat_available(db),
                "messages": [message_dict(msg)],
            }

    async def _get_chat(self, db: AsyncSession, session_id: uuid.UUID) -> ChatSession:
        chat = await db.get(ChatSession, session_id)
        if chat is None:
            raise NotFound("Сессия чата не найдена")
        return chat

    async def get_messages(self, session_id: uuid.UUID, after_id: int | None = None) -> dict[str, Any]:
        async with self.session_factory() as db:
            chat = await self._get_chat(db, session_id)
            query = select(ChatMessage).where(ChatMessage.session_id == session_id, ChatMessage.role != "system")
            if after_id:
                query = query.where(ChatMessage.id > after_id)
            rows = await db.scalars(query.order_by(ChatMessage.id).limit(200))
            return {**_session_dict(chat), "messages": [message_dict(m) for m in rows]}

    # --- a turn ------------------------------------------------------------------------------------
    async def start_turn(self, session_id: uuid.UUID, text: str, *, consent: bool, ip: str | None) -> TurnContext:
        """Validate and store the user message. Errors here become normal JSON error responses."""
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text or "").strip()
        if not text:
            raise ValidationFailed("Пустое сообщение", fields={"text": "Напишите сообщение"})
        if len(text) > self.settings.chat_max_message_chars:
            raise ValidationFailed(
                "Слишком длинное сообщение",
                fields={"text": f"Не длиннее {self.settings.chat_max_message_chars} символов"},
            )
        ip_key = hash_ip(ip, self.settings.secret_key.get_secret_value()) or "unknown"
        self.limiter.hit(f"chat:ip:{ip_key}", self.settings.chat_messages_per_ip_per_minute, 60)

        db = self.session_factory()
        try:
            chat = await self._get_chat(db, session_id)
            if chat.status == "closed":
                raise AppError("Диалог завершён. Начните новый чат.", code="chat_closed", status_code=409)
            if chat.user_message_count >= self.settings.chat_max_messages_per_session:
                raise RateLimited(
                    "Лимит сообщений в этом чате исчерпан. Позвоните нам или оставьте заявку.", code="chat_limit"
                )
            kb = await KnowledgeBase.load(db)
            if consent and chat.consent_at is None:
                chat.consent_at, chat.consent_version = utcnow(), kb.site.consent_version
            topic = detect_topic(text, Topic(chat.topic) if chat.topic in Topic else None)
            chat.topic = topic.value
            chat.user_message_count += 1
            message = ChatMessage(session_id=chat.id, role="user", content=text, topic=topic.value)
            db.add(message)
            await db.commit()
            return TurnContext(
                db=db, chat=chat, kb=kb, text=text, topic=topic, user_message=message, ip=ip, consent_now=consent
            )
        except Exception:
            await db.close()
            raise

    async def run_turn(self, ctx: TurnContext) -> AsyncIterator[Event]:
        """Produce SSE events for one user message. Never raises: errors become an `error` event."""
        try:
            yield {
                "event": "meta",
                "data": {
                    "topic": ctx.topic.value,
                    "session_status": ctx.chat.status,
                    "user_message_id": ctx.user_message.id,
                },
            }
            if ctx.chat.awaiting_phone and (phone := extract_phone(ctx.text)):
                async for ev in self._handoff_with_phone(ctx, phone):
                    yield ev
                return
            if ctx.chat.status in ("waiting_operator", "operator") and not await self._operator_wait_expired(ctx):
                async for ev in self._forward_to_operator(ctx):
                    yield ev
                return
            if await self._operator_requested(ctx):
                text, events = await self.request_operator(ctx, reason="user_request")
                for ev in events:
                    yield ev
                async for ev in self._finish(ctx, text, mode="rule", emit_text=True):
                    yield ev
                return
            if self.llm is not None and await self.budget.can_spend():
                streamed = False
                try:
                    async for ev in self._llm_turn(ctx):
                        streamed = streamed or ev["event"] == "delta"
                        yield ev
                    return
                except LLMUnavailable as exc:
                    logger.warning("llm_unavailable_fallback_faq", extra={"reason": str(exc)[:200]})
                    if streamed:
                        yield {"event": "reset", "data": {}}
            async for ev in self._faq_turn(ctx):
                yield ev
        except Exception:
            logger.exception("chat_turn_failed")
            yield {
                "event": "error",
                "data": {"code": "internal_error", "message": f"Что-то пошло не так. Позвоните нам: {ctx.kb.phone}"},
            }
        finally:
            await ctx.db.close()

    async def _finish(
        self,
        ctx: TurnContext,
        text: str,
        *,
        mode: str,
        emit_text: bool,
        suggested: list[str] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> AsyncIterator[Event]:
        override = ctx.topic_override
        topic = Topic(override) if override is not None and override in Topic else ctx.topic
        replies = suggested if suggested is not None else SUGGESTED_REPLIES[topic]
        if ctx.chat.status in ("waiting_operator", "operator") or ctx.chat.awaiting_phone:
            replies = []
        if emit_text and text:
            yield {"event": "delta", "data": {"text": text}}
        meta = dict(meta or {})
        if mode in ("llm", "faq") and any(m in text.lower() for m in OPERATOR_OFFER_MARKERS):
            meta["offered_operator"] = True
        message = ChatMessage(
            session_id=ctx.chat.id,
            role="assistant",
            content=text,
            topic=topic.value,
            mode=mode,
            suggested_replies=replies,
            meta=meta,
        )
        ctx.db.add(message)
        await ctx.db.commit()
        yield {
            "event": "done",
            "data": {
                "message_id": message.id,
                "text": text,
                "topic": topic.value,
                "suggested_replies": replies,
                "mode": mode,
                "session_status": ctx.chat.status,
            },
        }

    # --- FAQ mode ------------------------------------------------------------------------------------
    async def _faq_turn(self, ctx: TurnContext) -> AsyncIterator[Event]:
        estimate: dict[str, Any] | None = None
        brand, work = ctx.kb.find_brand(ctx.text), ctx.kb.find_work_type(ctx.text)
        if brand is not None and work is not None and ctx.topic in (Topic.PRICING, Topic.SERVICES, Topic.DISPATCH):
            async with self.session_factory() as db:
                row = await create_estimate(db, brand=brand.slug, work_type=work)
                await db.commit()
            estimate = estimate_to_dict(row, ctx.kb.site.pricing_rules().disclaimer)
            ctx.topic_override = Topic.PRICING.value
        answer = faq_answer(ctx.kb, ctx.text, Topic(ctx.topic_override or ctx.topic), estimate)
        if answer.estimate:
            yield {"event": "estimate", "data": answer.estimate}
        for action in answer.actions:
            yield {"event": "action", "data": action}
        async for ev in self._finish(ctx, answer.text, mode="faq", emit_text=True, suggested=answer.suggested_replies):
            yield ev

    # --- LLM mode ------------------------------------------------------------------------------------
    async def _history(self, ctx: TurnContext) -> list[dict[str, Any]]:
        rows = list(
            (
                await ctx.db.scalars(
                    select(ChatMessage)
                    .where(ChatMessage.session_id == ctx.chat.id, ChatMessage.role != "system")
                    .order_by(ChatMessage.id.desc())
                    .limit(self.settings.chat_history_window)
                )
            ).all()
        )
        history = []
        for m in reversed(rows):
            if m.role == "user":
                history.append({"role": "user", "content": m.content})
            elif m.role == "operator":
                history.append({"role": "assistant", "content": f"[Оператор] {m.content}"})
            elif m.content:
                history.append({"role": "assistant", "content": m.content})
        return history

    async def _llm_turn(self, ctx: TurnContext) -> AsyncIterator[Event]:
        assert self.llm is not None
        works = sorted(ctx.kb.work_types)
        vtypes = list((await ctx.db.scalars(select(PriceVehicleType.slug))).all())
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT.format(facts=ctx.kb.prompt_facts())},
            *await self._history(ctx),
        ]
        tools = ChatTools(self, ctx, self.geocoder)
        definitions = tool_definitions(works, vtypes)
        full_text = ""
        for round_no in range(MAX_TOOL_ROUNDS):
            if round_no and not await self.budget.can_spend():
                break
            round_text, calls, usage = "", None, None
            request = ChatRequest(messages, definitions, self.settings.llm_max_tokens, self.settings.llm_temperature)
            try:
                async for event in self.llm.stream(request):
                    if isinstance(event, TextDelta):
                        round_text += event.text
                        yield {"event": "delta", "data": {"text": event.text}}
                    elif isinstance(event, ToolCallsRequested):
                        calls = event.calls
                    elif isinstance(event, Usage):
                        usage = event
            finally:
                await self.budget.record(usage)
            full_text += round_text
            if not calls:
                break
            messages.append(
                {
                    "role": "assistant",
                    "content": round_text or None,
                    "tool_calls": [
                        {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                        for c in calls
                    ],
                }
            )
            for call in calls:
                if call.name == "request_operator" and not await self._operator_requested(ctx):
                    outcome_result: dict[str, Any] = {
                        "error": "not_requested",
                        "message": "Клиент не просил оператора. Не передавай диалог; можно один раз предложить.",
                    }
                else:
                    outcome = await tools.execute(call.name, call.arguments)
                    for ev in outcome.events:
                        yield ev
                    outcome_result = outcome.result
                yield {"event": "tool", "data": {"name": call.name}}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(outcome_result, ensure_ascii=False, default=str),
                    }
                )
        text = full_text.strip()
        emit = False
        if not text:
            text = ctx.handoff_text or "Готово. Чем ещё помочь?"
            emit = True
        async for ev in self._finish(ctx, text, mode="llm", emit_text=emit):
            yield ev

    async def _operator_requested(self, ctx: TurnContext) -> bool:
        """Handoff only if the user asked for a human, or agreed to an offer the assistant just made."""
        if asks_for_operator(ctx.text):
            return True
        words = set(re.findall(r"\w+", ctx.text.lower()))
        if not words & set(AFFIRMATIVE) or len(ctx.text) > 60:
            return False
        last = await ctx.db.scalar(
            select(ChatMessage)
            .where(ChatMessage.session_id == ctx.chat.id, ChatMessage.role == "assistant")
            .order_by(ChatMessage.id.desc())
            .limit(1)
        )
        return bool(last and (last.meta or {}).get("offered_operator"))

    # --- handoff -------------------------------------------------------------------------------------
    async def request_operator(self, ctx: TurnContext, *, reason: str) -> tuple[str, list[Event]]:
        """Level A: create a `chat_handoff` lead (ask phone first if needed). Level B: live chat via Telegram."""
        chat = ctx.chat
        live = await self.live_chat_available(ctx.db)
        events: list[Event] = [{"event": "handoff", "data": {"status": "requested", "live_chat": live}}]
        if chat.lead_id and chat.status in ("waiting_operator", "operator"):
            return "Оператор уже получил ваш запрос и скоро свяжется с вами.", events
        chat.handoff_requested_at = utcnow()
        if live:
            chat.status = "waiting_operator"
        if chat.phone and chat.consent_at:
            text = await self._create_handoff_lead(ctx, events)
        else:
            chat.awaiting_phone = True
            text = (
                f"Конечно, передам ваш вопрос оператору. Напишите, пожалуйста, номер телефона — "
                f"оператор перезвонит. Или позвоните сами: {ctx.kb.phone}."
            )
            events.append(
                {"event": "action", "data": {"type": "phone_required", "consent_required": chat.consent_at is None}}
            )
        await ctx.db.commit()
        logger.info("chat_handoff_requested", extra={"reason": reason, "live": live})
        return text, events

    async def _handoff_with_phone(self, ctx: TurnContext, phone: str) -> AsyncIterator[Event]:
        ctx.chat.phone = phone
        if ctx.chat.consent_at is None:
            await ctx.db.commit()
            yield {"event": "action", "data": {"type": "consent_required"}}
            async for ev in self._finish(
                ctx,
                "Чтобы оператор мог перезвонить, отметьте согласие на обработку персональных данных "
                "под полем ввода и отправьте номер ещё раз.",
                mode="rule",
                emit_text=True,
            ):
                yield ev
            return
        events: list[Event] = []
        text = await self._create_handoff_lead(ctx, events)
        await ctx.db.commit()
        for ev in events:
            yield ev
        async for ev in self._finish(ctx, text, mode="rule", emit_text=True):
            yield ev

    async def _create_handoff_lead(self, ctx: TurnContext, events: list[Event]) -> str:
        chat = ctx.chat
        assert chat.phone is not None
        rows = (
            await ctx.db.scalars(
                select(ChatMessage).where(ChatMessage.session_id == chat.id).order_by(ChatMessage.id.desc()).limit(30)
            )
        ).all()
        transcript = "\n".join(
            f"{'Клиент' if m.role == 'user' else 'Оператор' if m.role == 'operator' else 'Бот'}: {m.content}"
            for m in reversed(rows)
            if m.content
        )
        lead = await self.leads.create_chat_handoff(
            ctx.db,
            chat_session_id=chat.id,
            phone=chat.phone,
            name=chat.name,
            transcript=transcript,
            topic=chat.topic,
            consent_at=chat.consent_at,
            consent_version=chat.consent_version,
        )
        chat.lead_id = lead.id
        chat.awaiting_phone = False
        live = await self.live_chat_available(ctx.db)
        if not live:
            chat.status = "bot"  # level A only: the operator calls back, the bot keeps helping meanwhile
        await ctx.db.commit()
        self.on_commit()
        body = created_response(lead, self.settings)
        events.append({"event": "action", "data": {"type": "lead_created", "lead": body}})
        events.append(
            {
                "event": "handoff",
                "data": {"status": chat.status, "lead_number": lead.number, "live_chat": live},
            }
        )
        text = (
            f"Передал ваш запрос оператору — заявка {lead.number}. Перезвоним на номер "
            f"{mask_phone(chat.phone)} в течение ~{body['callback_eta_minutes']} минут."
        )
        if live:
            text += " Можете писать сюда — оператор ответит в этом чате."
        return text

    async def handoff_by_button(
        self, session_id: uuid.UUID, *, phone: str | None, name: str | None, consent: bool, ip: str | None
    ) -> dict[str, Any]:
        """`POST /chat/sessions/{id}/handoff` — the "Позвать оператора" button."""
        db = self.session_factory()
        try:
            chat = await self._get_chat(db, session_id)
            kb = await KnowledgeBase.load(db)
            if consent and chat.consent_at is None:
                chat.consent_at, chat.consent_version = utcnow(), kb.site.consent_version
            if name:
                chat.name = name.strip()[:120]
            if phone:
                normalized = extract_phone(phone)
                if normalized is None:
                    raise ValidationFailed("Проверьте телефон", fields={"phone": "Формат +7 XXX XXX XX XX"})
                chat.phone = normalized
            if chat.phone and chat.consent_at is None:
                raise ValidationFailed("Нужно согласие", fields={"consent": "Отметьте согласие на обработку ПДн"})
            message = ChatMessage(session_id=chat.id, role="user", content="Позвать оператора", topic=chat.topic)
            db.add(message)
            await db.flush()
            ctx = TurnContext(
                db=db, chat=chat, kb=kb, text="Позвать оператора", topic=Topic(chat.topic), user_message=message, ip=ip
            )
            text, events = await self.request_operator(ctx, reason="button")
            done: list[Event] = [ev async for ev in self._finish(ctx, text, mode="rule", emit_text=False)]
            return {**_session_dict(chat), "message": text, "events": events + done}
        finally:
            await db.close()

    async def create_lead_from_chat(self, ctx: TurnContext, data: dict[str, Any]) -> dict[str, Any]:
        created = await self.leads.create_from_form(
            {**data, "consent": True, "source": "chatbot"}, [], RequestContext(ip=ctx.ip, user_agent="chatbot")
        )
        ctx.chat.lead_id = uuid.UUID(created.body["id"])
        ctx.chat.phone = ctx.chat.phone or extract_phone(str(data.get("phone", "")))
        await ctx.db.commit()
        return created.body

    # --- operator live chat (level B) ------------------------------------------------------------------
    async def _operator_wait_expired(self, ctx: TurnContext) -> bool:
        chat = ctx.chat
        if chat.status != "waiting_operator" or chat.handoff_requested_at is None:
            return False
        if utcnow() - chat.handoff_requested_at < timedelta(minutes=self.settings.chat_operator_wait_minutes):
            return False
        chat.status = "bot"
        await ctx.db.commit()
        return True

    async def _forward_to_operator(self, ctx: TurnContext) -> AsyncIterator[Event]:
        lead = await ctx.db.get(Lead, ctx.chat.lead_id) if ctx.chat.lead_id else None
        forwarded = await enqueue_chat_forward(ctx.db, ctx.user_message.id, self.routing, lead)
        await ctx.db.commit()
        self.on_commit()
        yield {
            "event": "done",
            "data": {
                "message_id": None,
                "text": "",
                "forwarded_to_operator": forwarded,
                "topic": ctx.topic.value,
                "suggested_replies": [],
                "mode": "operator",
                "session_status": ctx.chat.status,
            },
        }

    async def close(self, session_id: uuid.UUID) -> dict[str, Any]:
        async with self.session_factory() as db:
            chat = await self._get_chat(db, session_id)
            chat.status = "closed"
            await db.commit()
            return _session_dict(chat)
