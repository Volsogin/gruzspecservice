"""ORM models. Business rules live in `app.domain`; these are storage shapes only."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONType, utcnow


class Setting(Base):
    """Key/value site settings editable in the admin (contacts, stats, dispatch zone, ...)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONType)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str | None] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    def __str__(self) -> str:
        return self.key


class Service(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(120))
    short_description: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(32))
    form_type: Mapped[str] = mapped_column(String(32))
    prefill: Mapped[dict[str, Any]] = mapped_column(default=dict)
    items: Mapped[Any] = mapped_column(JSONType, default=list)
    icon: Mapped[str | None] = mapped_column(String(64))
    badge: Mapped[str | None] = mapped_column(String(64))
    is_24_7: Mapped[bool] = mapped_column(Boolean, default=False)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    def __str__(self) -> str:
        return self.title


class Counter(Base):
    """Named monotonic counters (human-readable lead numbers)."""

    __tablename__ = "counters"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[int] = mapped_column(BigInteger, default=0)


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (
        Index("ix_leads_status_created", "status", "created_at"),
        Index("ix_leads_phone_created", "phone", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    number: Mapped[str] = mapped_column(String(24), unique=True)
    public_token: Mapped[str] = mapped_column(String(64), unique=True)
    type: Mapped[str] = mapped_column(String(24), index=True)
    service_slug: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(16))
    email: Mapped[str | None] = mapped_column(String(254))
    telegram_username: Mapped[str | None] = mapped_column(String(64))
    vehicle_brand: Mapped[str | None] = mapped_column(String(64))
    vehicle_type: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    address: Mapped[str | None] = mapped_column(String(300))
    dispatch_zone: Mapped[str | None] = mapped_column(String(16))
    estimate_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("estimates.id", ondelete="SET NULL"))
    chat_session_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    source: Mapped[str] = mapped_column(String(16), default="form")
    status: Mapped[str] = mapped_column(String(16), default="new")
    status_changed_at: Mapped[datetime] = mapped_column(default=utcnow)
    consent_given: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_at: Mapped[datetime | None] = mapped_column()
    consent_version: Mapped[str | None] = mapped_column(String(32))
    assigned_operator_id: Mapped[int | None] = mapped_column(ForeignKey("operators.id", ondelete="SET NULL"))
    assignee_name: Mapped[str | None] = mapped_column(String(120))
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    attachments: Mapped[list[LeadAttachment]] = relationship(
        back_populates="lead", cascade="all, delete-orphan", order_by="LeadAttachment.created_at"
    )
    history: Mapped[list[LeadStatusHistory]] = relationship(
        back_populates="lead", cascade="all, delete-orphan", order_by="LeadStatusHistory.id"
    )
    channels: Mapped[list[ClientChannel]] = relationship(back_populates="lead", cascade="all, delete-orphan")
    estimate: Mapped[Estimate | None] = relationship()
    assigned_operator: Mapped[Operator | None] = relationship()

    def __str__(self) -> str:
        return f"{self.number} ({self.type})"


class LeadAttachment(Base):
    __tablename__ = "lead_attachments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    original_key: Mapped[str] = mapped_column(String(200))
    preview_key: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(32))
    size_bytes: Mapped[int] = mapped_column(Integer)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    lead: Mapped[Lead] = relationship(back_populates="attachments")


class LeadStatusHistory(Base):
    __tablename__ = "lead_status_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(16))
    to_status: Mapped[str] = mapped_column(String(16))
    actor: Mapped[str] = mapped_column(String(64))
    comment: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    lead: Mapped[Lead] = relationship(back_populates="history")


class ClientChannel(Base):
    """Where to deliver status updates for a lead: e-mail, bound Telegram chat, Max chat."""

    __tablename__ = "client_channels"
    __table_args__ = (UniqueConstraint("lead_id", "kind", "address", name="uq_client_channels_lead_kind_addr"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    address: Mapped[str] = mapped_column(String(254))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    lead: Mapped[Lead] = relationship(back_populates="channels")


class OutboxMessage(Base):
    """Transactional outbox: written in the same transaction as the business change."""

    __tablename__ = "outbox"
    __table_args__ = (Index("ix_outbox_status_next", "status", "next_attempt_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(48))
    channel: Mapped[str] = mapped_column(String(16))
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column()


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Estimate(Base):
    __tablename__ = "estimates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    brand: Mapped[str] = mapped_column(String(64))
    vehicle_type: Mapped[str | None] = mapped_column(String(64))
    work_type: Mapped[str] = mapped_column(String(64))
    urgent: Mapped[bool] = mapped_column(Boolean, default=False)
    onsite: Mapped[bool] = mapped_column(Boolean, default=False)
    price_from: Mapped[int] = mapped_column(Integer)
    breakdown: Mapped[Any] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class PriceWorkType(Base):
    __tablename__ = "price_work_types"

    slug: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    base_price: Mapped[int] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(String(300))
    is_onsite_service: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=100)

    def __str__(self) -> str:
        return self.title


class PriceBrand(Base):
    __tablename__ = "price_brands"

    slug: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(64))
    origin: Mapped[str] = mapped_column(String(32))
    coefficient: Mapped[float] = mapped_column(Float, default=1.0)
    aliases: Mapped[Any] = mapped_column(JSONType, default=list)
    sort_order: Mapped[int] = mapped_column(Integer, default=100)

    def __str__(self) -> str:
        return self.title


class PriceVehicleType(Base):
    __tablename__ = "price_vehicle_types"

    slug: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(64))
    coefficient: Mapped[float] = mapped_column(Float, default=1.0)
    sort_order: Mapped[int] = mapped_column(Integer, default=100)

    def __str__(self) -> str:
        return self.title


class Case(Base):
    """A completed job shown when a review is expanded ("до/после")."""

    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(160))
    vehicle_brand: Mapped[str] = mapped_column(String(64))
    vehicle_model: Mapped[str | None] = mapped_column(String(64))
    service_slug: Mapped[str | None] = mapped_column(String(64))
    location_mode: Mapped[str] = mapped_column(String(16), default="sto")
    problem: Mapped[str] = mapped_column(Text)
    work_done: Mapped[Any] = mapped_column(JSONType, default=list)
    duration_hours: Mapped[float | None] = mapped_column(Float)
    price_from: Mapped[int | None] = mapped_column(Integer)
    completed_on: Mapped[date] = mapped_column(Date)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)

    photos: Mapped[list[CasePhoto]] = relationship(
        back_populates="case", cascade="all, delete-orphan", order_by="CasePhoto.sort_order"
    )

    def __str__(self) -> str:
        return self.title


class CasePhoto(Base):
    __tablename__ = "case_photos"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(8))
    original_key: Mapped[str] = mapped_column(String(200))
    preview_key: Mapped[str] = mapped_column(String(200))
    caption: Mapped[str | None] = mapped_column(String(200))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    case: Mapped[Case] = relationship(back_populates="photos")


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_reviews_source_external"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(16))
    external_id: Mapped[str] = mapped_column(String(128))
    author: Mapped[str] = mapped_column(String(80))
    rating: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    review_date: Mapped[date] = mapped_column(Date, index=True)
    vehicle_brand: Mapped[str | None] = mapped_column(String(64))
    service_slug: Mapped[str | None] = mapped_column(String(64))
    case_id: Mapped[int | None] = mapped_column(ForeignKey("cases.id", ondelete="SET NULL"))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    case: Mapped[Case | None] = relationship()

    def __str__(self) -> str:
        return f"{self.author}: {self.rating}★"


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(20), default="bot")
    topic: Mapped[str] = mapped_column(String(16), default="other")
    user_message_count: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(16))
    consent_at: Mapped[datetime | None] = mapped_column()
    consent_version: Mapped[str | None] = mapped_column(String(32))
    awaiting_phone: Mapped[bool] = mapped_column(Boolean, default=False)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    handoff_requested_at: Mapped[datetime | None] = mapped_column()
    operator_joined_at: Mapped[datetime | None] = mapped_column()
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.id"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    topic: Mapped[str | None] = mapped_column(String(16))
    mode: Mapped[str | None] = mapped_column(String(16))
    suggested_replies: Mapped[Any] = mapped_column(JSONType, default=list)
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    session: Mapped[ChatSession] = relationship(back_populates="messages")


class LlmUsage(Base):
    """Daily LLM budget accounting."""

    __tablename__ = "llm_usage"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    requests: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)


class Operator(Base):
    """A dispatcher who receives leads in a private Telegram chat (registered via /operator <invite code>)."""

    __tablename__ = "operators"

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    name: Mapped[str] = mapped_column(String(120))
    username: Mapped[str | None] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    on_shift: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    def __str__(self) -> str:
        return f"{self.name} (@{self.username})" if self.username else self.name


class OperatorCard(Base):
    """A lead card message sent to an operator (DM) or to the operators group — kept in sync on every change."""

    __tablename__ = "operator_cards"
    __table_args__ = (UniqueConstraint("chat_id", "message_id", name="uq_operator_cards_chat_message"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("operators.id", ondelete="CASCADE"))
    chat_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class TgRelay(Base):
    """An operator-side Telegram message; a reply to it is routed back to the website chat or the client's bot chat."""

    __tablename__ = "tg_relays"
    __table_args__ = (UniqueConstraint("chat_id", "message_id", name="uq_tg_relays_chat_message"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int] = mapped_column(BigInteger)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"))
    chat_session_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    client_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class TgClient(Base):
    """A client who talks to the bot directly (found their leads by link, @username or phone)."""

    __tablename__ = "tg_clients"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger)
    username: Mapped[str | None] = mapped_column(String(64))
    phone: Mapped[str | None] = mapped_column(String(16), index=True)
    phone_verified_at: Mapped[datetime | None] = mapped_column()
    pending_question_lead_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
