"""Services catalogue ("Услуги" ribbon)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Service


def service_to_dict(s: Service) -> dict[str, Any]:
    prefill = {"lead_type": s.form_type, "service_slug": s.slug, **(s.prefill or {})}
    return {
        "slug": s.slug,
        "title": s.title,
        "short_description": s.short_description,
        "description": s.description,
        "category": s.category,
        "items": s.items or [],
        "icon": s.icon,
        "badge": s.badge,
        "is_24_7": s.is_24_7,
        "form_type": s.form_type,
        "prefill": prefill,
    }


async def list_services(session: AsyncSession) -> list[dict[str, Any]]:
    rows = await session.scalars(
        select(Service).where(Service.is_active.is_(True)).order_by(Service.sort_order, Service.id)
    )
    return [service_to_dict(s) for s in rows]


async def get_service(session: AsyncSession, slug: str) -> Service | None:
    return await session.scalar(select(Service).where(Service.slug == slug, Service.is_active.is_(True)))
