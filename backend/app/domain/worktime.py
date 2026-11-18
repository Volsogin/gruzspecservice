"""Working hours evaluated in the company timezone (default Europe/Saratov, 24/7)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass(frozen=True)
class WorkStatus:
    is_open: bool
    mode: str
    label: str
    timezone: str
    local_time: str

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def work_status(hours: dict[str, Any], tz_name: str, now: datetime | None = None) -> WorkStatus:
    """`hours` is `{"mode": "24/7"}` or `{"mode": "schedule", "schedule": {"mon": ["08:00", "20:00"], ...}}`."""
    tz = ZoneInfo(tz_name)
    local = (now or datetime.now(tz)).astimezone(tz)
    stamp = local.isoformat(timespec="minutes")
    mode = str(hours.get("mode", "24/7"))
    if mode == "24/7":
        return WorkStatus(True, mode, "Работаем круглосуточно, без выходных", tz_name, stamp)

    schedule: dict[str, list[str]] = hours.get("schedule") or {}
    today = schedule.get(_DAYS[local.weekday()])
    if today and len(today) == 2:
        start, end = time.fromisoformat(today[0]), time.fromisoformat(today[1])
        current = local.time()
        is_open = start <= current < end if start < end else (current >= start or current < end)
        if is_open:
            return WorkStatus(True, mode, f"Открыто до {today[1]}", tz_name, stamp)
        return WorkStatus(False, mode, f"Сегодня работаем {today[0]}–{today[1]}", tz_name, stamp)
    return WorkStatus(False, mode, "Сегодня выходной — оставьте заявку, перезвоним", tz_name, stamp)
