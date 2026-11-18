"""Tools available to the LLM. Arguments from the model are untrusted input and validated here."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.core.errors import AppError
from app.domain.dispatch import check_point
from app.integrations.geocoder.dgis import Geocoder
from app.services.calculator import create_estimate, estimate_to_dict

if TYPE_CHECKING:
    from app.services.chat.service import ChatService, TurnContext

logger = logging.getLogger(__name__)

CHAT_LEAD_TYPES = ("callback", "repair", "parts")


def tool_definitions(work_types: list[str], vehicle_types: list[str]) -> list[dict[str, Any]]:
    def fn(
        name: str, description: str, properties: dict[str, Any], required: list[str] | None = None
    ) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required or [],
                    "additionalProperties": False,
                },
            },
        }

    return [
        fn("get_services", "Список услуг автосервиса с короткими описаниями.", {}),
        fn("get_contacts", "Телефон, адрес СТО, режим работы, мессенджеры.", {}),
        fn(
            "calculate_price",
            "Ориентировочная цена «от N ₽». ЕДИНСТВЕННЫЙ источник цен.",
            {
                "brand": {"type": "string", "description": "Марка техники, например MAN, КамАЗ, Shacman"},
                "work_type": {"type": "string", "enum": work_types},
                "vehicle_type": {"type": "string", "enum": vehicle_types},
                "urgent": {"type": "boolean"},
                "onsite": {"type": "boolean", "description": "Работы с выездом к месту поломки"},
            },
            ["brand", "work_type"],
        ),
        fn(
            "check_dispatch_zone",
            "Проверить, успеем ли приехать за 30 минут. Нужны координаты или адрес.",
            {
                "lat": {"type": "number"},
                "lon": {"type": "number"},
                "address": {"type": "string", "description": "Адрес или ориентир, если координат нет"},
            },
        ),
        fn(
            "create_lead",
            "Создать заявку (обратный звонок, ремонт на СТО, запчасти) после согласия клиента. "
            "Для выезда/эвакуатора не используй — попроси отметить точку в форме на сайте.",
            {
                "lead_type": {"type": "string", "enum": list(CHAT_LEAD_TYPES)},
                "name": {"type": "string"},
                "phone": {"type": "string"},
                "vehicle_brand": {"type": "string"},
                "description": {"type": "string"},
            },
            ["lead_type", "phone"],
        ),
        fn(
            "request_operator",
            "Передать диалог живому оператору. Вызывай, только если клиент сам попросил "
            "человека/оператора или согласился на твоё предложение.",
            {
                "reason": {"type": "string"},
            },
        ),
    ]


@dataclass
class ToolOutcome:
    result: dict[str, Any]
    events: list[dict[str, Any]] = field(default_factory=list)


class ChatTools:
    def __init__(self, service: ChatService, ctx: TurnContext, geocoder: Geocoder | None) -> None:
        self.service = service
        self.ctx = ctx
        self.geocoder = geocoder

    async def execute(self, name: str, raw_arguments: str) -> ToolOutcome:
        try:
            args = json.loads(raw_arguments or "{}")
            if not isinstance(args, dict):
                raise ValueError("arguments must be an object")
        except ValueError:
            return ToolOutcome({"error": "invalid_arguments"})
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:
            return ToolOutcome({"error": "unknown_tool"})
        try:
            outcome: ToolOutcome = await handler(args)
            return outcome
        except AppError as exc:
            return ToolOutcome({"error": exc.code, "message": exc.message, "fields": exc.fields})

    async def _tool_get_services(self, _: dict[str, Any]) -> ToolOutcome:
        return ToolOutcome(
            {
                "services": [
                    {
                        "slug": s["slug"],
                        "title": s["title"],
                        "description": s["short_description"],
                        "form_type": s["form_type"],
                    }
                    for s in self.ctx.kb.services
                ]
            }
        )

    async def _tool_get_contacts(self, _: dict[str, Any]) -> ToolOutcome:
        return ToolOutcome(self.ctx.kb.contacts(), [{"event": "action", "data": {"type": "show_map"}}])

    async def _tool_calculate_price(self, args: dict[str, Any]) -> ToolOutcome:
        async with self.service.session_factory() as session:
            row = await create_estimate(
                session,
                brand=str(args.get("brand", ""))[:64],
                work_type=str(args.get("work_type", ""))[:64],
                vehicle_type=(str(args["vehicle_type"])[:64] if args.get("vehicle_type") else None),
                urgent=bool(args.get("urgent")),
                onsite=bool(args.get("onsite")),
            )
            await session.commit()
        data = estimate_to_dict(row, self.ctx.kb.site.pricing_rules().disclaimer)
        self.ctx.topic_override = "pricing"
        return ToolOutcome(
            {
                "price_from": data["price_from"],
                "price_label": data["price_label"],
                "disclaimer": data["disclaimer"],
                "breakdown": data["breakdown"],
            },
            [{"event": "estimate", "data": data}],
        )

    async def _tool_check_dispatch_zone(self, args: dict[str, Any]) -> ToolOutcome:
        cfg = self.ctx.kb.site.dispatch_config()
        lat, lon = args.get("lat"), args.get("lon")
        if (lat is None or lon is None) and args.get("address") and self.geocoder is not None:
            found = await self.geocoder.geocode(str(args["address"])[:200], limit=1)
            if found:
                lat, lon = found[0].lat, found[0].lon
        if not isinstance(lat, int | float) or not isinstance(lon, int | float):
            return ToolOutcome(
                {
                    "radius_km": cfg.effective_radius_km,
                    "eta_minutes": cfg.eta_minutes,
                    "hint": "Точных координат нет. Попроси отметить точку на карте в форме вызова мастера.",
                },
                [
                    {
                        "event": "action",
                        "data": {"type": "open_form", "form_type": "onsite", "prefill": {"lead_type": "onsite"}},
                    }
                ],
            )
        check = check_point(cfg, float(lat), float(lon))
        return ToolOutcome(
            {
                "zone": check.zone.value,
                "distance_km": check.distance_km,
                "eta_minutes": check.eta_minutes,
                "message": check.message,
            }
        )

    async def _tool_create_lead(self, args: dict[str, Any]) -> ToolOutcome:
        lead_type = str(args.get("lead_type", "callback"))
        if lead_type not in CHAT_LEAD_TYPES:
            return ToolOutcome(
                {"error": "use_form", "message": "Для выезда и эвакуатора нужна точка на карте — открой форму."},
                [
                    {
                        "event": "action",
                        "data": {"type": "open_form", "form_type": lead_type, "prefill": {"lead_type": lead_type}},
                    }
                ],
            )
        if self.ctx.chat.consent_at is None:
            return ToolOutcome(
                {
                    "error": "consent_required",
                    "message": "Попроси клиента отметить согласие на обработку персональных данных.",
                },
                [{"event": "action", "data": {"type": "consent_required"}}],
            )
        body = await self.service.create_lead_from_chat(
            self.ctx,
            {
                "lead_type": lead_type,
                "name": args.get("name") or self.ctx.chat.name or "Клиент из чата",
                "phone": args.get("phone") or self.ctx.chat.phone or "",
                "vehicle_brand": args.get("vehicle_brand") or "",
                "description": args.get("description") or "",
            },
        )
        return ToolOutcome(
            {
                "number": body["number"],
                "status": body["status_label"],
                "callback_eta_minutes": body["callback_eta_minutes"],
            },
            [{"event": "action", "data": {"type": "lead_created", "lead": body}}],
        )

    async def _tool_request_operator(self, args: dict[str, Any]) -> ToolOutcome:
        text, events = await self.service.request_operator(self.ctx, reason=str(args.get("reason") or "")[:200])
        self.ctx.handoff_text = text
        return ToolOutcome({"status": self.ctx.chat.status, "say_to_user": text}, events)
