"""Russian phone numbers: normalization to E.164 (+7XXXXXXXXXX) and masking."""

from __future__ import annotations

import re

_NON_DIGITS = re.compile(r"\D+")
_FREE_TEXT_PHONE = re.compile(r"(?:\+7|8|7)?[\s\-()]*\d{3}[\s\-()]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}")
# Russian numbering plan: area/operator codes start with 3, 4, 8 or 9.
_VALID_FIRST = set("3489")


class InvalidPhone(ValueError):
    pass


def normalize_phone(raw: str) -> str:
    """Return `+7XXXXXXXXXX` or raise InvalidPhone.

    Accepts `+7 (960) 355-57-65`, `8 960 355 57 65`, `9603555765` and similar.
    """
    if not raw or len(raw) > 32:
        raise InvalidPhone("Укажите телефон в формате +7 XXX XXX XX XX")
    if any(ch.isalpha() for ch in raw):
        raise InvalidPhone("Укажите телефон в формате +7 XXX XXX XX XX")
    digits = _NON_DIGITS.sub("", raw)
    if len(digits) == 11 and digits[0] in "78":
        national = digits[1:]
    elif len(digits) == 10:
        national = digits
    else:
        raise InvalidPhone("Укажите телефон в формате +7 XXX XXX XX XX")
    if raw.strip().startswith("+") and not raw.strip().startswith("+7"):
        raise InvalidPhone("Принимаем номера российских операторов (+7)")
    if national[0] not in _VALID_FIRST:
        raise InvalidPhone("Похоже, в номере ошибка — проверьте код оператора")
    return f"+7{national}"


def mask_phone(e164: str) -> str:
    """`+79603555765` → `+7 *** *** 57 65`."""
    digits = _NON_DIGITS.sub("", e164)
    if len(digits) < 4:
        return "***"
    return f"+7 *** *** {digits[-4:-2]} {digits[-2:]}"


def format_phone(e164: str) -> str:
    """`+79603555765` → `+7 960 355-57-65` (for operators)."""
    d = _NON_DIGITS.sub("", e164)
    if len(d) != 11:
        return e164
    return f"+7 {d[1:4]} {d[4:7]}-{d[7:9]}-{d[9:11]}"


def extract_phone(text: str) -> str | None:
    """Find the first valid phone number in free text (chat messages)."""
    for match in _FREE_TEXT_PHONE.finditer(text):
        try:
            return normalize_phone(match.group(0))
        except InvalidPhone:
            continue
    return None
