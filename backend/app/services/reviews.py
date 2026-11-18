"""Reviews, review summary and "до/после" cases."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import NotFound
from app.db.models import Case, Review
from app.integrations.review_sources.base import ReviewSource
from app.integrations.storage.base import Storage
from app.services.site_settings import load_settings

SOURCE_LABELS = {"yandex": "Яндекс Карты", "2gis": "2ГИС", "own": "Сайт"}


def review_to_dict(r: Review) -> dict[str, Any]:
    return {
        "id": r.id,
        "author": r.author,
        "rating": r.rating,
        "text": r.text,
        "date": r.review_date.isoformat(),
        "source": r.source,
        "source_label": SOURCE_LABELS.get(r.source, r.source),
        "vehicle_brand": r.vehicle_brand,
        "service_slug": r.service_slug,
        "case_id": r.case_id,
        "has_case": r.case_id is not None,
        "is_demo": r.is_demo,
    }


async def list_reviews(
    session: AsyncSession, *, limit: int, offset: int, source: str | None, min_rating: int | None
) -> dict[str, Any]:
    query = select(Review).where(Review.is_published.is_(True))
    if source:
        query = query.where(Review.source == source)
    if min_rating:
        query = query.where(Review.rating >= min_rating)
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await session.scalars(
        query.order_by(Review.review_date.desc(), Review.id.desc()).limit(limit).offset(offset)
    )
    return {"items": [review_to_dict(r) for r in rows], "total": total, "limit": limit, "offset": offset}


async def review_summary(session: AsyncSession) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(Review.source, func.count(), func.avg(Review.rating))
            .where(Review.is_published.is_(True))
            .group_by(Review.source)
        )
    ).all()
    total = sum(int(c) for _, c, _ in rows)
    avg = sum(float(a) * int(c) for _, c, a in rows) / total if total else None
    links = (await load_settings(session)).section("review_links")
    return {
        "average_rating": round(avg, 2) if avg is not None else None,
        "total": total,
        "by_source": {
            s: {"count": int(c), "average": round(float(a), 2), "label": SOURCE_LABELS.get(s, s)} for s, c, a in rows
        },
        "review_links": links,
        "is_demo": True,
    }


async def get_case(session: AsyncSession, case_id: int, storage: Storage) -> dict[str, Any]:
    case = await session.scalar(select(Case).where(Case.id == case_id).options(selectinload(Case.photos)))
    if case is None:
        raise NotFound("Кейс не найден")
    reviews = await session.scalars(select(Review).where(Review.case_id == case.id, Review.is_published.is_(True)))

    def photos(kind: str) -> list[dict[str, Any]]:
        return [
            {"url": storage.url(p.original_key), "preview_url": storage.url(p.preview_key), "caption": p.caption}
            for p in case.photos
            if p.kind == kind
        ]

    return {
        "id": case.id,
        "slug": case.slug,
        "title": case.title,
        "vehicle": {"brand": case.vehicle_brand, "model": case.vehicle_model},
        "service_slug": case.service_slug,
        "location_mode": case.location_mode,
        "problem": case.problem,
        "work_done": case.work_done or [],
        "duration_hours": case.duration_hours,
        "price_from": case.price_from,
        "completed_on": case.completed_on.isoformat(),
        "photos": {"before": photos("before"), "after": photos("after")},
        "reviews": [review_to_dict(r) for r in reviews],
        "is_demo": case.is_demo,
    }


async def import_reviews(session: AsyncSession, source: ReviewSource) -> dict[str, int]:
    """Upsert reviews by (source, external_id). Caller commits."""
    created = updated = 0
    case_ids = {slug: cid for cid, slug in (await session.execute(select(Case.id, Case.slug))).all()}
    for item in source.fetch():
        existing = await session.scalar(
            select(Review).where(Review.source == item.source, Review.external_id == item.external_id)
        )
        values = {
            "author": item.author,
            "rating": item.rating,
            "text": item.text,
            "review_date": item.review_date,
            "vehicle_brand": item.vehicle_brand,
            "service_slug": item.service_slug,
            "is_demo": item.is_demo,
            "case_id": case_ids.get(item.case_slug) if item.case_slug else None,
        }
        if existing is None:
            session.add(Review(source=item.source, external_id=item.external_id, **values))
            created += 1
        else:
            for key, value in values.items():
                setattr(existing, key, value)
            updated += 1
    await session.flush()
    return {"created": created, "updated": updated}
