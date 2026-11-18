"""Operators (dispatchers) in Telegram: registration, shifts, who receives a lead, per-card buttons.

Routing rule for anything operators must see (new lead, client question, website chat message):
  1. the lead already has a responsible operator → only them;
  2. otherwise every active operator on shift → each gets their own card in a private chat;
  3. nobody on shift → the operators group (OPERATOR_TG_CHAT_ID), if configured.
The first operator to press «Беру» becomes responsible; the other cards turn into «Взял: …» without buttons.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Lead, Operator
from app.domain.statuses import STATUS_ACTIONS, TERMINAL, LeadStatus, allowed_transitions
from app.integrations.notifiers.base import InlineButton

TAKE_LABEL = "✋ Беру"


@dataclass(frozen=True)
class TgRecipient:
    chat_id: int
    operator_id: int | None  # None → operators group


async def active_operators(session: AsyncSession, *, on_shift_only: bool = True) -> list[Operator]:
    query = select(Operator).where(Operator.is_active.is_(True))
    if on_shift_only:
        query = query.where(Operator.on_shift.is_(True))
    return list((await session.scalars(query.order_by(Operator.id))).all())


async def recipients_for(
    session: AsyncSession, group_chat_id: int | None, lead: Lead | None = None
) -> list[TgRecipient]:
    """Who should see something about `lead` (or about a lead-less chat) in Telegram right now."""
    if lead is not None and lead.assigned_operator_id is not None:
        op = await session.get(Operator, lead.assigned_operator_id)
        if op is not None and op.is_active:
            return [TgRecipient(op.chat_id, op.id)]
    operators = await active_operators(session)
    if operators:
        return [TgRecipient(op.chat_id, op.id) for op in operators]
    if group_chat_id is not None:
        return [TgRecipient(group_chat_id, None)]
    return []


async def register_operator(session: AsyncSession, user: dict[str, Any], chat_id: int) -> tuple[Operator, bool]:
    """Create or re-activate the operator for this Telegram user. Returns (operator, created)."""
    tg_user_id = int(user["id"])
    name = " ".join(str(user.get(k) or "") for k in ("first_name", "last_name")).strip() or f"Оператор {tg_user_id}"
    op = await session.scalar(select(Operator).where(Operator.tg_user_id == tg_user_id))
    created = op is None
    if op is None:
        op = Operator(tg_user_id=tg_user_id, chat_id=chat_id, name=name[:120])
        session.add(op)
    op.chat_id, op.username = chat_id, (user.get("username") or None)
    op.is_active, op.on_shift = True, True
    await session.flush()
    return op, created


async def operator_by_user(session: AsyncSession, tg_user_id: int | None) -> Operator | None:
    if tg_user_id is None:
        return None
    return await session.scalar(select(Operator).where(Operator.tg_user_id == tg_user_id, Operator.is_active.is_(True)))


def card_buttons(lead: Lead, *, card_operator_id: int | None, is_group: bool) -> list[list[InlineButton]]:
    """Buttons for one operator card: «Беру» while unassigned; status buttons only for whoever leads the job."""
    status = LeadStatus(lead.status)
    if status in TERMINAL:
        return []
    hexid = lead.id.hex
    cancel = InlineButton(STATUS_ACTIONS[LeadStatus.CANCELLED], callback_data=f"st:{hexid}:cancelled")
    if status is LeadStatus.NEW and lead.assigned_operator_id is None:
        return [[InlineButton(TAKE_LABEL, callback_data=f"tk:{hexid}")], [cancel]]
    can_manage = is_group or lead.assigned_operator_id is None or card_operator_id == lead.assigned_operator_id
    if not can_manage:
        return []
    forward = [
        InlineButton(STATUS_ACTIONS[s], callback_data=f"st:{hexid}:{s.value}")
        for s in allowed_transitions(lead.type, lead.status)
        if s is not LeadStatus.CANCELLED
    ]
    return [row for row in (forward, [cancel]) if row]


def assignee_line(lead: Lead) -> str | None:
    return f"👷 Ответственный: {lead.assignee_name}" if lead.assignee_name else None
