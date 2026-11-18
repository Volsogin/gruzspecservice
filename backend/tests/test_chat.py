"""Chat assistant: FAQ mode without LLM, LLM tool calling, fallback, handoff only on request, live chat."""

from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy import select

from app.db.models import ChatSession, Lead
from app.integrations.llm.base import Finished, LLMUnavailable, TextDelta, ToolCall, ToolCallsRequested, Usage
from tests.conftest import OPERATOR_CHAT, Env


async def _session(env: Env, consent: bool = True) -> str:
    resp = await env.client.post("/api/v1/chat/sessions", json={"consent": consent})
    assert resp.status_code == 201
    return str(resp.json()["session_id"])


async def _say(env: Env, sid: str, text: str, **extra: Any) -> list[dict[str, Any]]:
    resp = await env.client.post(f"/api/v1/chat/sessions/{sid}/messages?stream=false", json={"text": text, **extra})
    assert resp.status_code == 200, resp.text
    return list(resp.json()["events"])


def _done(events: list[dict[str, Any]]) -> dict[str, Any]:
    return next(e["data"] for e in events if e["event"] == "done")


def _actions(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e["data"] for e in events if e["event"] == "action"]


async def _leads(env: Env, lead_type: str) -> list[Lead]:
    async with env.container.session_factory() as s:
        return list((await s.scalars(select(Lead).where(Lead.type == lead_type))).all())


# --- FAQ mode (no OPENROUTER_API_KEY) ---------------------------------------------------------------
async def test_faq_mode_answers_without_llm(env: Env) -> None:
    sid = await _session(env)
    events = await _say(env, sid, "Сколько стоит диагностика MAN?")
    done = _done(events)
    assert done["mode"] == "faq" and done["topic"] == "pricing"
    estimate = next(e["data"] for e in events if e["event"] == "estimate")
    assert estimate["price_from"] == 3000 and "от 3 000 ₽" in done["text"]  # 2500 × 1.2

    done = _done(await _say(env, sid, "Где вы находитесь?"))
    assert "Автокомбинатовская" in done["text"]
    events = await _say(env, sid, "Сломался на трассе, нужен выезд")
    assert _done(events)["topic"] == "dispatch"
    assert _actions(events)[0] == {
        "type": "open_form",
        "form_type": "onsite",
        "prefill": {"lead_type": "onsite", "service_slug": "onsite-repair"},
    }
    assert _done(await _say(env, sid, "Работаете с НДС?"))["topic"] == "corporate"
    assert _done(events)["suggested_replies"]


async def test_sse_stream_format(env: Env) -> None:
    sid = await _session(env)
    async with env.client.stream("POST", f"/api/v1/chat/sessions/{sid}/messages", json={"text": "Привет"}) as resp:
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert "content-encoding" not in resp.headers
        raw = "".join([chunk async for chunk in resp.aiter_text()])
    blocks = [b for b in raw.split("\n\n") if b]
    assert blocks[0].startswith("event: meta") and blocks[-1].startswith("event: done")
    assert json.loads(blocks[-1].split("data: ", 1)[1])["text"].startswith("Здравствуйте")


async def test_chat_validation_and_limits(env: Env) -> None:
    sid = await _session(env)
    too_long = await env.client.post(f"/api/v1/chat/sessions/{sid}/messages", json={"text": "a" * 1001})
    assert too_long.status_code == 422
    unknown = await env.client.post(
        "/api/v1/chat/sessions/00000000-0000-0000-0000-000000000000/messages", json={"text": "hi"}
    )
    assert unknown.status_code == 404


@pytest.mark.parametrize("settings_overrides", [{"chat_max_messages_per_session": 2}])
async def test_message_limit_per_session(env: Env) -> None:
    sid = await _session(env)
    await _say(env, sid, "привет")
    await _say(env, sid, "привет")
    resp = await env.client.post(f"/api/v1/chat/sessions/{sid}/messages", json={"text": "ещё"})
    assert resp.status_code == 429 and resp.json()["error"]["code"] == "chat_limit"


# --- handoff -------------------------------------------------------------------------------------------
async def test_handoff_only_on_request_and_asks_phone(env: Env) -> None:
    sid = await _session(env)
    for text in ["Сколько стоит ремонт тормозов КамАЗ?", "Есть запчасти на Volvo?", "Не знаю что делать"]:
        events = await _say(env, sid, text)
        assert not [e for e in events if e["event"] == "handoff"], text
    assert await _leads(env, "chat_handoff") == []

    events = await _say(env, sid, "Позовите оператора, пожалуйста")
    assert [e for e in events if e["event"] == "handoff"]
    assert {"type": "phone_required", "consent_required": False} in _actions(events)
    assert "номер телефона" in _done(events)["text"]

    events = await _say(env, sid, "+7 927 555 44 33")
    lead_action = next(a for a in _actions(events) if a["type"] == "lead_created")
    assert lead_action["lead"]["number"].startswith("GS-")
    leads = await _leads(env, "chat_handoff")
    assert len(leads) == 1 and leads[0].phone == "+79275554433" and leads[0].source == "chatbot"
    assert "Позовите оператора" in leads[0].details["transcript"]
    await env.drain()
    operator_msgs = env.tg.to(OPERATOR_CHAT)
    assert operator_msgs and "Запрос из чата" in operator_msgs[0]["text"]
    assert any(m.recipient == "ops@example.test" for m in env.email.sent)


async def test_agreeing_to_offer_triggers_handoff(env: Env) -> None:
    sid = await _session(env)
    done = _done(await _say(env, sid, "абракадабра"))
    assert "оператору" in done["text"]  # fallback offers once
    events = await _say(env, sid, "да, давайте")
    assert [e for e in events if e["event"] == "handoff"]


async def test_handoff_requires_consent(env: Env) -> None:
    sid = await _session(env, consent=False)
    await _say(env, sid, "Соедините с менеджером")
    events = await _say(env, sid, "89275554433")
    assert {"type": "consent_required"} in _actions(events)
    assert await _leads(env, "chat_handoff") == []
    events = await _say(env, sid, "89275554433", consent=True)
    assert any(a["type"] == "lead_created" for a in _actions(events))


async def test_handoff_button(env: Env) -> None:
    sid = await _session(env)
    no_phone = (await env.client.post(f"/api/v1/chat/sessions/{sid}/handoff", json={})).json()
    assert any(e["data"].get("type") == "phone_required" for e in no_phone["events"] if e["event"] == "action")
    with_phone = await env.client.post(
        f"/api/v1/chat/sessions/{sid}/handoff", json={"phone": "8 927 000 11 22", "name": "Олег", "consent": True}
    )
    assert with_phone.status_code == 200 and with_phone.json()["lead_id"]
    bad = await env.client.post(f"/api/v1/chat/sessions/{sid}/handoff", json={"phone": "123"})
    assert bad.status_code == 422


async def test_live_operator_chat(env: Env) -> None:
    sid = await _session(env)
    await env.client.post(f"/api/v1/chat/sessions/{sid}/handoff", json={"phone": "89270001122", "consent": True})
    events = await _say(env, sid, "Машина стоит у заправки на выезде")
    assert _done(events)["mode"] == "operator" and _done(events)["forwarded_to_operator"] is True
    await env.drain()
    forwarded = next(m for m in env.tg.to(OPERATOR_CHAT) if "у заправки" in m["text"])

    queue = env.container.live_chat.subscribe(__import__("uuid").UUID(sid))
    bot = env.container.telegram_bot
    assert bot is not None
    await bot.handle_update(
        {
            "update_id": 9,
            "message": {
                "message_id": 500,
                "chat": {"id": OPERATOR_CHAT, "type": "supergroup"},
                "from": {"first_name": "Мария"},
                "text": "Выезжаем, будем через 25 минут",
                "reply_to_message": {"message_id": forwarded["message_id"]},
            },
        }
    )
    event = queue.get_nowait()
    assert event["event"] == "operator_message" and event["data"]["operator_name"] == "Мария"
    history = (await env.client.get(f"/api/v1/chat/sessions/{sid}/messages")).json()
    assert history["status"] == "operator" and history["messages"][-1]["role"] == "operator"


# --- LLM mode -----------------------------------------------------------------------------------------
@pytest.mark.parametrize("use_llm", [True])
async def test_llm_tool_calling_price(env: Env) -> None:
    assert env.llm is not None
    env.llm.script = [
        [
            ToolCallsRequested(
                [ToolCall("c1", "calculate_price", json.dumps({"brand": "Scania", "work_type": "brakes"}))]
            ),
            Usage(100, 10),
            Finished("tool_calls"),
        ],
        [TextDelta("Ремонт тормозов Scania — "), TextDelta("от 5 000 ₽."), Usage(150, 20), Finished("stop")],
    ]
    sid = await _session(env)
    events = await _say(env, sid, "Сколько стоят тормоза на Скании?")
    assert next(e for e in events if e["event"] == "estimate")["data"]["price_from"] == 5000  # 4000 × 1.25
    done = _done(events)
    assert done["mode"] == "llm" and done["topic"] == "pricing"
    assert done["text"] == "Ремонт тормозов Scania — от 5 000 ₽."
    first, second = env.llm.requests
    assert first.messages[0]["role"] == "system" and "calculate_price" in json.dumps(first.tools)
    tool_msg = second.messages[-1]
    assert tool_msg["role"] == "tool" and json.loads(tool_msg["content"])["price_from"] == 5000
    usage = (await env.client.get("/readyz")).json()
    assert usage["integrations"]["llm"] is True


@pytest.mark.parametrize("use_llm", [True])
async def test_llm_cannot_handoff_unprompted(env: Env) -> None:
    assert env.llm is not None
    env.llm.script = [
        [ToolCallsRequested([ToolCall("c1", "request_operator", "{}")]), Finished("tool_calls")],
        [TextDelta("Подскажу сам: опишите проблему."), Finished("stop")],
    ]
    sid = await _session(env)
    events = await _say(env, sid, "у меня вопрос по ремонту")
    assert not [e for e in events if e["event"] == "handoff"]
    assert json.loads(env.llm.requests[1].messages[-1]["content"])["error"] == "not_requested"
    async with env.container.session_factory() as s:
        chat = await s.get(ChatSession, __import__("uuid").UUID(sid))
        assert chat is not None and chat.status == "bot" and not chat.awaiting_phone


@pytest.mark.parametrize("use_llm", [True])
async def test_explicit_operator_request_bypasses_llm(env: Env) -> None:
    sid = await _session(env)
    events = await _say(env, sid, "переключите на человека")
    assert [e for e in events if e["event"] == "handoff"] and env.llm is not None and env.llm.requests == []


@pytest.mark.parametrize("use_llm", [True])
async def test_llm_failure_falls_back_to_faq(env: Env) -> None:
    assert env.llm is not None
    env.llm.script = [LLMUnavailable("network")]
    sid = await _session(env)
    done = _done(await _say(env, sid, "Какая у вас гарантия?"))
    assert done["mode"] == "faq" and "12 месяцев" in done["text"]


@pytest.mark.parametrize("use_llm", [True])
@pytest.mark.parametrize("settings_overrides", [{"llm_daily_request_limit": 1}])
async def test_llm_budget_exhausted_switches_to_faq(env: Env) -> None:
    assert env.llm is not None
    env.llm.script = [[TextDelta("Здравствуйте!"), Finished("stop")]]
    sid = await _session(env)
    assert _done(await _say(env, sid, "привет"))["mode"] == "llm"
    assert _done(await _say(env, sid, "привет"))["mode"] == "faq"
    assert len(env.llm.requests) == 1


@pytest.mark.parametrize("use_llm", [True])
async def test_llm_create_lead_tool(env: Env) -> None:
    assert env.llm is not None
    args = {"lead_type": "callback", "name": "Пётр", "phone": "89271112233"}
    env.llm.script = [
        [ToolCallsRequested([ToolCall("c1", "create_lead", json.dumps(args))]), Finished("tool_calls")],
        [TextDelta("Заявка создана, перезвоним."), Finished("stop")],
    ]
    sid = await _session(env)
    events = await _say(env, sid, "перезвоните мне 89271112233, Пётр")
    assert any(a["type"] == "lead_created" for a in _actions(events))
    leads = await _leads(env, "callback")
    assert len(leads) == 1 and leads[0].source == "chatbot" and leads[0].consent_given
