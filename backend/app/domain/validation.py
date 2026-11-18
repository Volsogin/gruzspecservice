"""LeadValidator — the single validation pipeline behind `POST /leads`.

Pipeline: resolve form schema → anti-spam honeypot → per-field coercion (phone normalization,
e-mail, selects, INN checksum, geo point, …) → conditional requirements → consent.
Errors from all fields are collected and returned together as `fields` in the 422 response.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from email_validator import EmailNotValidError, validate_email

from app.core.errors import AppError, ValidationFailed
from app.domain.forms import FieldSpec, FieldType, FormSchema, get_form
from app.domain.inn import is_valid_inn
from app.domain.phone import InvalidPhone, normalize_phone
from app.domain.statuses import LeadType

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_TG_USERNAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")
_VIN = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
_TRUE = {"true", "1", "on", "yes", "да"}
_FALSE = {"false", "0", "off", "no", "нет"}
_ALLOWED_SOURCES = {"form", "calculator", "chatbot"}


class _FieldError(ValueError):
    pass


@dataclass
class ValidatedLead:
    lead_type: LeadType
    columns: dict[str, Any] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)
    source: str = "form"
    form_token: str | None = None
    consent: bool = False


def clean_text(value: str, max_length: int | None) -> str:
    text = _CONTROL_CHARS.sub("", value).strip()
    if max_length is not None and len(text) > max_length:
        raise _FieldError(f"Не длиннее {max_length} символов")
    return text


def _as_str(raw: Any) -> str:
    if isinstance(raw, bool):
        return "true" if raw else "false"
    if isinstance(raw, int | float):
        return str(raw)
    if isinstance(raw, str):
        return raw
    raise _FieldError("Неверный формат значения")


def _is_empty(raw: Any) -> bool:
    return raw is None or (isinstance(raw, str) and not raw.strip()) or (isinstance(raw, list) and not raw)


class LeadValidator:
    """Validates raw form data against the schema of a lead type."""

    def __init__(self, timezone: str = "Europe/Saratov", now: Callable[[], datetime] | None = None) -> None:
        self._tz = ZoneInfo(timezone)
        self._now = now or (lambda: datetime.now(self._tz))

    def resolve_form(self, lead_type: Any) -> FormSchema:
        form = get_form(str(lead_type)) if lead_type else None
        if form is None or not form.public:
            raise ValidationFailed("Неизвестный тип заявки", fields={"lead_type": "Выберите тип заявки"})
        return form

    def validate(self, data: Mapping[str, Any]) -> ValidatedLead:
        """Validate a flat mapping of form values (strings, or JSON-native types)."""
        form = self.resolve_form(data.get("lead_type"))
        if not _is_empty(data.get("website")):
            # Honeypot: humans never see this field.
            raise AppError("Заявка не принята. Позвоните нам по телефону.", code="rejected", status_code=400)

        result = ValidatedLead(lead_type=form.form_type)
        errors: dict[str, str] = {}
        for spec in form.fields:
            if spec.type is FieldType.FILES:
                continue
            try:
                self._apply_field(spec, data, result)
            except _FieldError as exc:
                errors[spec.name] = str(exc)

        for spec in form.fields:  # conditional requirements need all values parsed first
            if spec.required_if and spec.name not in errors:
                ((dep, expected),) = spec.required_if.items()
                actual = result.details.get(dep, result.columns.get(dep))
                if actual == expected and _is_empty(result.details.get(spec.name, result.columns.get(spec.name))):
                    errors[spec.name] = "Обязательное поле"
        if errors:
            raise ValidationFailed("Проверьте правильность заполнения полей", fields=errors)
        return result

    # --- per-field ---------------------------------------------------------------------------
    def _apply_field(self, spec: FieldSpec, data: Mapping[str, Any], out: ValidatedLead) -> None:
        if spec.type is FieldType.GEO_POINT:
            self._apply_geo(spec, data, out)
            return
        raw = data.get(spec.name)
        if _is_empty(raw):
            if spec.required:
                raise _FieldError(
                    "Необходимо согласие на обработку персональных данных"
                    if spec.type is FieldType.CONSENT
                    else "Обязательное поле"
                )
            return
        value = self._coerce(spec, raw)
        if spec.name == "website":
            return
        if spec.type is FieldType.CONSENT:
            out.consent = bool(value)
        elif spec.name == "source":
            out.source = value if value in _ALLOWED_SOURCES else "form"
        elif spec.name == "form_token":
            out.form_token = value
        elif spec.target == "column":
            out.columns[spec.name] = value
        elif spec.target == "details":
            out.details[spec.name] = value

    def _coerce(self, spec: FieldSpec, raw: Any) -> Any:
        t = spec.type
        if t is FieldType.MULTISELECT:
            items = raw if isinstance(raw, list) else [p for p in _as_str(raw).split(",")]
            values = [clean_text(_as_str(i), 64) for i in items if _as_str(i).strip()]
            allowed = {o.value for o in spec.options}
            if any(v not in allowed for v in values):
                raise _FieldError("Выберите значения из списка")
            return sorted(set(values))
        text = _as_str(raw)
        if t in (FieldType.TEXT, FieldType.TEXTAREA, FieldType.HIDDEN):
            return clean_text(text, spec.max_length)
        if t is FieldType.PHONE:
            try:
                return normalize_phone(text)
            except InvalidPhone as exc:
                raise _FieldError(str(exc)) from exc
        if t is FieldType.EMAIL:
            try:
                return validate_email(text.strip(), check_deliverability=False).normalized.lower()
            except EmailNotValidError as exc:
                raise _FieldError("Проверьте адрес e-mail") from exc
        if t is FieldType.TELEGRAM:
            username = text.strip().removeprefix("https://t.me/").lstrip("@")
            if not _TG_USERNAME.match(username):
                raise _FieldError("Имя пользователя Telegram: 5–32 символа, латиница, цифры и _")
            return username
        if t is FieldType.SELECT:
            value = text.strip()
            if value not in {o.value for o in spec.options}:
                raise _FieldError("Выберите значение из списка")
            return value
        if t is FieldType.BOOLEAN:
            return self._bool(text)
        if t is FieldType.CONSENT:
            if not self._bool(text):
                raise _FieldError("Необходимо согласие на обработку персональных данных")
            return True
        if t is FieldType.INTEGER:
            try:
                number = int(text.strip())
            except ValueError as exc:
                raise _FieldError("Введите целое число") from exc
            if spec.min_value is not None and number < spec.min_value:
                raise _FieldError(f"Не меньше {spec.min_value}")
            if spec.max_value is not None and number > spec.max_value:
                raise _FieldError(f"Не больше {spec.max_value}")
            return number
        if t is FieldType.INN:
            inn = re.sub(r"\s+", "", text)
            if not is_valid_inn(inn):
                raise _FieldError("ИНН не прошёл проверку: 10 цифр для организации или 12 для ИП")
            return inn
        if t is FieldType.VIN:
            vin = re.sub(r"[\s-]+", "", text).upper()
            if not _VIN.match(vin):
                raise _FieldError("VIN — 17 символов: латинские буквы (кроме I, O, Q) и цифры")
            return vin
        if t is FieldType.DATETIME:
            return self._datetime(text)
        if t is FieldType.UUID:
            try:
                return uuid.UUID(text.strip())
            except ValueError as exc:
                raise _FieldError("Неверный идентификатор") from exc
        raise _FieldError("Неподдерживаемое поле")  # pragma: no cover

    @staticmethod
    def _bool(text: str) -> bool:
        lowered = text.strip().lower()
        if lowered in _TRUE:
            return True
        if lowered in _FALSE:
            return False
        raise _FieldError("Ожидается да/нет")

    def _datetime(self, text: str) -> str:
        try:
            value = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise _FieldError("Дата в формате ГГГГ-ММ-ДДTЧЧ:ММ") from exc
        if value.tzinfo is None:
            value = value.replace(tzinfo=self._tz)
        now = self._now()
        if value < now - timedelta(hours=1):
            raise _FieldError("Дата уже прошла")
        if value > now + timedelta(days=90):
            raise _FieldError("Запись открыта на 90 дней вперёд")
        return value.astimezone(self._tz).isoformat(timespec="minutes")

    def _apply_geo(self, spec: FieldSpec, data: Mapping[str, Any], out: ValidatedLead) -> None:
        lat_raw, lon_raw = data.get("lat"), data.get("lon")
        address_raw = data.get("address")
        if _is_empty(lat_raw) or _is_empty(lon_raw):
            if spec.required:
                raise _FieldError("Отметьте точку на карте")
            return
        try:
            lat, lon = float(_as_str(lat_raw)), float(_as_str(lon_raw))
        except ValueError as exc:
            raise _FieldError("Неверные координаты") from exc
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise _FieldError("Неверные координаты")
        out.columns["lat"] = round(lat, 6)
        out.columns["lon"] = round(lon, 6)
        if not _is_empty(address_raw):
            out.columns["address"] = clean_text(_as_str(address_raw), 300)
