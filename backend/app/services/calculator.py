"""Calculator service: options from price tables + persisted estimates."""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationFailed
from app.db.models import Estimate, PriceBrand, PriceVehicleType, PriceWorkType
from app.domain.calculator import EstimateInput, estimate
from app.services.site_settings import load_settings

ORIGIN_LABELS = {
    "europe": "Европейские",
    "china": "Китайские",
    "russia": "Отечественные",
    "america": "Американские",
    "trailer": "Прицепная техника",
    "special": "Спецтехника",
}


async def get_options(session: AsyncSession) -> dict[str, Any]:
    brands = (await session.scalars(select(PriceBrand).order_by(PriceBrand.sort_order, PriceBrand.title))).all()
    vtypes = (await session.scalars(select(PriceVehicleType).order_by(PriceVehicleType.sort_order))).all()
    works = (await session.scalars(select(PriceWorkType).order_by(PriceWorkType.sort_order))).all()
    rules = (await load_settings(session)).pricing_rules()
    return {
        "brands": [
            {
                "slug": b.slug,
                "title": b.title,
                "origin": b.origin,
                "origin_label": ORIGIN_LABELS.get(b.origin, b.origin),
            }
            for b in brands
        ],
        "vehicle_types": [{"slug": v.slug, "title": v.title} for v in vtypes],
        "work_types": [
            {"slug": w.slug, "title": w.title, "description": w.description, "is_onsite_service": w.is_onsite_service}
            for w in works
        ],
        "surcharges": {"urgent_pct": rules.urgent_surcharge_pct, "onsite_fee": rules.onsite_fee},
        "currency": "RUB",
        "disclaimer": rules.disclaimer,
    }


def _norm(text: str) -> str:
    return re.sub(r"[\s\-_.]+", "", text.lower().replace("ё", "е"))


async def find_brand(session: AsyncSession, query: str) -> PriceBrand | None:
    """Match a brand by slug, title or alias ("Камаз", "kamaz", "КАМАЗ" → kamaz)."""
    q = _norm(query)
    if not q:
        return None
    for brand in await session.scalars(select(PriceBrand)):
        names = [brand.slug, brand.title, *(brand.aliases or [])]
        if any(_norm(n) == q for n in names):
            return brand
    return None


async def find_work_type(session: AsyncSession, query: str) -> PriceWorkType | None:
    q = _norm(query)
    for work in await session.scalars(select(PriceWorkType)):
        if q in (_norm(work.slug), _norm(work.title)):
            return work
    return None


async def create_estimate(
    session: AsyncSession,
    *,
    brand: str,
    work_type: str,
    vehicle_type: str | None = None,
    urgent: bool = False,
    onsite: bool = False,
) -> Estimate:
    """Compute and persist an estimate; the id can later be attached to a lead. Caller commits."""
    errors: dict[str, str] = {}
    brand_row = await find_brand(session, brand)
    if brand_row is None:
        errors["brand"] = "Марка не найдена — выберите из списка или оставьте заявку, мастер посчитает"
    work_row = await session.get(PriceWorkType, work_type) or await find_work_type(session, work_type)
    if work_row is None:
        errors["work_type"] = "Выберите тип работ из списка"
    vt_row = None
    if vehicle_type:
        vt_row = await session.get(PriceVehicleType, vehicle_type)
        if vt_row is None:
            errors["vehicle_type"] = "Выберите тип техники из списка"
    if errors:
        raise ValidationFailed("Не удалось рассчитать стоимость", fields=errors)
    assert brand_row is not None and work_row is not None

    rules = (await load_settings(session)).pricing_rules()
    result = estimate(
        EstimateInput(
            work_type_title=work_row.title,
            base_price=work_row.base_price,
            brand_title=brand_row.title,
            brand_coefficient=brand_row.coefficient,
            vehicle_type_title=vt_row.title if vt_row else None,
            vehicle_type_coefficient=vt_row.coefficient if vt_row else 1.0,
            urgent=urgent,
            onsite=onsite or work_row.is_onsite_service,
            onsite_included=work_row.is_onsite_service,
        ),
        rules,
    )
    row = Estimate(
        brand=brand_row.slug,
        vehicle_type=vt_row.slug if vt_row else None,
        work_type=work_row.slug,
        urgent=urgent,
        onsite=onsite or work_row.is_onsite_service,
        price_from=result.price_from,
        breakdown=[asdict(line) for line in result.breakdown],
    )
    session.add(row)
    await session.flush()
    return row


def estimate_to_dict(row: Estimate, disclaimer: str) -> dict[str, Any]:
    return {
        "estimate_id": str(row.id),
        "price_from": row.price_from,
        "price_label": f"от {row.price_from:,} ₽".replace(",", " "),
        "currency": "RUB",
        "breakdown": row.breakdown,
        "input": {
            "brand": row.brand,
            "vehicle_type": row.vehicle_type,
            "work_type": row.work_type,
            "urgent": row.urgent,
            "onsite": row.onsite,
        },
        "disclaimer": disclaimer,
        "lead_prefill": {
            "estimate_id": str(row.id),
            "source": "calculator",
            "lead_type": "onsite" if row.onsite else "repair",
        },
    }
