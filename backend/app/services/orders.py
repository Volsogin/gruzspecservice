"""Public order page data (`/order/{public_token}`): status, history, masked summary."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.core.errors import NotFound
from app.db.models import Lead
from app.domain.forms import form_for_lead_type
from app.domain.statuses import DISPATCH_TYPES, LeadStatus, LeadType, status_label
from app.integrations.storage.base import Storage
from app.services.calculator import estimate_to_dict
from app.services.leads import lead_summary
from app.services.notifications import _detail_lines

_NOT_FOUND = "Заявка не найдена. Проверьте ссылку из письма или Telegram."


def _expected_steps(lead_type: str) -> list[LeadStatus]:
    steps = [LeadStatus.NEW, LeadStatus.ACCEPTED]
    if LeadType(lead_type) in DISPATCH_TYPES:
        steps.append(LeadStatus.ON_THE_WAY)
    return [*steps, LeadStatus.IN_PROGRESS, LeadStatus.COMPLETED]


def _estimate(lead: Lead) -> dict[str, Any] | None:
    row = lead.estimate
    if row is None:
        return None
    data = estimate_to_dict(row, "")
    return {k: data[k] for k in ("price_from", "price_label", "currency", "breakdown", "input")}


async def get_order(session: AsyncSession, token: str, settings: Settings, storage: Storage) -> dict[str, Any]:
    """Raises the same NotFound for malformed, unknown and foreign tokens (no oracle)."""
    if not (16 <= len(token) <= 64) or not all(c.isalnum() or c in "-_" for c in token):
        raise NotFound(_NOT_FOUND)
    lead = await session.scalar(
        select(Lead)
        .where(Lead.public_token == token)
        .options(
            selectinload(Lead.history),
            selectinload(Lead.attachments),
            selectinload(Lead.channels),
            selectinload(Lead.estimate),
        )
    )
    if lead is None:
        raise NotFound(_NOT_FOUND)

    reached = {h.to_status for h in lead.history}
    steps = [
        {
            "status": s.value,
            "label": status_label(s.value),
            "done": s.value in reached,
            "current": s.value == lead.status,
        }
        for s in _expected_steps(lead.type)
    ]
    summary = lead_summary(lead)
    summary.update(
        {
            "description": lead.description,
            "details": [{"label": label, "value": value} for label, value in _detail_lines(lead)],
            "photos": [
                {
                    "preview_url": storage.url(a.preview_key),
                    "url": storage.url(a.original_key),
                    "width": a.width,
                    "height": a.height,
                }
                for a in lead.attachments
            ],
            "estimate": _estimate(lead),
        }
    )
    form = form_for_lead_type(LeadType(lead.type))
    return {
        "number": lead.number,
        "status": lead.status,
        "status_label": status_label(lead.status),
        "is_cancelled": lead.status == LeadStatus.CANCELLED,
        "steps": steps,
        "history": [
            {
                "status": h.to_status,
                "label": status_label(h.to_status),
                "at": h.created_at.isoformat(),
                "comment": h.comment,
            }
            for h in lead.history
        ],
        "summary": summary,
        "callback_eta_minutes": form.callback_eta_minutes,
        "tracking_url": settings.tracking_url(lead.public_token),
        "telegram_bind_url": settings.telegram_bind_url(lead.public_token),
        "telegram_bound": any(c.kind == "telegram" for c in lead.channels),
        "email_notifications": bool(lead.email),
        "created_at": lead.created_at.isoformat(),
        "updated_at": lead.status_changed_at.isoformat(),
    }
