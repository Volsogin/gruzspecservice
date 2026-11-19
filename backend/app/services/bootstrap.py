"""`GET /bootstrap`: everything for the first screen in one cached, pre-compressed response."""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any

import brotli
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import PriceBrand
from app.domain.forms import FORMS
from app.services.catalog import list_services
from app.services.reviews import list_reviews, review_summary
from app.services.site_settings import load_settings


@dataclass(frozen=True)
class CachedBody:
    raw: bytes
    gzip: bytes
    br: bytes
    etag: str
    built_at: float


async def build_bootstrap(
    session: AsyncSession, bot_username: str | None = None, maps: dict[str, str | None] | None = None
) -> dict[str, Any]:
    site = await load_settings(session)
    public = site.public(bot_username, maps)
    brands = (await session.scalars(select(PriceBrand).order_by(PriceBrand.sort_order))).all()
    lat, lon = site.sto_point
    dispatch = site.dispatch_config()
    return {
        "settings": public,
        "work_status": public["work_status"],
        "services": await list_services(session),
        "stats": public["stats"],
        "reviews": {
            "summary": await review_summary(session),
            "top": (await list_reviews(session, limit=6, offset=0, source=None, min_rating=4))["items"],
        },
        "brands": [{"slug": b.slug, "title": b.title, "origin": b.origin} for b in brands],
        "dispatch_zone": {
            "center": {"lat": lat, "lon": lon},
            "radius_km": dispatch.effective_radius_km,
            "eta_minutes": dispatch.eta_minutes,
        },
        "forms": [{"form_type": f.form_type.value, "title": f.title} for f in FORMS.values()],
    }


class BootstrapCache:
    """Builds the payload at most once per `ttl` seconds; ETag = content hash."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        ttl: float,
        bot_username: str | None = None,
        maps: dict[str, str | None] | None = None,
    ) -> None:
        self.bot_username = bot_username
        self.maps = maps
        self.session_factory = session_factory
        self.ttl = ttl
        self._entry: CachedBody | None = None
        self._lock = asyncio.Lock()

    def invalidate(self) -> None:
        self._entry = None

    async def get(self) -> CachedBody:
        entry = self._entry
        if entry and time.monotonic() - entry.built_at < self.ttl:
            return entry
        async with self._lock:
            entry = self._entry
            if entry and time.monotonic() - entry.built_at < self.ttl:
                return entry
            async with self.session_factory() as session:
                payload = await build_bootstrap(session, self.bot_username, self.maps)
            raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode()
            # work_status.local_time changes every minute; exclude it from the ETag so caches stay warm.
            status = {k: v for k, v in payload["work_status"].items() if k != "local_time"}
            stable = dict(payload, work_status=status, settings=dict(payload["settings"], work_status=status))
            etag_src = json.dumps(stable, ensure_ascii=False, sort_keys=True, default=str).encode()
            etag = '"' + hashlib.sha256(etag_src).hexdigest()[:24] + '"'
            entry = CachedBody(raw, gzip.compress(raw, 6), brotli.compress(raw, quality=5), etag, time.monotonic())
            self._entry = entry
            return entry
