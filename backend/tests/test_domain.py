"""Pure domain rules: phone, INN, statuses, calculator formula, dispatch zone, topics, form tokens."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import ValidationFailed
from app.core.logging import mask_pii
from app.core.security import FormTokenError, FormTokenSigner
from app.domain.calculator import EstimateInput, PricingRules, estimate
from app.domain.dispatch import DispatchConfig, Zone, check_point, circle_geojson
from app.domain.inn import is_valid_inn
from app.domain.phone import InvalidPhone, extract_phone, mask_phone, normalize_phone
from app.domain.statuses import InvalidTransition, LeadStatus, allowed_transitions, ensure_transition
from app.domain.topics import Topic, asks_for_operator, detect_topic
from app.domain.validation import LeadValidator
from app.domain.worktime import work_status
from app.integrations.llm.base import ChatRequest, TextDelta
from app.integrations.llm.openrouter import OpenRouterProvider
from app.integrations.notifiers.telegram import TelegramClient


@pytest.mark.parametrize(
    "raw", ["+7 (960) 355-57-65", "8 960 355 57 65", "79603555765", "9603555765", "+7-960-355-5765", " 8(960)3555765 "]
)
def test_phone_normalization(raw: str) -> None:
    assert normalize_phone(raw) == "+79603555765"


@pytest.mark.parametrize("raw", ["", "12345", "+1 202 555 0100", "8 160 355 57 65", "телефон", "+7 960 355 57 6"])
def test_phone_invalid(raw: str) -> None:
    with pytest.raises(InvalidPhone):
        normalize_phone(raw)


def test_phone_mask_and_extract() -> None:
    assert mask_phone("+79603555765") == "+7 *** *** 57 65"
    assert extract_phone("мой номер 8-927-111-22-33, звоните") == "+79271112233"
    assert extract_phone("заказ 12345") is None


def test_log_masking() -> None:
    masked = mask_pii("call +7 960 355-57-65 or mail ivan.petrov@example.com bot123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    assert "355" not in masked and "ivan.petrov" not in masked and "ABCDEFG" not in masked


@pytest.mark.parametrize(
    ("inn", "ok"),
    [
        ("7707083893", True),
        ("500100732259", True),
        ("7707083894", False),
        ("500100732258", False),
        ("12345", False),
        ("77070838９3", False),
    ],
)
def test_inn(inn: str, ok: bool) -> None:
    assert is_valid_inn(inn) is ok


def test_status_transitions() -> None:
    assert allowed_transitions("onsite", "accepted") == [
        LeadStatus.ON_THE_WAY,
        LeadStatus.IN_PROGRESS,
        LeadStatus.CANCELLED,
    ]
    assert LeadStatus.ON_THE_WAY not in allowed_transitions("repair", "accepted")
    assert allowed_transitions("repair", "completed") == []
    with pytest.raises(InvalidTransition):
        ensure_transition("repair", "accepted", "on_the_way")
    with pytest.raises(InvalidTransition):
        ensure_transition("repair", "new", "completed")


def test_calculator_formula_rounds_up_and_breakdown_sums() -> None:
    result = estimate(
        EstimateInput("Диагностика", 2500, "MAN", 1.2, "Тягач", 1.0, urgent=True, onsite=True, onsite_included=False),
        PricingRules(),
    )
    # 2500 × 1.2 = 3000; +20% = 3600; + 3000 выезд = 6600
    assert result.price_from == 6600
    assert sum(line.amount for line in result.breakdown) == result.price_from
    odd = estimate(EstimateInput("X", 1234, "B", 1.1, None, 1.0, False, False, False), PricingRules())
    assert odd.price_from == 1400 and odd.price_from % 100 == 0


CFG = DispatchConfig(
    center_lat=51.5336,
    center_lon=46.0343,
    avg_speed_kmh=30,
    eta_minutes=30,
    region_polygon=((42.45, 51.45), (46.6, 52.85), (50.85, 51.75), (48.4, 49.8), (43.9, 50.4)),
)


def test_dispatch_zones() -> None:
    assert CFG.effective_radius_km == 15
    inside = check_point(CFG, 51.56, 46.05)
    assert inside.zone is Zone.INSIDE and inside.eta_minutes is not None and inside.eta_minutes <= 30
    region = check_point(CFG, 51.03, 45.70)  # ~60 km away, still inside the oblast polygon
    assert region.zone is Zone.REGION and region.eta_minutes is None
    assert check_point(CFG, 55.75, 37.62).zone is Zone.OUTSIDE  # Moscow
    ring = circle_geojson(CFG)["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1] and len(ring) == 65


def test_work_status_schedule() -> None:
    tz = ZoneInfo("Europe/Saratov")
    hours = {"mode": "schedule", "schedule": {"mon": ["08:00", "20:00"]}}
    assert work_status(hours, "Europe/Saratov", datetime(2026, 11, 16, 10, 0, tzinfo=tz)).is_open
    assert not work_status(hours, "Europe/Saratov", datetime(2026, 11, 16, 21, 0, tzinfo=tz)).is_open
    assert not work_status(hours, "Europe/Saratov", datetime(2026, 11, 17, 10, 0, tzinfo=tz)).is_open
    assert work_status({"mode": "24/7"}, "Europe/Saratov").is_open


def test_topics_and_operator_detection() -> None:
    assert detect_topic("Сколько стоит замена колодок?") is Topic.PRICING
    assert detect_topic("Сломался на трассе, нужен выезд") is Topic.DISPATCH
    assert detect_topic("работаете с НДС по договору?") is Topic.CORPORATE
    assert detect_topic("ок", Topic.PARTS) is Topic.PARTS
    for text in ["Позовите оператора", "хочу с живым человеком", "соедините с менеджером", "не хочу с ботом"]:
        assert asks_for_operator(text), text
    for text in ["сколько стоит ремонт", "нужен эвакуатор", "привет"]:
        assert not asks_for_operator(text), text


def test_form_token() -> None:
    signer = FormTokenSigner("s")
    token = signer.issue("repair", now=1000.0)
    signer.verify(token, "repair", min_age=3, max_age=60, now=1005.0)
    with pytest.raises(FormTokenError) as fast:
        signer.verify(token, "repair", min_age=3, max_age=60, now=1001.0)
    assert fast.value.code == "form_too_fast"
    with pytest.raises(FormTokenError):
        signer.verify(token, "onsite", min_age=3, max_age=60, now=1005.0)
    with pytest.raises(FormTokenError):
        signer.verify(token[:-2] + "xx", "repair", min_age=3, max_age=60, now=1005.0)


class TestLeadValidator:
    v = LeadValidator()

    def test_consent_required(self) -> None:
        with pytest.raises(ValidationFailed) as exc:
            self.v.validate({"lead_type": "callback", "name": "A", "phone": "89271234567"})
        assert exc.value.fields and "consent" in exc.value.fields
        with pytest.raises(ValidationFailed):
            self.v.validate({"lead_type": "callback", "name": "A", "phone": "89271234567", "consent": "false"})

    def test_phone_normalized_and_columns(self) -> None:
        r = self.v.validate({"lead_type": "callback", "name": " Анна ", "phone": "8 927 123 45 67", "consent": "on"})
        assert r.columns == {"name": "Анна", "phone": "+79271234567"} and r.consent

    def test_corporate_rules(self) -> None:
        with pytest.raises(ValidationFailed) as exc:
            self.v.validate(
                {
                    "lead_type": "corporate",
                    "name": "A",
                    "phone": "89271234567",
                    "consent": True,
                    "inn": "1234567890",
                    "fleet_size": "0",
                }
            )
        fields = exc.value.fields or {}
        assert {"company_name", "email", "inn", "fleet_size"} <= set(fields)
        ok = self.v.validate(
            {
                "lead_type": "corporate",
                "name": "A",
                "phone": "89271234567",
                "consent": True,
                "company_name": "ООО",
                "email": "A@Example.COM",
                "fleet_size": "3",
            }
        )
        assert ok.details["fleet_size"] == 3 and ok.columns["email"] == "a@example.com"

    def test_conditional_field_and_geo(self) -> None:
        base = {
            "lead_type": "tow",
            "name": "A",
            "phone": "89271234567",
            "consent": True,
            "vehicle_type": "truck",
            "is_drivable": "no",
            "destination": "other_address",
            "lat": "51.5",
            "lon": "46.0",
        }
        with pytest.raises(ValidationFailed) as exc:
            self.v.validate(base)
        assert exc.value.fields == {"destination_address": "Обязательное поле"}
        with pytest.raises(ValidationFailed) as exc:
            self.v.validate({**base, "destination_address": "Энгельс", "lat": "", "lon": ""})
        assert "location" in (exc.value.fields or {})

    def test_honeypot_and_unknown_type(self) -> None:
        with pytest.raises(Exception, match="не принята"):
            self.v.validate({"lead_type": "callback", "website": "http://spam"})
        with pytest.raises(ValidationFailed):
            self.v.validate({"lead_type": "chat_handoff"})


def test_telegram_proxy_setting() -> None:
    assert Settings(_env_file=None, telegram_proxy_url="").telegram_proxy_url is None
    s = Settings(_env_file=None, telegram_proxy_url="socks5://127.0.0.1:10808")
    client = TelegramClient("123:X", proxy=s.telegram_proxy_url)  # constructs with SOCKS support installed
    assert client._http is not None


async def test_openrouter_retries_once_on_connect_error() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectTimeout("slow network")
        body = 'data: {"choices":[{"delta":{"content":"Привет"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    llm = OpenRouterProvider("k", "m", transport=httpx.MockTransport(handler))
    events = [e async for e in llm.stream(ChatRequest(messages=[{"role": "user", "content": "hi"}]))]
    assert calls["n"] == 2 and TextDelta("Привет") in events
