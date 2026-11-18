"""Content endpoints: settings, bootstrap, services, forms, legal, reviews, cases."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request, Response

from app.api.deps import ContainerDep, DbDep
from app.api.v1.schemas import (
    CaseOut,
    FormListItem,
    FormSchemaOut,
    Open,
    PrivacyOut,
    ReviewListOut,
    ReviewSummaryOut,
    ServiceOut,
)
from app.core.errors import NotFound
from app.domain.forms import FORMS, get_form
from app.services import reviews as reviews_service
from app.services.catalog import list_services
from app.services.site_settings import load_settings

router = APIRouter()

PUBLIC_CACHE = "public, max-age=60, stale-while-revalidate=300"


@router.get(
    "/settings/public",
    response_model=Open,
    tags=["content"],
    summary="Контакты, адрес, статистика",
    description="Телефон, мессенджеры, адрес и координаты СТО для карты, режим работы и текущий статус "
    "(`work_status`), статистика блока доверия (демо), гарантия, ссылки на отзывы.",
)
async def public_settings(db: DbDep, response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = PUBLIC_CACHE
    return (await load_settings(db)).public()


@router.get(
    "/bootstrap",
    tags=["content"],
    summary="Всё для первого экрана одним запросом",
    response_model=Open,
    description="settings + services + stats + топ-отзывы + work_status + зона выезда + марки. "
    "Кэшируется в памяти, отдаётся с `ETag` (поддерживает `If-None-Match` → 304) "
    "и сжатием brotli/gzip по `Accept-Encoding`.",
)
async def bootstrap(request: Request, container: ContainerDep) -> Response:
    cached = await container.bootstrap.get()
    headers = {"ETag": cached.etag, "Cache-Control": PUBLIC_CACHE, "Vary": "Accept-Encoding"}
    if request.headers.get("if-none-match") == cached.etag:
        return Response(status_code=304, headers=headers)
    accept = request.headers.get("accept-encoding", "")
    if "br" in accept:
        return Response(cached.br, media_type="application/json", headers={**headers, "Content-Encoding": "br"})
    if "gzip" in accept:
        return Response(cached.gzip, media_type="application/json", headers={**headers, "Content-Encoding": "gzip"})
    return Response(cached.raw, media_type="application/json", headers=headers)


@router.get(
    "/services",
    response_model=list[ServiceOut],
    tags=["content"],
    summary="Лента услуг",
    description="Карточки услуг. `prefill` — что подставить в форму заявки при выборе карточки "
    "(`lead_type`, `service_slug`, `location_mode`); `form_type` — какую схему формы загрузить.",
)
async def services(db: DbDep, response: Response) -> list[dict[str, Any]]:
    response.headers["Cache-Control"] = PUBLIC_CACHE
    return await list_services(db)


@router.get("/forms", response_model=list[FormListItem], tags=["forms"], summary="Типы форм заявки")
async def forms() -> list[dict[str, Any]]:
    return [
        {"form_type": f.form_type.value, "title": f.title, "location_mode": f.location_mode} for f in FORMS.values()
    ]


@router.get(
    "/forms/{form_type}",
    response_model=FormSchemaOut,
    tags=["forms"],
    summary="Схема формы заявки",
    description="Поля формы для типа заявки. Фронт рисует поля по схеме, сервер валидирует `POST /leads` "
    "по ней же. Поле типа `geo_point` передаётся тремя полями: `lat`, `lon`, `address`. "
    "`form_token` нужно вернуть при отправке.",
)
async def form_schema(form_type: str, container: ContainerDep, db: DbDep, response: Response) -> dict[str, Any]:
    form = get_form(form_type)
    if form is None or not form.public:
        raise NotFound("Неизвестный тип формы")
    site = await load_settings(db)
    response.headers["Cache-Control"] = "no-store"  # form_token is time-bound
    return {
        **form.to_public(),
        "form_token": container.signer.issue(form.form_type.value),
        "consent": {
            "version": site.consent_version,
            "text": site.section("legal").get("consent_text"),
            "privacy_url": "/api/v1/legal/privacy",
        },
    }


@router.get("/legal/privacy", response_model=PrivacyOut, tags=["content"], summary="Политика обработки ПДн")
async def privacy(db: DbDep) -> dict[str, Any]:
    legal = (await load_settings(db)).section("legal")
    return {
        "version": str(legal.get("consent_version", "v1")),
        "title": legal.get("privacy_title", ""),
        "text": legal.get("privacy_text", ""),
        "consent_text": legal.get("consent_text", ""),
        "updated_at": legal.get("updated_at"),
        "is_placeholder": bool(legal.get("is_placeholder", True)),
    }


@router.get("/reviews", response_model=ReviewListOut, tags=["reviews"], summary="Отзывы (с пагинацией)")
async def reviews(
    db: DbDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
    source: Literal["yandex", "2gis", "own"] | None = None,
    min_rating: Annotated[int | None, Query(ge=1, le=5)] = None,
) -> dict[str, Any]:
    return await reviews_service.list_reviews(db, limit=limit, offset=offset, source=source, min_rating=min_rating)


@router.get(
    "/reviews/summary",
    response_model=ReviewSummaryOut,
    tags=["reviews"],
    summary="Средний рейтинг, счётчики по площадкам, ссылки «Отзывы на Яндексе / 2ГИС»",
)
async def reviews_summary(db: DbDep) -> dict[str, Any]:
    return await reviews_service.review_summary(db)


@router.get(
    "/cases/{case_id}", response_model=CaseOut, tags=["reviews"], summary="Кейс к отзыву: данные заказа и фото до/после"
)
async def case(case_id: int, db: DbDep, container: ContainerDep) -> dict[str, Any]:
    return await reviews_service.get_case(db, case_id, container.storage)
