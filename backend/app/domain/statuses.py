"""Lead lifecycle: statuses, human labels and allowed transitions."""

from __future__ import annotations

from enum import StrEnum


class LeadType(StrEnum):
    REPAIR = "repair"
    ONSITE = "onsite"
    TOW = "tow"
    PARTS = "parts"
    CORPORATE = "corporate"
    CALLBACK = "callback"
    CHAT_HANDOFF = "chat_handoff"


DISPATCH_TYPES = frozenset({LeadType.ONSITE, LeadType.TOW})


class LeadStatus(StrEnum):
    NEW = "new"
    ACCEPTED = "accepted"
    ON_THE_WAY = "on_the_way"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


STATUS_LABELS: dict[LeadStatus, str] = {
    LeadStatus.NEW: "Заявка получена",
    LeadStatus.ACCEPTED: "Принята мастером",
    LeadStatus.ON_THE_WAY: "Мастер выехал к вам",
    LeadStatus.IN_PROGRESS: "Работы выполняются",
    LeadStatus.COMPLETED: "Готово",
    LeadStatus.CANCELLED: "Отменена",
}

# Short verbs for operator buttons (Telegram / admin).
STATUS_ACTIONS: dict[LeadStatus, str] = {
    LeadStatus.ACCEPTED: "✅ Принять",
    LeadStatus.ON_THE_WAY: "🚚 Выехали",
    LeadStatus.IN_PROGRESS: "🔧 В работе",
    LeadStatus.COMPLETED: "🏁 Готово",
    LeadStatus.CANCELLED: "✖ Отменить",
}

TERMINAL = frozenset({LeadStatus.COMPLETED, LeadStatus.CANCELLED})

_FORWARD: dict[LeadStatus, tuple[LeadStatus, ...]] = {
    LeadStatus.NEW: (LeadStatus.ACCEPTED,),
    LeadStatus.ACCEPTED: (LeadStatus.ON_THE_WAY, LeadStatus.IN_PROGRESS),
    LeadStatus.ON_THE_WAY: (LeadStatus.IN_PROGRESS,),
    LeadStatus.IN_PROGRESS: (LeadStatus.COMPLETED,),
}

LEAD_TYPE_LABELS: dict[LeadType, str] = {
    LeadType.REPAIR: "Ремонт на СТО",
    LeadType.ONSITE: "Выезд мастера",
    LeadType.TOW: "Эвакуатор",
    LeadType.PARTS: "Запчасти",
    LeadType.CORPORATE: "Корпоративное обслуживание",
    LeadType.CALLBACK: "Обратный звонок",
    LeadType.CHAT_HANDOFF: "Запрос из чата",
}


def status_label(status: str) -> str:
    try:
        return STATUS_LABELS[LeadStatus(status)]
    except ValueError:
        return status


def allowed_transitions(lead_type: str, current: str) -> list[LeadStatus]:
    """Statuses an operator may move the lead to next (in display order)."""
    status = LeadStatus(current)
    if status in TERMINAL:
        return []
    forward = [
        s for s in _FORWARD.get(status, ()) if s is not LeadStatus.ON_THE_WAY or LeadType(lead_type) in DISPATCH_TYPES
    ]
    return [*forward, LeadStatus.CANCELLED]


class InvalidTransition(ValueError):
    pass


def ensure_transition(lead_type: str, current: str, target: str) -> LeadStatus:
    """Validate a status change and return the target as enum."""
    try:
        target_status = LeadStatus(target)
    except ValueError as exc:
        raise InvalidTransition(f"Неизвестный статус: {target}") from exc
    if target_status not in allowed_transitions(lead_type, current):
        raise InvalidTransition(f"Нельзя перевести заявку из «{status_label(current)}» в «{status_label(target)}»")
    return target_status
