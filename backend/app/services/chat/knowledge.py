"""Knowledge base + rule-based FAQ answers (works without any LLM; used as the fallback mode)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PriceBrand, PriceWorkType
from app.domain.topics import SUGGESTED_REPLIES, Topic
from app.services.catalog import list_services
from app.services.site_settings import SiteSettings, load_settings

# keyword stem → price_work_types.slug (must match seeds/pricing.yaml)
WORK_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("диагност", "diagnostics"),
    ("компьютерн", "diagnostics"),
    ("плановое то", "maintenance"),
    ("техобслуж", "maintenance"),
    (" то ", "maintenance"),
    ("замена масл", "maintenance"),
    ("двигат", "engine"),
    ("мотор", "engine"),
    ("турбин", "engine"),
    ("ходов", "chassis"),
    ("подвеск", "chassis"),
    ("рессор", "chassis"),
    ("тормоз", "brakes"),
    ("колодк", "brakes"),
    ("abs", "brakes"),
    ("кпп", "transmission"),
    ("коробк", "transmission"),
    ("сцеплен", "transmission"),
    ("трансмис", "transmission"),
    ("пневм", "pneumatics"),
    ("воздух", "pneumatics"),
    ("топлив", "fuel"),
    ("форсун", "fuel"),
    ("тнвд", "fuel"),
    ("электри", "electrics"),
    ("проводк", "electrics"),
    ("блок управ", "electrics"),
    ("эвакуа", "towing"),
    ("выезд", "onsite"),
)


@dataclass
class KnowledgeBase:
    site: SiteSettings
    services: list[dict[str, Any]]
    brands: list[PriceBrand]
    work_types: dict[str, str]

    @classmethod
    async def load(cls, session: AsyncSession) -> KnowledgeBase:
        brands = list((await session.scalars(select(PriceBrand))).all())
        works = {w.slug: w.title for w in await session.scalars(select(PriceWorkType))}
        return cls(await load_settings(session), await list_services(session), brands, works)

    @property
    def phone(self) -> str:
        return str(self.site.section("contacts").get("phone_display") or self.site.section("contacts").get("phone", ""))

    @property
    def address(self) -> str:
        return str(self.site.section("address").get("text", ""))

    def contacts(self) -> dict[str, Any]:
        return {
            "company": self.site.company_name,
            "phone": self.phone,
            "address": self.address,
            "work_hours": self.site.work_status()["label"],
            "messengers": self.site.section("messengers"),
            "email": self.site.section("contacts").get("email"),
        }

    def brand_title(self, slug: str) -> str:
        return next((b.title for b in self.brands if b.slug == slug), slug)

    def find_brand(self, text: str) -> PriceBrand | None:
        lowered = f" {text.lower().replace('ё', 'е')} "
        for brand in sorted(self.brands, key=lambda b: -len(b.title)):
            for name in [brand.title, brand.slug, *(brand.aliases or [])]:
                n = name.lower().replace("ё", "е")
                if re.search(rf"(?<![\w]){re.escape(n)}(?![\w])", lowered):
                    return brand
        return None

    def find_work_type(self, text: str) -> str | None:
        lowered = f" {text.lower()} "
        for stem, slug in WORK_KEYWORDS:
            if stem in lowered and slug in self.work_types:
                return slug
        return None

    def prompt_facts(self) -> str:
        """Compact facts for the LLM system prompt."""
        dispatch = self.site.dispatch_config()
        services = "; ".join(s["title"] for s in self.services)
        warranty = self.site.section("warranty").get("text", "")
        return (
            f"Компания: {self.site.company_name}, ремонт грузовиков, полуприцепов и спецтехники.\n"
            f"Адрес СТО: {self.address}. Телефон: {self.phone}. Режим: {self.site.work_status()['label']}.\n"
            f"Услуги: {services}.\n"
            f"Выезд: в радиусе {dispatch.effective_radius_km:g} км от СТО — примерно за {dispatch.eta_minutes} минут; "
            f"дальше по области — время и стоимость уточняет диспетчер.\n"
            f"Гарантия: {warranty}\n"
            "Работаем с юрлицами: договор, НДС, безнал, отсрочка по договорённости."
        )


@dataclass
class FaqAnswer:
    text: str
    suggested_replies: list[str]
    actions: list[dict[str, Any]] = field(default_factory=list)
    estimate: dict[str, Any] | None = None


_GREETING = re.compile(r"^\s*(привет|здравств|добр(ый|ое|ого)|хай|hello|hi)\b", re.IGNORECASE)
_CONTACTS = (
    "адрес",
    "где наход",
    "где вы",
    "контакт",
    "телефон",
    "позвонить",
    "режим",
    "часы работ",
    "когда работ",
    "круглосуточ",
    "как доехать",
    "как проехать",
)


def _form_action(form_type: str, service_slug: str | None = None) -> dict[str, Any]:
    prefill: dict[str, Any] = {"lead_type": form_type}
    if service_slug:
        prefill["service_slug"] = service_slug
    return {"type": "open_form", "form_type": form_type, "prefill": prefill}


def faq_answer(kb: KnowledgeBase, text: str, topic: Topic, estimate: dict[str, Any] | None = None) -> FaqAnswer:
    """Deterministic answer by intent. `estimate` is precomputed by the caller when brand+work were found."""
    lowered = text.lower()
    replies = SUGGESTED_REPLIES[topic]
    dispatch = kb.site.dispatch_config()

    if _GREETING.match(text) and len(text) < 40:
        return FaqAnswer(
            f"Здравствуйте! Я помощник {kb.site.company_name}. Подскажу по услугам, ценам и выезду мастера. "
            "Что случилось с техникой?",
            SUGGESTED_REPLIES[Topic.OTHER],
        )
    if any(k in lowered for k in _CONTACTS):
        c = kb.contacts()
        return FaqAnswer(
            f"Мы находимся по адресу: {c['address']}. Телефон: {c['phone']}. {c['work_hours']}.",
            ["Вызвать мастера", "Записаться на ремонт", "Услуги и цены"],
            [{"type": "show_map"}],
        )
    if topic is Topic.PRICING or estimate is not None:
        if estimate is not None:
            return FaqAnswer(
                f"Ориентировочно {estimate['price_label']} ({kb.work_types.get(estimate['input']['work_type'], '')}, "
                f"{kb.brand_title(estimate['input']['brand'])}). {estimate['disclaimer']}",
                ["Оставить заявку", "Вызвать мастера", "Рассчитать другое"],
                [
                    {
                        "type": "open_form",
                        "form_type": estimate["lead_prefill"]["lead_type"],
                        "prefill": estimate["lead_prefill"],
                    }
                ],
                estimate,
            )
        return FaqAnswer(
            "Стоимость зависит от марки и вида работ. Напишите, например: «диагностика MAN» или «тормоза КамАЗ» — "
            "посчитаю ориентировочную цену. Также есть калькулятор на сайте.",
            replies,
            [{"type": "open_calculator"}],
        )
    if topic is Topic.DISPATCH:
        if "эвакуат" in lowered:
            return FaqAnswer(
                "Организуем грузовой эвакуатор: перевезём технику к нам на СТО или по вашему адресу. "
                "Отметьте точку на карте в форме — диспетчер перезвонит.",
                replies,
                [_form_action("tow", "tow-truck")],
            )
        return FaqAnswer(
            f"Выезжаем круглосуточно. В радиусе {dispatch.effective_radius_km:g} км от СТО приедем примерно за "
            f"{dispatch.eta_minutes} минут, дальше по области — время уточнит диспетчер. "
            f"Отметьте точку на карте в форме вызова или позвоните: {kb.phone}.",
            replies,
            [_form_action("onsite", "onsite-repair")],
        )
    if topic is Topic.PARTS:
        return FaqAnswer(
            "Подберём запчасть — оригинал или аналог под ваш бюджет, со склада или под заказ, с доставкой "
            "в день обращения. Оставьте заявку: марка, деталь и, если есть, VIN.",
            replies,
            [_form_action("parts", "parts")],
        )
    if topic is Topic.CORPORATE:
        return FaqAnswer(
            "Работаем с юрлицами: договор, НДС, безналичный расчёт и закрывающие документы, "
            "отсрочка платежа — по договорённости. Для автопарков подготовим индивидуальное предложение.",
            replies,
            [_form_action("corporate", "fleet-service")],
        )
    if topic is Topic.WARRANTY:
        warranty = kb.site.section("warranty").get("text") or "Даём гарантию на выполненные работы."
        return FaqAnswer(str(warranty), replies)
    if topic is Topic.SERVICES:
        titles = ", ".join(s["title"] for s in kb.services[:9])
        return FaqAnswer(
            f"Наши услуги: {titles}. Что именно нужно — ремонт на СТО или выезд мастера?",
            replies,
            [{"type": "show_services"}],
        )
    return FaqAnswer(
        "Я помогу с услугами, ценами, выездом мастера и запчастями. Опишите, что случилось, "
        f"или позвоните: {kb.phone}. Если нужно — могу передать вопрос оператору.",
        [*SUGGESTED_REPLIES[Topic.OTHER], "Позвать оператора"],
    )
