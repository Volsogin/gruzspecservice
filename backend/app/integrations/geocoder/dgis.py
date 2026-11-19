"""2GIS Catalog API geocoder (forward + reverse) with an in-memory TTL cache.

Endpoint per docs.2gis.com: GET https://catalog.api.2gis.com/3.0/items/geocode
  forward: q=<address>&fields=items.point
  reverse: lat=..&lon=..&fields=items.point,items.address
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.errors import UpstreamError


@dataclass(frozen=True)
class GeoResult:
    name: str
    full_name: str
    address: str | None
    lat: float
    lon: float
    type: str | None

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class Geocoder(Protocol):
    async def geocode(self, query: str, limit: int = 5) -> list[GeoResult]: ...

    async def reverse(self, lat: float, lon: float) -> list[GeoResult]: ...


class _TTLCache:
    def __init__(self, ttl: float = 3600, size: int = 1000) -> None:
        self.ttl, self.size = ttl, size
        self._data: OrderedDict[str, tuple[float, list[GeoResult]]] = OrderedDict()

    def get(self, key: str) -> list[GeoResult] | None:
        item = self._data.get(key)
        if not item or item[0] < time.monotonic():
            self._data.pop(key, None)
            return None
        self._data.move_to_end(key)
        return item[1]

    def put(self, key: str, value: list[GeoResult]) -> None:
        self._data[key] = (time.monotonic() + self.ttl, value)
        self._data.move_to_end(key)
        while len(self._data) > self.size:
            self._data.popitem(last=False)


def parse_items(body: dict[str, Any]) -> list[GeoResult]:
    meta_code = (body.get("meta") or {}).get("code")
    if meta_code == 404:
        return []
    if meta_code not in (200, None):
        raise UpstreamError("Геокодер 2ГИС вернул ошибку", code="geocoder_error")
    results = []
    for item in (body.get("result") or {}).get("items") or []:
        point = item.get("point") or {}
        if "lat" not in point or "lon" not in point:
            continue
        results.append(
            GeoResult(
                name=str(item.get("name") or item.get("full_name") or ""),
                full_name=str(item.get("full_name") or item.get("name") or ""),
                address=item.get("address_name"),
                lat=float(point["lat"]),
                lon=float(point["lon"]),
                type=item.get("type"),
            )
        )
    return results


class DgisGeocoder:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://catalog.api.2gis.com/3.0",
        timeout: float = 8.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._key = api_key
        self._url = f"{base_url.rstrip('/')}/items/geocode"
        self._timeout = timeout
        self._transport = transport
        self._cache = _TTLCache()

    async def _request(self, params: dict[str, Any]) -> list[GeoResult]:
        # trust_env=False: desktop VPN clients export proxy variables (e.g. ALL_PROXY=socks://…) that httpx
        # can't parse; 2GIS is reachable directly, so the process environment must not affect it.
        cache_key = repr(sorted(params.items()))
        if (cached := self._cache.get(cache_key)) is not None:
            return cached
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport, trust_env=False) as client:
                resp = await client.get(self._url, params={**params, "key": self._key})
        except httpx.HTTPError:
            raise UpstreamError("Геокодер 2ГИС недоступен", code="geocoder_unavailable") from None
        if resp.status_code >= 400:
            raise UpstreamError("Геокодер 2ГИС вернул ошибку", code="geocoder_error")
        results = parse_items(resp.json())
        self._cache.put(cache_key, results)
        return results

    async def geocode(self, query: str, limit: int = 5) -> list[GeoResult]:
        return (await self._request({"q": query, "fields": "items.point", "page_size": limit}))[:limit]

    async def reverse(self, lat: float, lon: float) -> list[GeoResult]:
        return await self._request({"lat": f"{lat:.6f}", "lon": f"{lon:.6f}", "fields": "items.point,items.address"})
