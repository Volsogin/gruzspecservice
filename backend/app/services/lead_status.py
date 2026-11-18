"""The ONE place where a lead's status changes (admin, Telegram buttons and admin API all call this)."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import Conflict, NotFound
from app.db.base import utcnow
from app.db.models import Lead, LeadStatusHistory
from app.domain.statuses import InvalidTransition, ensure_transition
from app.services.notifications import Routing, enqueue_status_changed

logger = logging.getLogger(__name__)


async def change_status(
    session: AsyncSession,
    lead_id: uuid.UUID,
    target: str,
    *,
    actor: str,
    routing: Routing,
    comment: str | None = None,
) -> Lead:
    """Validate the transition, append history, enqueue client notifications. Caller commits."""
    lead = await session.scalar(
        select(Lead)
        .where(Lead.id == lead_id)
        .options(selectinload(Lead.channels), selectinload(Lead.attachments), selectinload(Lead.estimate))
        .with_for_update()
    )
    if lead is None:
        raise NotFound("Заявка не найдена")
    try:
        new_status = ensure_transition(lead.type, lead.status, target)
    except InvalidTransition as exc:
        raise Conflict(str(exc), code="invalid_transition") from exc

    now = utcnow()
    entry = LeadStatusHistory(
        lead_id=lead.id,
        from_status=lead.status,
        to_status=new_status.value,
        actor=actor[:64],
        comment=(comment or None) and comment[:500],
        created_at=now,
    )
    session.add(entry)
    lead.status = new_status.value
    lead.status_changed_at = now
    await session.flush()
    enqueue_status_changed(session, lead, entry, list(lead.channels), routing)
    logger.info("lead_status_changed", extra={"lead_number": lead.number, "status": lead.status, "actor": actor})
    return lead
