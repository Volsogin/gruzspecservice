"""`POST /leads` and the public order page `GET /orders/{token}`."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header, Request, Response
from starlette.datastructures import UploadFile

from app.api.deps import ClientIpDep, ContainerDep, DbDep
from app.api.v1.schemas import ERRORS, ErrorResponse, LeadCreatedOut, OrderOut
from app.core.errors import AppError, ValidationFailed
from app.core.security import hash_ip
from app.domain.forms import FieldType, all_wire_fields
from app.services.leads import RequestContext
from app.services.orders import get_order
from app.services.photos import UploadedFile

router = APIRouter()

_TYPE_MAP: dict[FieldType, dict[str, Any]] = {
    FieldType.INTEGER: {"type": "integer"},
    FieldType.BOOLEAN: {"type": "boolean"},
    FieldType.CONSENT: {"type": "boolean"},
    FieldType.MULTISELECT: {"type": "array", "items": {"type": "string"}},
}


def _multipart_schema() -> dict[str, Any]:
    props: dict[str, Any] = {
        "lead_type": {"type": "string", "enum": ["repair", "onsite", "tow", "parts", "corporate", "callback"]}
    }
    for name, spec in all_wire_fields().items():
        if spec.type is FieldType.FILES:
            props["photos"] = {"type": "array", "items": {"type": "string", "format": "binary"}, "maxItems": 5}
        elif spec.type is FieldType.GEO_POINT:
            props["lat"] = {"type": "number"}
            props["lon"] = {"type": "number"}
            props["address"] = {"type": "string"}
        else:
            props[name] = {**_TYPE_MAP.get(spec.type, {"type": "string"}), "description": spec.label}
    return {"type": "object", "required": ["lead_type", "phone", "consent"], "properties": props}


_EXAMPLE = {
    "lead_type": "onsite",
    "service_slug": "onsite-repair",
    "name": "Иван",
    "phone": "+7 (927) 123-45-67",
    "vehicle_brand": "MAN",
    "vehicle_type": "tractor",
    "is_drivable": "no",
    "description": "Не заводится на трассе",
    "lat": 51.56,
    "lon": 46.02,
    "address": "Трасса Р-228, 12 км",
    "consent": True,
}


@router.post(
    "/leads",
    status_code=201,
    response_model=LeadCreatedOut,
    tags=["leads"],
    summary="Создать заявку (любого типа)",
    description=(
        "Единый приём заявок. `multipart/form-data` (поля + до 5 файлов в `photos`) или `application/json` "
        "(без фото). Набор и обязательность полей зависят от `lead_type` — см. `GET /forms/{form_type}`. "
        "Конвейер: honeypot (`website`) → проверка `form_token` → валидация по схеме (телефон → +7XXXXXXXXXX, "
        "ИНН, согласие ПДн) → фото (проверка содержимого, удаление EXIF/GPS, WebP-превью) → запись в БД + "
        "outbox в одной транзакции. Уведомления отправляет фоновый воркер, сбой SMTP/Telegram не влияет на ответ. "
        "Заголовок `Idempotency-Key` защищает от двойной отправки: повтор вернёт ту же заявку "
        "(`Idempotent-Replayed: true`)."
    ),
    responses={
        **ERRORS,
        409: {"model": ErrorResponse, "description": "Idempotency-Key занят другой заявкой"},
        413: {"model": ErrorResponse, "description": "Слишком большой запрос"},
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {"schema": _multipart_schema()},
                "application/json": {"schema": _multipart_schema(), "example": _EXAMPLE},
            },
        }
    },
)
async def create_lead(
    request: Request,
    response: Response,
    container: ContainerDep,
    ip: ClientIpDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    user_agent: Annotated[str | None, Header(alias="User-Agent")] = None,
) -> dict[str, Any]:
    data, files = await _read_body(request, container.settings.max_upload_files)
    result = await container.leads.create_from_form(
        data, files, RequestContext(ip=ip, user_agent=user_agent, idempotency_key=idempotency_key)
    )
    if result.replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return result.body


async def _read_body(request: Request, max_files: int) -> tuple[dict[str, Any], list[UploadedFile]]:
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("application/json"):
        try:
            payload = await request.json()
        except ValueError as exc:
            raise AppError("Тело запроса — некорректный JSON", code="bad_json") from exc
        if not isinstance(payload, dict) or len(payload) > 60:
            raise ValidationFailed("Ожидается JSON-объект с полями формы")
        return payload, []
    if ctype.startswith("multipart/form-data") or ctype.startswith("application/x-www-form-urlencoded"):
        form = await request.form(max_files=max_files + 1, max_fields=60, max_part_size=64 * 1024)
        data: dict[str, Any] = {}
        files: list[UploadedFile] = []
        for key, value in form.multi_items():
            if isinstance(value, UploadFile):
                if key == "photos" and (value.filename or value.size):
                    files.append(UploadedFile(value.filename or "photo", await value.read()))
                continue
            if key in data:  # repeated keys → list (multiselect)
                data[key] = [*data[key], value] if isinstance(data[key], list) else [data[key], value]
            else:
                data[key] = value
        await form.close()
        return data, files
    raise AppError(
        "Поддерживаются multipart/form-data и application/json", code="unsupported_media_type", status_code=415
    )


@router.get(
    "/orders/{public_token}",
    response_model=OrderOut,
    tags=["leads"],
    summary="Статус заявки по ссылке",
    description="Страница `/order/{token}` на фронте. Телефон маскируется, фото — превью. Ответ одинаковый (404) "
    "для несуществующего и неверного токена. `X-Robots-Tag: noindex`, rate limit по IP.",
    responses={404: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
)
async def order(
    public_token: str, response: Response, db: DbDep, container: ContainerDep, ip: ClientIpDep
) -> dict[str, Any]:
    s = container.settings
    ip_key = hash_ip(ip, s.secret_key.get_secret_value()) or "unknown"
    container.limiter.hit(f"orders:ip:{ip_key}", s.orders_per_ip_per_minute, 60)
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return await get_order(db, public_token, s, container.storage)
