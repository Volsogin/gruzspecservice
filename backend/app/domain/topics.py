"""Chat topics ("темы"): deterministic keyword classifier + per-topic suggested replies."""

from __future__ import annotations

import re
from enum import StrEnum


class Topic(StrEnum):
    SERVICES = "services"
    PRICING = "pricing"
    DISPATCH = "dispatch"
    PARTS = "parts"
    CORPORATE = "corporate"
    WARRANTY = "warranty"
    OTHER = "other"


_KEYWORDS: dict[Topic, tuple[str, ...]] = {
    Topic.DISPATCH: (
        "выезд",
        "приед",
        "эвакуат",
        "сломал",
        "заглох",
        "не завод",
        "на трасс",
        "на дорог",
        "место полом",
        "срочно",
        "колесо",
        "встал",
        "стою",
        "буксир",
    ),
    Topic.PRICING: (
        "цен",
        "стоим",
        "сколько стоит",
        "стоит",
        "сколько будет стоить",
        "сколько будет",
        "прайс",
        "руб",
        "₽",
        "дорого",
        "калькул",
        "расчёт",
        "расчет",
        "почём",
        "почем",
    ),
    Topic.PARTS: ("запчаст", "детал", "аккумулятор", "колодк", "фильтр", "в наличии", "артикул", "vin", "масло"),
    Topic.CORPORATE: (
        "юрлиц",
        "юр лиц",
        "юридическ",
        "договор",
        "ндс",
        "автопарк",
        "парк ",
        "флот",
        "безнал",
        "отсрочк",
        "компани",
        "организац",
        "ооо",
        " ип ",
    ),
    Topic.WARRANTY: ("гаранти", "возврат", "претензи", "повторно слом"),
    Topic.SERVICES: (
        "ремонт",
        "диагност",
        "двигател",
        "ходов",
        "тормоз",
        "кпп",
        "коробк",
        "сцеплен",
        "пневм",
        "топлив",
        "форсун",
        "электри",
        "отогрев",
        "услуг",
        "сто",
        "то ",
        "обслуживан",
    ),
}

SUGGESTED_REPLIES: dict[Topic, list[str]] = {
    Topic.SERVICES: ["Какие услуги есть на выезде?", "Записаться на ремонт", "Сколько стоит диагностика?"],
    Topic.PRICING: ["Рассчитать стоимость", "Цена диагностики MAN", "Оставить заявку"],
    Topic.DISPATCH: ["Вызвать мастера", "Приедете за 30 минут?", "Нужен эвакуатор"],
    Topic.PARTS: ["Заказать запчасть", "Есть доставка?", "Оригинал или аналог?"],
    Topic.CORPORATE: ["Работаете с НДС?", "Обслуживание автопарка", "Есть отсрочка платежа?"],
    Topic.WARRANTY: ["Какая гарантия?", "Позвать оператора", "Контакты"],
    Topic.OTHER: ["Вызвать мастера", "Услуги и цены", "Адрес и режим работы"],
}

_WORD = re.compile(r"\s+")


def detect_topic(text: str, previous: Topic | None = None) -> Topic:
    """Best-scoring topic by keyword hits; falls back to the previous topic for short follow-ups."""
    lowered = f" {_WORD.sub(' ', text.lower())} "
    scores = {topic: sum(1 for kw in kws if kw in lowered) for topic, kws in _KEYWORDS.items()}
    best = max(scores, key=lambda t: scores[t])
    if scores[best] == 0:
        return previous or Topic.OTHER
    return best


_HUMAN = r"(человек\w*|менеджер\w*|консультант\w*|сотрудник\w*|оператор\w*)"
_OPERATOR_PATTERNS = re.compile(
    r"(оператор|жив\w*\s+"
    + _HUMAN
    + r"|позов\w*\s+"
    + _HUMAN
    + r"|свяж\w*(\s+меня)?\s+(с\s+)?"
    + _HUMAN
    + r"|(нужен|нужна|хочу|дайте|соедин\w*)\s+(с\s+|со\s+)?"
    + _HUMAN
    + r"|не\s+(хочу|буду)\s+(общаться\s+)?(с\s+)?бот"
    + r"|переключ\w*\s+на\s+"
    + _HUMAN
    + r"|позвать\s+"
    + _HUMAN
    + r")",
    re.IGNORECASE,
)


def asks_for_operator(text: str) -> bool:
    """True when the user explicitly asks for a human. Handoff happens only on such request."""
    return bool(_OPERATOR_PATTERNS.search(text))
