"""Request/response models — the API contract the frontend is built against (see /docs)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Open(BaseModel):
    """Objects whose inner structure is editable content (settings JSON) — documented by example."""

    model_config = ConfigDict(extra="allow")


class ErrorBody(BaseModel):
    code: str = Field(examples=["validation_error"])
    message: str = Field(examples=["Проверьте правильность заполнения полей"])
    fields: dict[str, str] | None = Field(
        default=None, examples=[{"phone": "Укажите телефон в формате +7 XXX XXX XX XX"}]
    )


class ErrorResponse(BaseModel):
    error: ErrorBody


ERRORS: dict[int | str, dict[str, Any]] = {
    422: {"model": ErrorResponse, "description": "Ошибка валидации"},
    429: {"model": ErrorResponse, "description": "Слишком много запросов (Retry-After)"},
}


class HealthOut(BaseModel):
    status: Literal["ok"]


class ReadyOut(BaseModel):
    status: Literal["ok", "degraded"]
    database: bool
    integrations: dict[str, bool]


# --- services & forms ----------------------------------------------------------------------------
class ServiceOut(BaseModel):
    slug: str = Field(examples=["onsite-repair"])
    title: str = Field(examples=["Выездной ремонт 24/7"])
    short_description: str
    description: str
    category: str = Field(examples=["onsite"])
    items: list[str]
    icon: str | None
    badge: str | None
    is_24_7: bool
    form_type: str = Field(examples=["onsite"])
    prefill: dict[str, Any] = Field(
        examples=[{"lead_type": "onsite", "service_slug": "onsite-repair", "location_mode": "onsite"}]
    )


class FormFieldOut(Open):
    name: str
    type: str
    label: str
    required: bool


class FormSchemaOut(BaseModel):
    form_type: str
    title: str
    description: str
    submit_label: str
    location_mode: Literal["sto", "onsite"]
    callback_eta_minutes: int
    fields: list[FormFieldOut]
    hidden_fields: list[str]
    form_token: str = Field(description="Вернуть в поле form_token при отправке (анти-бот проверка времени)")
    consent: dict[str, Any]


class FormListItem(BaseModel):
    form_type: str
    title: str
    location_mode: str


# --- leads & orders ----------------------------------------------------------------------------------
class LeadSummary(BaseModel):
    type: str
    type_label: str
    service_slug: str | None
    name: str | None
    phone_masked: str = Field(examples=["+7 *** *** 57 65"])
    vehicle_brand: str | None
    vehicle_type: str | None
    address: str | None
    photos_count: int
    created_at: str


class LeadCreatedOut(BaseModel):
    id: str
    number: str = Field(examples=["GS-1042"])
    public_token: str
    tracking_url: str = Field(examples=["https://example.ru/order/3q2-xYz..."])
    status: str = Field(examples=["new"])
    status_label: str = Field(examples=["Заявка получена"])
    summary: LeadSummary
    callback_eta_minutes: int
    message: str
    telegram_bind_url: str | None = Field(examples=["https://t.me/gruzspec_bot?start=3q2-xYz..."])
    telegram_bound: bool = Field(
        default=False, description="Клиент уже писал боту (тот же @ник или телефон) — подтверждение ушло в Telegram"
    )
    max_bind_url: str | None


class OrderStep(BaseModel):
    status: str
    label: str
    done: bool
    current: bool


class OrderHistoryItem(BaseModel):
    status: str
    label: str
    at: str
    comment: str | None


class OrderPhoto(BaseModel):
    preview_url: str
    url: str
    width: int
    height: int


class OrderSummary(LeadSummary):
    description: str | None
    details: list[dict[str, str]]
    photos: list[OrderPhoto]
    estimate: dict[str, Any] | None


class OrderOut(BaseModel):
    number: str
    status: str
    status_label: str
    is_cancelled: bool
    steps: list[OrderStep]
    history: list[OrderHistoryItem]
    summary: OrderSummary
    callback_eta_minutes: int
    tracking_url: str
    telegram_bind_url: str | None
    telegram_bound: bool
    email_notifications: bool
    created_at: str
    updated_at: str


# --- calculator ----------------------------------------------------------------------------------------
class EstimateIn(BaseModel):
    brand: str = Field(min_length=1, max_length=64, examples=["MAN"])
    vehicle_type: str | None = Field(default=None, max_length=64, examples=["tractor"])
    work_type: str = Field(min_length=1, max_length=64, examples=["diagnostics"])
    urgent: bool = False
    onsite: bool = False


class BreakdownLine(BaseModel):
    label: str
    amount: int


class EstimateOut(BaseModel):
    estimate_id: str
    price_from: int = Field(examples=[4200])
    price_label: str = Field(examples=["от 4 200 ₽"])
    currency: Literal["RUB"]
    breakdown: list[BreakdownLine]
    input: dict[str, Any]
    disclaimer: str
    lead_prefill: dict[str, Any]


class CalculatorOptionsOut(BaseModel):
    brands: list[dict[str, Any]]
    vehicle_types: list[dict[str, Any]]
    work_types: list[dict[str, Any]]
    surcharges: dict[str, int]
    currency: str
    disclaimer: str


# --- dispatch & geo --------------------------------------------------------------------------------------
class LatLon(BaseModel):
    lat: float = Field(ge=-90, le=90, examples=[51.5406])
    lon: float = Field(ge=-180, le=180, examples=[46.0086])


class ZoneOut(BaseModel):
    center: LatLon
    radius_km: float
    eta_minutes: int
    avg_speed_kmh: float
    region_name: str
    note: str
    geojson: dict[str, Any]


class ZoneCheckOut(BaseModel):
    zone: Literal["inside", "region", "outside"]
    distance_km: float
    eta_minutes: int | None
    message: str


class GeocodeIn(BaseModel):
    query: str = Field(min_length=3, max_length=200, examples=["Саратов, Автокомбинатовская 15"])
    limit: int = Field(default=5, ge=1, le=10)


class GeoItem(BaseModel):
    name: str
    full_name: str
    address: str | None
    lat: float
    lon: float
    type: str | None


class GeoOut(BaseModel):
    items: list[GeoItem]


# --- reviews -------------------------------------------------------------------------------------------
class ReviewOut(BaseModel):
    id: int
    author: str
    rating: int
    text: str
    date: str
    source: Literal["yandex", "2gis", "own"]
    source_label: str
    vehicle_brand: str | None
    service_slug: str | None
    case_id: int | None
    has_case: bool
    is_demo: bool


class ReviewListOut(BaseModel):
    items: list[ReviewOut]
    total: int
    limit: int
    offset: int


class ReviewSummaryOut(BaseModel):
    average_rating: float | None
    total: int
    by_source: dict[str, dict[str, Any]]
    review_links: dict[str, Any] = Field(
        examples=[{"yandex": "https://yandex.ru/maps/org/...", "2gis": "https://2gis.ru/saratov/firm/..."}]
    )
    is_demo: bool


class CasePhotoOut(BaseModel):
    url: str
    preview_url: str
    caption: str | None


class CaseOut(BaseModel):
    id: int
    slug: str
    title: str
    vehicle: dict[str, str | None]
    service_slug: str | None
    location_mode: str
    problem: str
    work_done: list[str]
    duration_hours: float | None
    price_from: int | None
    completed_on: str
    photos: dict[str, list[CasePhotoOut]]
    reviews: list[ReviewOut]
    is_demo: bool


# --- legal ---------------------------------------------------------------------------------------------
class PrivacySection(BaseModel):
    title: str
    text: str


class PrivacyOut(BaseModel):
    version: str
    title: str
    text: str
    sections: list[PrivacySection] = Field(default_factory=list, description="Разделы политики (если заданы)")
    consent_text: str
    updated_at: str | None
    is_placeholder: bool


# --- chat ----------------------------------------------------------------------------------------------
class ChatSessionIn(BaseModel):
    consent: bool = Field(default=False, description="Пользователь отметил согласие на обработку ПДн")
    name: str | None = Field(default=None, max_length=120)


class ChatMessageOut(BaseModel):
    id: int
    role: Literal["user", "assistant", "operator"]
    text: str
    topic: str | None
    mode: str | None
    suggested_replies: list[str]
    created_at: str
    operator_name: str | None = None


class ChatSessionOut(BaseModel):
    session_id: str
    status: Literal["bot", "waiting_operator", "operator", "closed"]
    topic: str
    has_phone: bool
    consent: bool
    lead_id: str | None
    messages: list[ChatMessageOut]
    llm_enabled: bool | None = None
    live_chat_available: bool | None = None


class ChatMessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000, examples=["Сколько стоит диагностика MAN?"])
    consent: bool = False


class HandoffIn(BaseModel):
    phone: str | None = Field(default=None, max_length=32, examples=["+7 960 000-00-00"])
    name: str | None = Field(default=None, max_length=120)
    consent: bool = False


class HandoffOut(BaseModel):
    session_id: str
    status: str
    topic: str
    has_phone: bool
    consent: bool
    lead_id: str | None
    message: str
    events: list[dict[str, Any]]


# --- admin ---------------------------------------------------------------------------------------------
class StatusChangeIn(BaseModel):
    status: Literal["accepted", "on_the_way", "in_progress", "completed", "cancelled"]
    comment: str | None = Field(default=None, max_length=500)


class SettingIn(BaseModel):
    value: Any
