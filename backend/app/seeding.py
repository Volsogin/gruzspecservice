"""Idempotent seed loader (settings, services, prices, cases with generated demo photos, reviews).

By default only missing rows are inserted, so admin edits survive re-seeding; `force=True`
overwrites seeded content (not leads, chats or other user data).
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    Case,
    CasePhoto,
    Counter,
    PriceBrand,
    PriceVehicleType,
    PriceWorkType,
    Service,
    Setting,
)
from app.integrations.review_sources.base import JsonFileReviewSource
from app.integrations.storage.base import Storage
from app.services.leads import FIRST_NUMBER, LEAD_COUNTER
from app.services.reviews import import_reviews

logger = logging.getLogger(__name__)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


async def _upsert(session: AsyncSession, model: type[Any], key: str, rows: list[dict[str, Any]], force: bool) -> int:
    changed = 0
    for row in rows:
        existing = await session.scalar(select(model).where(getattr(model, key) == row[key]))
        if existing is None:
            session.add(model(**row))
            changed += 1
        elif force:
            for k, v in row.items():
                setattr(existing, k, v)
            changed += 1
    return changed


async def seed_settings(session: AsyncSession, seeds: Path, force: bool) -> int:
    data = _load_json(seeds / "settings.json")
    rows = [
        {"key": k, "value": v["value"], "description": v.get("description"), "is_public": True}
        for k, v in data.items()
        if not k.startswith("_")
    ]
    return await _upsert(session, Setting, "key", rows, force)


async def seed_services(session: AsyncSession, seeds: Path, force: bool) -> int:
    return await _upsert(session, Service, "slug", _load_json(seeds / "services.json"), force)


async def seed_pricing(session: AsyncSession, seeds: Path, force: bool) -> int:
    data = yaml.safe_load((seeds / "pricing.yaml").read_text(encoding="utf-8"))
    brands = [{"sort_order": i * 10, **b} for i, b in enumerate(data["brands"], 1)]
    return (
        await _upsert(session, PriceWorkType, "slug", data["work_types"], force)
        + await _upsert(session, PriceVehicleType, "slug", data["vehicle_types"], force)
        + await _upsert(session, PriceBrand, "slug", brands, force)
    )


_COLORS = {"before": ((58, 32, 30), (196, 84, 60)), "after": ((24, 46, 36), (64, 176, 110))}


def demo_photo(title: str, kind: str, caption: str) -> tuple[bytes, bytes]:
    """Generated placeholder image (we don't use third-party photos). Returns (jpeg, webp preview)."""
    bg, accent = _COLORS[kind]
    img = Image.new("RGB", (1200, 800), bg)
    draw = ImageDraw.Draw(img)
    for i in range(0, 1200, 60):
        draw.line([(i, 800), (i + 400, 0)], fill=tuple(min(255, c + 8) for c in bg), width=18)
    draw.rectangle([(0, 0), (1200, 14)], fill=accent)
    big = ImageFont.load_default(size=96)
    small = ImageFont.load_default(size=40)
    draw.text((60, 520), "BEFORE" if kind == "before" else "AFTER", fill=accent, font=big)
    draw.text((60, 650), f"DEMO  |  {title}", fill=(230, 230, 230), font=small)
    out, prev = io.BytesIO(), io.BytesIO()
    img.save(out, "JPEG", quality=82)
    img.copy().resize((480, 320)).save(prev, "WEBP", quality=75)
    _ = caption
    return out.getvalue(), prev.getvalue()


async def seed_cases(session: AsyncSession, seeds: Path, storage: Storage, force: bool) -> int:
    changed = 0
    for item in _load_json(seeds / "cases.json"):
        photos = item.pop("photos", [])
        item["completed_on"] = date.fromisoformat(item["completed_on"])
        case = await session.scalar(select(Case).where(Case.slug == item["slug"]).options(selectinload(Case.photos)))
        if case is not None and not force:
            continue
        if case is None:
            case = Case(**item, photos=[])
            session.add(case)
        else:
            for k, v in item.items():
                setattr(case, k, v)
            case.photos.clear()
        latin = item["slug"].split("-")[0].upper()
        for order, p in enumerate(photos):
            jpeg, preview = demo_photo(latin, p["kind"], p.get("caption", ""))
            digest = hashlib.sha256(jpeg).hexdigest()[:10]
            original_key = f"cases/{item['slug']}-{p['kind']}-{digest}.jpg"
            preview_key = f"cases/{item['slug']}-{p['kind']}-{digest}-preview.webp"
            await storage.save(original_key, jpeg, "image/jpeg")
            await storage.save(preview_key, preview, "image/webp")
            case.photos.append(
                CasePhoto(
                    kind=p["kind"],
                    caption=p.get("caption"),
                    sort_order=order,
                    original_key=original_key,
                    preview_key=preview_key,
                )
            )
        changed += 1
    await session.flush()
    return changed


async def seed_counter(session: AsyncSession) -> None:
    if await session.get(Counter, LEAD_COUNTER) is None:
        session.add(Counter(name=LEAD_COUNTER, value=FIRST_NUMBER - 1))


async def run_seed(session: AsyncSession, seeds: Path, storage: Storage, force: bool = False) -> dict[str, Any]:
    """Load every seed file. Caller commits."""
    result: dict[str, Any] = {
        "settings": await seed_settings(session, seeds, force),
        "services": await seed_services(session, seeds, force),
        "pricing": await seed_pricing(session, seeds, force),
    }
    await session.flush()
    result["cases"] = await seed_cases(session, seeds, storage, force)
    result["reviews"] = await import_reviews(session, JsonFileReviewSource(seeds / "reviews.json", default_demo=True))
    await seed_counter(session)
    return result
