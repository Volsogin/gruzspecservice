"""Lead form schemas per lead type.

The same schema is (1) served to the frontend via `GET /forms/{form_type}` so it can render
fields dynamically, and (2) used by `LeadValidator` on `POST /leads`. One source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.domain.statuses import LeadType


class FieldType(StrEnum):
    TEXT = "text"
    TEXTAREA = "textarea"
    PHONE = "phone"
    EMAIL = "email"
    TELEGRAM = "telegram_username"
    SELECT = "select"
    MULTISELECT = "multiselect"
    BOOLEAN = "boolean"
    CONSENT = "consent"
    INTEGER = "integer"
    DATETIME = "datetime"
    GEO_POINT = "geo_point"
    INN = "inn"
    VIN = "vin"
    FILES = "files"
    HIDDEN = "hidden"
    UUID = "uuid"


@dataclass(frozen=True)
class Option:
    value: str
    label: str


@dataclass(frozen=True)
class FieldSpec:
    name: str
    type: FieldType
    label: str
    required: bool = False
    target: str = "details"  # "column" → Lead column, "details" → Lead.details JSON, "meta" → not stored
    placeholder: str | None = None
    help: str | None = None
    options: tuple[Option, ...] = ()
    options_source: str | None = None
    max_length: int | None = None
    min_value: int | None = None
    max_value: int | None = None
    required_if: dict[str, str] | None = None
    max_files: int | None = None
    mask: str | None = None

    def to_public(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "type": self.type.value,
            "label": self.label,
            "required": self.required,
        }
        optional = {
            "placeholder": self.placeholder,
            "help": self.help,
            "options_source": self.options_source,
            "max_length": self.max_length,
            "min": self.min_value,
            "max": self.max_value,
            "required_if": self.required_if,
            "max_files": self.max_files,
            "mask": self.mask,
        }
        data.update({k: v for k, v in optional.items() if v is not None})
        if self.options:
            data["options"] = [{"value": o.value, "label": o.label} for o in self.options]
        if self.type is FieldType.GEO_POINT:
            data["wire_fields"] = ["lat", "lon", "address"]
        return data


@dataclass(frozen=True)
class FormSchema:
    form_type: LeadType
    title: str
    description: str
    submit_label: str
    fields: tuple[FieldSpec, ...]
    callback_eta_minutes: int
    success_message: str
    location_mode: str = "sto"  # "sto" | "onsite" — whether the frontend shows a map picker
    public: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    def field(self, name: str) -> FieldSpec | None:
        return next((f for f in self.fields if f.name == name), None)

    def to_public(self) -> dict[str, Any]:
        return {
            "form_type": self.form_type.value,
            "title": self.title,
            "description": self.description,
            "submit_label": self.submit_label,
            "location_mode": self.location_mode,
            "callback_eta_minutes": self.callback_eta_minutes,
            "fields": [f.to_public() for f in self.fields if f.type is not FieldType.HIDDEN],
            "hidden_fields": [f.name for f in self.fields if f.type is FieldType.HIDDEN],
        }


VEHICLE_TYPES: tuple[Option, ...] = (
    Option("tractor", "Седельный тягач"),
    Option("truck", "Грузовик (бортовой, фургон)"),
    Option("dump", "Самосвал"),
    Option("semitrailer", "Полуприцеп / прицеп"),
    Option("special", "Спецтехника"),
)

YES_NO_UNKNOWN = (Option("yes", "Да"), Option("no", "Нет"), Option("unknown", "Не знаю"))

# --- shared field definitions ------------------------------------------------------------
NAME = FieldSpec("name", FieldType.TEXT, "Ваше имя", required=True, target="column", max_length=120, placeholder="Иван")
PHONE = FieldSpec(
    "phone",
    FieldType.PHONE,
    "Телефон",
    required=True,
    target="column",
    placeholder="+7 (___) ___-__-__",
    mask="+7 (999) 999-99-99",
)
EMAIL = FieldSpec(
    "email",
    FieldType.EMAIL,
    "E-mail",
    target="column",
    max_length=254,
    help="Пришлём подтверждение и уведомления о статусе заявки",
)
TELEGRAM = FieldSpec(
    "telegram_username",
    FieldType.TELEGRAM,
    "Telegram (@username)",
    target="column",
    help="Необязательно. Укажите ник и нажмите «Start» в нашем боте — статусы заявки будут приходить туда",
)
BRAND = FieldSpec(
    "vehicle_brand",
    FieldType.TEXT,
    "Марка техники",
    required=True,
    target="column",
    max_length=64,
    options_source="calculator.brands",
    placeholder="Например, MAN",
)
BRAND_OPTIONAL = FieldSpec(
    "vehicle_brand", FieldType.TEXT, "Марка техники", target="column", max_length=64, options_source="calculator.brands"
)
VEHICLE_TYPE = FieldSpec("vehicle_type", FieldType.SELECT, "Тип техники", target="column", options=VEHICLE_TYPES)
PHOTOS = FieldSpec(
    "photos",
    FieldType.FILES,
    "Фото неисправности",
    target="meta",
    max_files=5,
    help="До 5 фото, JPG/PNG/WebP/HEIC, до 5 МБ каждое. Геометки из фото удаляются",
)
CONSENT = FieldSpec(
    "consent", FieldType.CONSENT, "Согласен(на) на обработку персональных данных", required=True, target="meta"
)
HIDDEN = (
    FieldSpec("service_slug", FieldType.HIDDEN, "Услуга", target="column", max_length=64),
    FieldSpec("estimate_id", FieldType.UUID, "Расчёт калькулятора", target="column"),
    FieldSpec("source", FieldType.HIDDEN, "Источник", target="meta", max_length=16),
    FieldSpec("form_token", FieldType.HIDDEN, "Токен формы", target="meta", max_length=200),
    FieldSpec("website", FieldType.HIDDEN, "Honeypot", target="meta", max_length=200),
)
LOCATION = FieldSpec(
    "location",
    FieldType.GEO_POINT,
    "Где находится техника",
    required=True,
    target="column",
    help="Поставьте точку на карте или разрешите геолокацию; адрес — по желанию",
)


def _common(*fields: FieldSpec, email: FieldSpec = EMAIL) -> tuple[FieldSpec, ...]:
    return (NAME, PHONE, *fields, email, TELEGRAM, CONSENT, *HIDDEN)


FORMS: dict[LeadType, FormSchema] = {
    LeadType.REPAIR: FormSchema(
        form_type=LeadType.REPAIR,
        title="Запись на ремонт в СТО",
        description="Опишите проблему — мастер перезвонит и согласует время заезда",
        submit_label="Записаться на ремонт",
        callback_eta_minutes=10,
        success_message="Заявка принята. Мастер перезвонит, чтобы согласовать время заезда.",
        fields=_common(
            BRAND,
            VEHICLE_TYPE,
            FieldSpec(
                "description",
                FieldType.TEXTAREA,
                "Что случилось",
                required=True,
                target="column",
                max_length=2000,
                placeholder="Опишите симптомы неисправности",
            ),
            FieldSpec(
                "preferred_at",
                FieldType.DATETIME,
                "Желаемые дата и время заезда",
                help="Необязательно. Время по Саратову",
            ),
            PHOTOS,
        ),
    ),
    LeadType.ONSITE: FormSchema(
        form_type=LeadType.ONSITE,
        title="Вызов мастера на место",
        description="Приедем с инструментом и ходовыми запчастями",
        submit_label="Вызвать мастера",
        location_mode="onsite",
        callback_eta_minutes=3,
        success_message="Заявка принята. Диспетчер перезвонит в течение нескольких минут.",
        fields=_common(
            LOCATION,
            BRAND,
            VEHICLE_TYPE,
            FieldSpec("is_drivable", FieldType.SELECT, "Машина на ходу?", required=True, options=YES_NO_UNKNOWN),
            FieldSpec(
                "description",
                FieldType.TEXTAREA,
                "Что случилось",
                required=True,
                target="column",
                max_length=2000,
                placeholder="Например: не заводится, горит ошибка ABS",
            ),
            PHOTOS,
        ),
    ),
    LeadType.TOW: FormSchema(
        form_type=LeadType.TOW,
        title="Вызов грузового эвакуатора",
        description="Перевезём технику к нам на СТО или по вашему адресу",
        submit_label="Вызвать эвакуатор",
        location_mode="onsite",
        callback_eta_minutes=3,
        success_message="Заявка принята. Диспетчер перезвонит и уточнит детали погрузки.",
        fields=_common(
            LOCATION,
            FieldSpec(
                "destination",
                FieldType.SELECT,
                "Куда везти",
                required=True,
                options=(Option("our_sto", "К вам на СТО"), Option("other_address", "По другому адресу")),
            ),
            FieldSpec(
                "destination_address",
                FieldType.TEXT,
                "Адрес назначения",
                max_length=300,
                required_if={"destination": "other_address"},
            ),
            FieldSpec("is_drivable", FieldType.SELECT, "Машина на ходу?", required=True, options=YES_NO_UNKNOWN),
            FieldSpec(
                "vehicle_type", FieldType.SELECT, "Тип техники", required=True, target="column", options=VEHICLE_TYPES
            ),
            FieldSpec(
                "dimensions",
                FieldType.TEXT,
                "Габариты / масса",
                max_length=200,
                placeholder="Например: тягач с полуприцепом, 16 м, 18 т",
            ),
            BRAND_OPTIONAL,
            FieldSpec("description", FieldType.TEXTAREA, "Комментарий", target="column", max_length=2000),
            PHOTOS,
        ),
    ),
    LeadType.PARTS: FormSchema(
        form_type=LeadType.PARTS,
        title="Заказ запчасти",
        description="Подберём оригинал или аналог под ваш бюджет",
        submit_label="Подобрать запчасть",
        callback_eta_minutes=15,
        success_message="Заявка принята. Менеджер подберёт деталь и перезвонит.",
        fields=_common(
            BRAND,
            FieldSpec(
                "description",
                FieldType.TEXTAREA,
                "Какая деталь нужна",
                required=True,
                target="column",
                max_length=2000,
                placeholder="Название, номер по каталогу или описание",
            ),
            FieldSpec("vin", FieldType.VIN, "VIN", help="Необязательно, ускорит подбор"),
            FieldSpec(
                "urgency",
                FieldType.SELECT,
                "Срочность",
                required=True,
                options=(
                    Option("today", "Нужна сегодня"),
                    Option("this_week", "На этой неделе"),
                    Option("not_urgent", "Не срочно"),
                ),
            ),
            FieldSpec(
                "delivery",
                FieldType.SELECT,
                "Получение",
                required=True,
                options=(Option("delivery", "Доставка"), Option("pickup", "Самовывоз")),
            ),
            FieldSpec(
                "delivery_address",
                FieldType.TEXT,
                "Адрес доставки",
                max_length=300,
                required_if={"delivery": "delivery"},
            ),
            PHOTOS,
        ),
    ),
    LeadType.CORPORATE: FormSchema(
        form_type=LeadType.CORPORATE,
        title="Обслуживание автопарка",
        description="Подготовим коммерческое предложение под размер и состав вашего парка",
        submit_label="Получить предложение",
        callback_eta_minutes=60,
        success_message="Заявка принята. Менеджер по работе с юрлицами свяжется с вами в рабочее время.",
        fields=(
            FieldSpec("company_name", FieldType.TEXT, "Название компании", required=True, max_length=200),
            FieldSpec("inn", FieldType.INN, "ИНН", help="Необязательно. 10 цифр для организации, 12 — для ИП"),
            FieldSpec(
                "fleet_size",
                FieldType.INTEGER,
                "Сколько единиц техники в парке",
                required=True,
                min_value=1,
                max_value=10000,
            ),
            FieldSpec("fleet_types", FieldType.MULTISELECT, "Типы техники", options=VEHICLE_TYPES),
            FieldSpec("name", FieldType.TEXT, "Контактное лицо", required=True, target="column", max_length=120),
            PHONE,
            FieldSpec("email", FieldType.EMAIL, "Рабочий e-mail", required=True, target="column", max_length=254),
            FieldSpec(
                "description",
                FieldType.TEXTAREA,
                "Комментарий",
                target="column",
                max_length=2000,
                placeholder="Регион работы, текущие задачи, интересующие услуги",
            ),
            TELEGRAM,
            CONSENT,
            *HIDDEN,
        ),
    ),
    LeadType.CALLBACK: FormSchema(
        form_type=LeadType.CALLBACK,
        title="Перезвоните мне",
        description="Оставьте номер — перезвоним и ответим на вопросы",
        submit_label="Перезвоните мне",
        callback_eta_minutes=5,
        success_message="Спасибо! Перезвоним в ближайшие минуты.",
        fields=(NAME, PHONE, CONSENT, *HIDDEN),
    ),
}

# Not a public form: created by the chat assistant on handoff.
CHAT_HANDOFF_FORM = FormSchema(
    form_type=LeadType.CHAT_HANDOFF,
    title="Запрос из чата",
    description="",
    submit_label="",
    callback_eta_minutes=5,
    success_message="Передали ваш запрос оператору — он перезвонит.",
    public=False,
    fields=(),
)


def get_form(form_type: str) -> FormSchema | None:
    try:
        return FORMS.get(LeadType(form_type))
    except ValueError:
        return None


def form_for_lead_type(lead_type: LeadType) -> FormSchema:
    return CHAT_HANDOFF_FORM if lead_type is LeadType.CHAT_HANDOFF else FORMS[lead_type]


def all_wire_fields() -> dict[str, FieldSpec]:
    """Every field name any form accepts (used to document the multipart body in OpenAPI)."""
    result: dict[str, FieldSpec] = {}
    for form in FORMS.values():
        for spec in form.fields:
            result.setdefault(spec.name, spec)
    return result
