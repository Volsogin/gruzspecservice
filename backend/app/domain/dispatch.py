"""Dispatch ("выезд за 30 минут") zone geometry: circle around the service station + region polygon."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

EARTH_RADIUS_KM = 6371.0088


class Zone(StrEnum):
    INSIDE = "inside"
    REGION = "region"
    OUTSIDE = "outside"


@dataclass(frozen=True)
class DispatchConfig:
    center_lat: float
    center_lon: float
    avg_speed_kmh: float = 30.0
    eta_minutes: int = 30
    radius_km: float | None = None  # explicit override; otherwise speed × eta
    region_name: str = "Саратовская область"
    region_polygon: tuple[tuple[float, float], ...] = ()  # (lon, lat) pairs

    @property
    def effective_radius_km(self) -> float:
        if self.radius_km is not None:
            return self.radius_km
        return round(self.avg_speed_kmh * self.eta_minutes / 60, 1)


@dataclass(frozen=True)
class ZoneCheck:
    zone: Zone
    distance_km: float
    eta_minutes: int | None
    message: str


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def point_in_polygon(lon: float, lat: float, polygon: tuple[tuple[float, float], ...]) -> bool:
    """Ray casting; polygon is a closed or open ring of (lon, lat)."""
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if (y1 > lat) != (y2 > lat):
            x_cross = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if lon < x_cross:
                inside = not inside
    return inside


def check_point(cfg: DispatchConfig, lat: float, lon: float) -> ZoneCheck:
    """Classify a breakdown point: inside the 30-minute circle, elsewhere in the region, or outside."""
    distance = round(haversine_km(cfg.center_lat, cfg.center_lon, lat, lon), 1)
    radius = cfg.effective_radius_km
    if distance <= radius:
        eta = max(10, min(cfg.eta_minutes, math.ceil(distance / cfg.avg_speed_kmh * 60) + 10))
        return ZoneCheck(Zone.INSIDE, distance, eta, f"Вы в зоне быстрого выезда: приедем примерно за {eta} минут.")
    if cfg.region_polygon and point_in_polygon(lon, lat, cfg.region_polygon):
        return ZoneCheck(
            Zone.REGION,
            distance,
            None,
            f"Выезжаем и сюда ({distance:g} км от СТО). Время прибытия и стоимость выезда уточнит диспетчер.",
        )
    return ZoneCheck(
        Zone.OUTSIDE,
        distance,
        None,
        f"Точка за пределами зоны обслуживания ({cfg.region_name}). Позвоните нам — "
        "подскажем, сможем ли помочь или организовать эвакуацию.",
    )


def circle_geojson(cfg: DispatchConfig, segments: int = 64) -> dict[str, Any]:
    """GeoJSON Feature approximating the dispatch circle (for drawing on a 2GIS map)."""
    lat0, lon0 = math.radians(cfg.center_lat), math.radians(cfg.center_lon)
    d = cfg.effective_radius_km / EARTH_RADIUS_KM
    ring: list[list[float]] = []
    for i in range(segments + 1):
        brg = 2 * math.pi * i / segments
        lat = math.asin(math.sin(lat0) * math.cos(d) + math.cos(lat0) * math.sin(d) * math.cos(brg))
        lon = lon0 + math.atan2(
            math.sin(brg) * math.sin(d) * math.cos(lat0), math.cos(d) - math.sin(lat0) * math.sin(lat)
        )
        ring.append([round(math.degrees(lon), 6), round(math.degrees(lat), 6)])
    return {
        "type": "Feature",
        "properties": {"radius_km": cfg.effective_radius_km, "eta_minutes": cfg.eta_minutes},
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


def dgis_point_url(lat: float, lon: float, zoom: int = 17) -> str:
    """Link that opens the point in 2GIS (used in operator notifications)."""
    return f"https://2gis.ru/geo/{lon:.6f},{lat:.6f}?m={lon:.6f},{lat:.6f}/{zoom}"
