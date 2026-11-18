"""Token-protected admin JSON API (the same status service as the admin UI and Telegram buttons)."""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import AdminDep, ContainerDep, DbDep
from app.api.v1.schemas import ERRORS, ErrorResponse, Open, SettingIn, StatusChangeIn
from app.core.errors import NotFound
from app.db.models import Lead, OutboxMessage, Setting
from app.domain.statuses import allowed_transitions, status_label
from app.services.lead_status import change_status
from app.services.notifications import Routing

router = APIRouter(
    prefix="/admin", tags=["admin"], responses={401: {"model": ErrorResponse}, 501: {"model": ErrorResponse}}
)


def _lead_dict(lead: Lead, container: ContainerDep, full: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": str(lead.id),
        "number": lead.number,
        "type": lead.type,
        "status": lead.status,
        "status_label": status_label(lead.status),
        "name": lead.name,
        "phone": lead.phone,
        "email": lead.email,
        "vehicle_brand": lead.vehicle_brand,
        "service_slug": lead.service_slug,
        "source": lead.source,
        "created_at": lead.created_at.isoformat(),
        "allowed_transitions": [s.value for s in allowed_transitions(lead.type, lead.status)],
    }
    if full:
        data.update(
            {
                "telegram_username": lead.telegram_username,
                "vehicle_type": lead.vehicle_type,
                "description": lead.description,
                "details": lead.details,
                "lat": lead.lat,
                "lon": lead.lon,
                "address": lead.address,
                "dispatch_zone": lead.dispatch_zone,
                "estimate": {
                    "id": str(lead.estimate.id),
                    "price_from": lead.estimate.price_from,
                    "breakdown": lead.estimate.breakdown,
                }
                if lead.estimate
                else None,
                "consent": {
                    "given": lead.consent_given,
                    "at": lead.consent_at.isoformat() if lead.consent_at else None,
                    "version": lead.consent_version,
                },
                "tracking_url": container.settings.tracking_url(lead.public_token),
                "photos": [container.storage.url(a.original_key) for a in lead.attachments],
                "history": [
                    {
                        "from": h.from_status,
                        "to": h.to_status,
                        "actor": h.actor,
                        "comment": h.comment,
                        "at": h.created_at.isoformat(),
                    }
                    for h in lead.history
                ],
                "channels": [{"kind": c.kind, "address": c.address} for c in lead.channels],
            }
        )
    return data


@router.get("/leads", response_model=Open, summary="Список заявок")
async def leads(
    _: AdminDep,
    db: DbDep,
    container: ContainerDep,
    status: str | None = None,
    type: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    query = select(Lead)
    if status:
        query = query.where(Lead.status == status)
    if type:
        query = query.where(Lead.type == type)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await db.scalars(query.order_by(Lead.created_at.desc()).limit(limit).offset(offset))
    return {"items": [_lead_dict(r, container) for r in rows], "total": total}


async def _load(db: DbDep, lead_id: uuid.UUID) -> Lead:
    lead = await db.scalar(
        select(Lead)
        .where(Lead.id == lead_id)
        .options(
            selectinload(Lead.history),
            selectinload(Lead.attachments),
            selectinload(Lead.channels),
            selectinload(Lead.estimate),
        )
    )
    if lead is None:
        raise NotFound("Заявка не найдена")
    return lead


@router.get("/leads/{lead_id}", response_model=Open, summary="Заявка целиком (с историей и каналами)")
async def lead(lead_id: uuid.UUID, _: AdminDep, db: DbDep, container: ContainerDep) -> dict[str, Any]:
    return _lead_dict(await _load(db, lead_id), container, full=True)


@router.post(
    "/leads/{lead_id}/status",
    response_model=Open,
    summary="Сменить статус заявки",
    description="Та же функция, что у кнопок в Telegram и админки: история + уведомление клиенту.",
    responses={**ERRORS, 409: {"model": ErrorResponse, "description": "Недопустимый переход"}},
)
async def set_status(
    lead_id: uuid.UUID, body: StatusChangeIn, actor: AdminDep, db: DbDep, container: ContainerDep
) -> dict[str, Any]:
    await change_status(
        db, lead_id, body.status, actor=actor, comment=body.comment, routing=Routing.from_settings(container.settings)
    )
    await db.commit()
    container.outbox.kick()
    db.expunge_all()
    return _lead_dict(await _load(db, lead_id), container, full=True)


@router.get("/outbox", response_model=Open, summary="Очередь уведомлений (диагностика)")
async def outbox(
    _: AdminDep, db: DbDep, status: Literal["pending", "processing", "sent", "dead"] | None = None
) -> dict[str, Any]:
    query = select(OutboxMessage).order_by(OutboxMessage.id.desc()).limit(50)
    if status:
        query = query.where(OutboxMessage.status == status)
    rows = await db.scalars(query)
    return {
        "items": [
            {
                "id": m.id,
                "kind": m.kind,
                "channel": m.channel,
                "status": m.status,
                "attempts": m.attempts,
                "last_error": m.last_error,
                "created_at": m.created_at.isoformat(),
                "sent_at": m.sent_at.isoformat() if m.sent_at else None,
            }
            for m in rows
        ]
    }


@router.get("/settings", response_model=Open, summary="Все настройки сайта")
async def settings(_: AdminDep, db: DbDep) -> dict[str, Any]:
    return {key: value for key, value in (await db.execute(select(Setting.key, Setting.value))).all()}


@router.put("/settings/{key}", response_model=Open, summary="Изменить настройку (JSON-значение)")
async def put_setting(key: str, body: SettingIn, _: AdminDep, db: DbDep, container: ContainerDep) -> dict[str, Any]:
    row = await db.get(Setting, key)
    if row is None:
        raise NotFound("Настройка не найдена")
    row.value = body.value
    await db.commit()
    container.bootstrap.invalidate()
    return {"key": key, "value": row.value}
