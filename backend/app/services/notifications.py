"""Notification events → outbox rows, and rendering of outbox rows into messages.

Enqueue functions run inside the business transaction (transactional outbox), so a lead or a
status change is never committed without its notifications and vice versa.
"""

from __future__ import annotations

import html
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import ClientChannel, Lead, LeadStatusHistory, OutboxMessage
from app.domain.dispatch import dgis_point_url
from app.domain.forms import FieldType, form_for_lead_type
from app.domain.phone import format_phone
from app.domain.statuses import (
    LEAD_TYPE_LABELS,
    LeadStatus,
    LeadType,
    status_label,
)
from app.integrations.notifiers.base import telegram_link
from app.services.operators import assignee_line, recipients_for

# Outbox kinds
OPERATOR_LEAD_CREATED = "operator.lead_created"
OPERATOR_LEAD_REFRESH = "operator.lead_refresh"
OPERATOR_CHAT_MESSAGE = "operator.chat_message"
OPERATOR_CLIENT_MESSAGE = "operator.client_message"
CLIENT_OPERATOR_REPLY = "client.operator_reply"
CLIENT_LEAD_CREATED = "client.lead_created"
CLIENT_STATUS_CHANGED = "client.status_changed"

DEV_OPERATOR_EMAIL = "operator@localhost"


@dataclass(frozen=True)
class Routing:
    """Which operator channels are active (derived from env)."""

    operator_email: str | None
    operator_tg_chat_id: int | None
    email_to_file: bool
    telegram_enabled: bool

    @classmethod
    def from_settings(cls, s: Settings) -> Routing:
        return cls(
            operator_email=s.operator_email,
            operator_tg_chat_id=s.operator_tg_chat_id if s.telegram_enabled else None,
            email_to_file=not s.smtp_enabled,
            telegram_enabled=s.telegram_enabled,
        )


def _add(session: AsyncSession, kind: str, channel: str, lead_id: uuid.UUID | None, **payload: Any) -> None:
    session.add(OutboxMessage(kind=kind, channel=channel, lead_id=lead_id, payload=payload))


async def enqueue_lead_created(session: AsyncSession, lead: Lead, routing: Routing) -> None:
    """Operators get the lead (e-mail + Telegram cards); the client gets a confirmation e-mail if given."""
    if routing.operator_email:
        _add(session, OPERATOR_LEAD_CREATED, "email", lead.id, to=routing.operator_email)
    elif routing.email_to_file:
        # Dev mode: SMTP is off, so the letter only lands in var/mail/*.eml — never sent anywhere.
        _add(session, OPERATOR_LEAD_CREATED, "email", lead.id, to=DEV_OPERATOR_EMAIL)
    if routing.telegram_enabled:
        for r in await recipients_for(session, routing.operator_tg_chat_id, lead):
            _add(session, OPERATOR_LEAD_CREATED, "telegram", lead.id, to=str(r.chat_id), operator_id=r.operator_id)
    else:
        _add(session, OPERATOR_LEAD_CREATED, "log", lead.id, to="log")
    if lead.email:
        _add(session, CLIENT_LEAD_CREATED, "email", lead.id, to=lead.email)


def enqueue_status_changed(
    session: AsyncSession, lead: Lead, entry: LeadStatusHistory, channels: list[ClientChannel], routing: Routing
) -> None:
    snapshot = {
        "status": entry.to_status,
        "status_label": status_label(entry.to_status),
        "comment": entry.comment,
        "changed_at": entry.created_at.isoformat(),
    }
    if lead.email:
        _add(session, CLIENT_STATUS_CHANGED, "email", lead.id, to=lead.email, **snapshot)
    for ch in channels:
        if ch.kind in ("telegram", "max"):
            _add(session, CLIENT_STATUS_CHANGED, ch.kind, lead.id, to=ch.address, **snapshot)
    enqueue_cards_refresh(session, lead, routing)


def enqueue_cards_refresh(session: AsyncSession, lead: Lead, routing: Routing) -> None:
    """Re-render every operator card of the lead (status, responsible, buttons)."""
    if routing.telegram_enabled:
        _add(session, OPERATOR_LEAD_REFRESH, "telegram", lead.id, to="cards")


async def enqueue_chat_forward(
    session: AsyncSession, chat_message_id: int, routing: Routing, lead: Lead | None = None
) -> bool:
    """Live chat from the website: forward the client's message to the responsible / on-shift operators."""
    if not routing.telegram_enabled:
        return False
    recipients = await recipients_for(session, routing.operator_tg_chat_id, lead)
    for r in recipients:
        _add(session, OPERATOR_CHAT_MESSAGE, "telegram", None, to=str(r.chat_id), chat_message_id=chat_message_id)
    return bool(recipients)


async def enqueue_client_message(
    session: AsyncSession, lead: Lead, client_chat_id: int, text: str, routing: Routing, *, kind: str = "question"
) -> bool:
    """A client wrote to the bot about a lead (question / cancellation) → operators who should see it."""
    if not routing.telegram_enabled:
        return False
    recipients = await recipients_for(session, routing.operator_tg_chat_id, lead)
    for r in recipients:
        _add(
            session,
            OPERATOR_CLIENT_MESSAGE,
            "telegram",
            lead.id,
            to=str(r.chat_id),
            client_chat_id=client_chat_id,
            text=text[:3000],
            message_type=kind,
        )
    return bool(recipients)


def enqueue_operator_reply(session: AsyncSession, lead: Lead, client_chat_id: int, text: str, operator: str) -> None:
    """An operator answered a client's Telegram question → deliver it to the client's bot chat."""
    _add(
        session,
        CLIENT_OPERATOR_REPLY,
        "telegram",
        lead.id,
        to=str(client_chat_id),
        text=text[:3000],
        operator=operator[:60],
    )


# --- rendering ---------------------------------------------------------------------------------
def _e(value: Any) -> str:
    return html.escape(str(value), quote=False)


def _detail_lines(lead: Lead) -> list[tuple[str, str]]:
    form = form_for_lead_type(LeadType(lead.type))
    lines: list[tuple[str, str]] = []
    for key, raw in (lead.details or {}).items():
        if key in ("transcript", "topic"):
            continue
        spec = form.field(key)
        label = spec.label if spec else key
        value: Any = raw
        if spec and spec.options:
            labels: dict[Any, str] = {o.value: o.label for o in spec.options}
            value = ", ".join(str(labels.get(v, v)) for v in raw) if isinstance(raw, list) else labels.get(raw, raw)
        if spec and spec.type is FieldType.BOOLEAN:
            value = "да" if raw else "нет"
        lines.append((label, str(value)))
    return lines


def render_operator_lead(lead: Lead, settings: Settings, *, html_mode: bool) -> str:
    """Operator card for a lead: everything needed to call the client back."""
    e = _e if html_mode else str
    b = (lambda s: f"<b>{_e(s)}</b>") if html_mode else str
    out: list[str] = [
        f"{'🆕 ' if lead.status == LeadStatus.NEW else ''}{b('Заявка ' + lead.number)} · "
        f"{e(LEAD_TYPE_LABELS[LeadType(lead.type)])}",
        f"Статус: {e(status_label(lead.status))}",
    ]
    if line := assignee_line(lead):
        out.append(e(line))
    if lead.service_slug:
        out.append(f"Услуга: {e(lead.service_slug)}")
    out.append(f"Имя: {e(lead.name or '—')}")
    out.append(f"Телефон: {e(format_phone(lead.phone))}")
    if lead.email:
        out.append(f"E-mail: {e(lead.email)}")
    if lead.telegram_username:
        out.append(f"Telegram клиента: @{e(lead.telegram_username)} (бот первым не пишет — только вручную)")
    vehicle = ", ".join(x for x in (lead.vehicle_brand, lead.vehicle_type) if x)
    if vehicle:
        out.append(f"Техника: {e(vehicle)}")
    if lead.lat is not None and lead.lon is not None:
        url = dgis_point_url(lead.lat, lead.lon)
        where = lead.address or f"{lead.lat:.5f}, {lead.lon:.5f}"
        link = telegram_link(url, "открыть в 2ГИС") if html_mode else url
        zone = {"inside": "в зоне 30 минут", "region": "по области", "outside": "вне зоны"}.get(
            lead.dispatch_zone or "", ""
        )
        out.append(f"Точка: {e(where)} — {link}" + (f" ({zone})" if zone else ""))
    elif lead.address:
        out.append(f"Адрес: {e(lead.address)}")
    if lead.description:
        out.append(f"Описание: {e(lead.description)}")
    for label, value in _detail_lines(lead):
        out.append(f"{e(label)}: {e(value)}")
    if lead.estimate is not None:
        out.append(
            f"Расчёт калькулятора: от {lead.estimate.price_from:,} ₽".replace(",", " ")
            + f" ({e(lead.estimate.work_type)}, {e(lead.estimate.brand)})"
        )
    if lead.attachments:
        base = settings.api_base_url.rstrip("/") + settings.media_url_prefix
        links = [f"{base}/{a.original_key}" for a in lead.attachments]
        if html_mode:
            out.append("Фото: " + ", ".join(telegram_link(u, str(i)) for i, u in enumerate(links, 1)))
        else:
            out.append("Фото:\n" + "\n".join(links))
    transcript = (lead.details or {}).get("transcript")
    if transcript:
        out.append(b("Диалог:"))
        out.append(e(str(transcript)[-2500:]))
    out.append(f"Источник: {e(lead.source)}")
    return "\n".join(out)


def render_client_created(lead: Lead, settings: Settings, company: str) -> tuple[str, str, str]:
    form = form_for_lead_type(LeadType(lead.type))
    tracking = settings.tracking_url(lead.public_token)
    tg = settings.telegram_bind_url(lead.public_token)
    subject = f"Заявка {lead.number} принята — {company}"
    lines = [
        f"Здравствуйте{', ' + lead.name if lead.name else ''}!",
        "",
        f"Мы получили вашу заявку {lead.number} ({LEAD_TYPE_LABELS[LeadType(lead.type)].lower()}).",
        form.success_message,
        "",
        f"Статус и детали заявки: {tracking}",
    ]
    if tg:
        lines.append(f"Получать статус в Telegram: {tg}")
    lines += ["", f"— {company}"]
    text = "\n".join(lines)
    html_body = _simple_html(subject, lines, tracking, tg)
    return subject, text, html_body


def render_client_status(
    lead: Lead, payload: dict[str, Any], settings: Settings, company: str, *, html_mode: bool
) -> tuple[str, str]:
    tracking = settings.tracking_url(lead.public_token)
    label = payload.get("status_label") or status_label(str(payload.get("status")))
    subject = f"Заявка {lead.number}: {label}"
    comment = payload.get("comment")
    if html_mode:
        text = (
            f"<b>{_e(subject)}</b>"
            + (f"\n{_e(comment)}" if comment else "")
            + "\n\n"
            + telegram_link(tracking, "Открыть заявку")
        )
    else:
        text = "\n".join(
            [
                f"Статус вашей заявки {lead.number}: {label}.",
                *([comment] if comment else []),
                "",
                f"Подробнее: {tracking}",
                "",
                f"— {company}",
            ]
        )
    return subject, text


def _simple_html(title: str, lines: list[str], tracking: str, tg: str | None) -> str:
    skip = ("Статус и", "Получать")
    body = "".join(f"<p>{_e(line)}</p>" for line in lines if line and not line.startswith(skip))
    buttons = f'<p><a href="{_e(tracking)}">Открыть заявку</a></p>'
    if tg:
        buttons += f'<p><a href="{_e(tg)}">Получать статус в Telegram</a></p>'
    return f"<!doctype html><html><body><h2>{_e(title)}</h2>{body}{buttons}</body></html>"
