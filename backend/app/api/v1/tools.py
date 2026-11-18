"""Calculator, dispatch zone and geocoder proxy."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response

from app.api.deps import ContainerDep, DbDep
from app.api.v1.schemas import (
    ERRORS,
    CalculatorOptionsOut,
    ErrorResponse,
    EstimateIn,
    EstimateOut,
    GeocodeIn,
    GeoOut,
    LatLon,
    ZoneCheckOut,
    ZoneOut,
)
from app.core.errors import NotConfigured
from app.domain.dispatch import check_point, circle_geojson
from app.services.calculator import create_estimate, estimate_to_dict, get_options
from app.services.site_settings import load_settings

router = APIRouter()


@router.get(
    "/calculator/options",
    response_model=CalculatorOptionsOut,
    tags=["calculator"],
    summary="Марки, типы техники и типы работ для калькулятора",
)
async def calculator_options(db: DbDep, response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "public, max-age=300"
    return await get_options(db)


@router.post(
    "/calculator/estimate",
    response_model=EstimateOut,
    tags=["calculator"],
    responses=ERRORS,
    summary="Рассчитать «от N ₽»",
    description="`base(work_type) × k(brand) × k(vehicle_type) × (1 + срочность%) + выезд`, округление вверх "
    "до 100 ₽. Цены условные (seed, правятся в админке). `estimate_id` передайте в `POST /leads`, "
    "чтобы оператор видел расчёт; `lead_prefill` — готовые поля для формы.",
)
async def calculator_estimate(body: EstimateIn, db: DbDep) -> dict[str, Any]:
    row = await create_estimate(
        db,
        brand=body.brand,
        work_type=body.work_type,
        vehicle_type=body.vehicle_type,
        urgent=body.urgent,
        onsite=body.onsite,
    )
    await db.commit()
    return estimate_to_dict(row, (await load_settings(db)).pricing_rules().disclaimer)


@router.get(
    "/dispatch/zone",
    response_model=ZoneOut,
    tags=["dispatch"],
    summary="Зона «выезд за 30 минут» (круг для карты 2ГИС)",
)
async def dispatch_zone(db: DbDep, response: Response) -> dict[str, Any]:
    site = await load_settings(db)
    cfg = site.dispatch_config()
    response.headers["Cache-Control"] = "public, max-age=300"
    note = site.section("dispatch").get("note") or (
        f"В пределах {cfg.effective_radius_km:g} км от СТО — около {cfg.eta_minutes} минут"
    )
    return {
        "center": {"lat": cfg.center_lat, "lon": cfg.center_lon},
        "radius_km": cfg.effective_radius_km,
        "eta_minutes": cfg.eta_minutes,
        "avg_speed_kmh": cfg.avg_speed_kmh,
        "region_name": cfg.region_name,
        "note": note,
        "geojson": circle_geojson(cfg),
    }


@router.post(
    "/dispatch/check",
    response_model=ZoneCheckOut,
    tags=["dispatch"],
    responses=ERRORS,
    summary="Проверить точку: inside / region / outside",
    description="`inside` — в круге, «около N минут»; `region` — по области, время уточнит оператор "
    "(без обещания 30 минут); `outside` — вне зоны обслуживания.",
)
async def dispatch_check(body: LatLon, db: DbDep) -> dict[str, Any]:
    check = check_point((await load_settings(db)).dispatch_config(), body.lat, body.lon)
    return {
        "zone": check.zone.value,
        "distance_km": check.distance_km,
        "eta_minutes": check.eta_minutes,
        "message": check.message,
    }


_GEO_ERRORS: dict[int | str, dict[str, Any]] = {
    501: {"model": ErrorResponse, "description": "DGIS_API_KEY не задан — выбирайте точку на карте"},
    502: {"model": ErrorResponse, "description": "Геокодер 2ГИС недоступен"},
}


@router.post(
    "/geo/geocode",
    response_model=GeoOut,
    tags=["dispatch"],
    responses=_GEO_ERRORS,
    summary="Адрес → координаты (прокси к 2ГИС, с кэшем)",
)
async def geocode(body: GeocodeIn, container: ContainerDep) -> dict[str, Any]:
    if container.geocoder is None:
        raise NotConfigured("Геокодер не настроен", code="geocoder_not_configured")
    return {"items": [r.as_dict() for r in await container.geocoder.geocode(body.query, body.limit)]}


@router.post(
    "/geo/reverse",
    response_model=GeoOut,
    tags=["dispatch"],
    responses=_GEO_ERRORS,
    summary="Координаты → адрес (прокси к 2ГИС, с кэшем)",
)
async def reverse(body: LatLon, container: ContainerDep) -> dict[str, Any]:
    if container.geocoder is None:
        raise NotConfigured("Геокодер не настроен", code="geocoder_not_configured")
    return {"items": [r.as_dict() for r in await container.geocoder.reverse(body.lat, body.lon)]}
