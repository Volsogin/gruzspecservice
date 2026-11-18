"""Telegram bot: operators (DM cards, «Беру», shifts) and clients (verified phone, questions, cancel)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from app.db.models import ClientChannel, Lead, Operator
from app.services.telegram_bot import TelegramBot
from tests.conftest import OPERATOR_CHAT, Env, lead_payload

OP1, OP2, CLIENT = 7001, 7002, 9001
INVITE = {"operator_invite_code": "let-me-in"}
_seq = iter(range(1, 10_000))


def _msg(
    chat_id: int,
    text: str = "",
    *,
    user_id: int | None = None,
    username: str | None = None,
    reply_to: int | None = None,
    contact: dict[str, Any] | None = None,
    first_name: str = "Тест",
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "message_id": next(_seq),
        "chat": {"id": chat_id, "type": "private"},
        "text": text,
        "from": {"id": user_id or chat_id, "first_name": first_name, **({"username": username} if username else {})},
    }
    if reply_to:
        message["reply_to_message"] = {"message_id": reply_to}
    if contact:
        message["contact"] = contact
    return {"update_id": next(_seq), "message": message}


def _cb(chat_id: int, data: str, *, user_id: int | None = None, message_id: int = 1) -> dict[str, Any]:
    return {
        "update_id": next(_seq),
        "callback_query": {
            "id": f"cq{next(_seq)}",
            "data": data,
            "from": {"id": user_id or chat_id, "first_name": "Тест"},
            "message": {"message_id": message_id, "chat": {"id": chat_id, "type": "private"}},
        },
    }


def _bot(env: Env) -> TelegramBot:
    assert env.container.telegram_bot is not None
    return env.container.telegram_bot


def _labels(message: dict[str, Any]) -> list[str]:
    return [b.text for row in message["buttons"] for b in row]


async def _register(env: Env, chat_id: int, name: str) -> None:
    await _bot(env).handle_update(_msg(chat_id, "/operator let-me-in", first_name=name, username=name.lower()))


async def _lead(env: Env, **extra: Any) -> dict[str, Any]:
    resp = await env.client.post("/api/v1/leads", json=lead_payload("onsite", **extra))
    assert resp.status_code == 201, resp.text
    await env.drain()
    return dict(resp.json())


# --- operators -----------------------------------------------------------------------------------
@pytest.mark.parametrize("settings_overrides", [INVITE])
async def test_operator_registration(env: Env) -> None:
    bot = _bot(env)
    await bot.handle_update(_msg(OP1, "/operator wrong"))
    assert "Неверный код" in env.tg.to(OP1)[-1]["text"]
    await _register(env, OP1, "Мария")
    assert "Вы оператор" in env.tg.to(OP1)[-1]["text"]
    async with env.container.session_factory() as s:
        ops = (await s.scalars(select(Operator))).all()
        assert len(ops) == 1 and ops[0].name == "Мария" and ops[0].on_shift


async def test_registration_disabled_without_code(env: Env) -> None:
    await _bot(env).handle_update(_msg(OP1, "/operator anything"))
    assert "выключена" in env.tg.to(OP1)[-1]["text"]


@pytest.mark.parametrize("settings_overrides", [INVITE])
async def test_first_take_wins_and_others_see_it(env: Env) -> None:
    await _register(env, OP1, "Мария")
    await _register(env, OP2, "Олег")
    lead = await _lead(env)
    card1, card2 = env.tg.to(OP1)[-1], env.tg.to(OP2)[-1]
    assert lead["number"] in card1["text"] and _labels(card1) == ["✋ Беру", "✖ Отменить"]
    assert _labels(card2) == ["✋ Беру", "✖ Отменить"]
    assert env.tg.to(OPERATOR_CHAT) == []  # operators on shift → the group is not used

    hexid = lead["id"].replace("-", "")
    await _bot(env).handle_update(_cb(OP1, f"tk:{hexid}", message_id=card1["message_id"]))
    assert env.tg.answers[-1]["text"] == f"Заявка {lead['number']} ваша"
    await _bot(env).handle_update(_cb(OP2, f"tk:{hexid}", message_id=card2["message_id"]))
    assert env.tg.answers[-1]["text"] == "Заявку уже взял Мария"
    await env.drain()

    edits = {e["chat_id"]: e for e in env.tg.edits}
    assert "Ответственный: Мария" in edits[OP1]["text"] and "Ответственный: Мария" in edits[OP2]["text"]
    assert _labels(edits[OP1]) == ["🚚 Выехали", "🔧 В работе", "✖ Отменить"]
    assert _labels(edits[OP2]) == []  # someone else's job: no buttons

    await _bot(env).handle_update(_cb(OP2, f"st:{hexid}:on_the_way"))
    assert env.tg.answers[-1]["text"] == "Заявку ведёт Мария"
    await _bot(env).handle_update(_cb(OP1, f"st:{hexid}:on_the_way"))
    assert env.tg.answers[-1]["text"] == "Статус: Мастер выехал к вам"
    detail = (await env.client.get(f"/api/v1/admin/leads/{lead['id']}", headers=env.admin)).json()
    assert detail["status"] == "on_the_way"


@pytest.mark.parametrize("settings_overrides", [INVITE])
async def test_shift_controls_who_gets_new_leads(env: Env) -> None:
    await _register(env, OP1, "Мария")
    await _register(env, OP2, "Олег")
    await _bot(env).handle_update(_msg(OP2, "/smena"))
    assert "Смена закрыта" in env.tg.to(OP2)[-1]["text"]
    sent_before = len(env.tg.to(OP2))
    lead = await _lead(env)
    assert any(lead["number"] in m["text"] for m in env.tg.to(OP1))
    assert len(env.tg.to(OP2)) == sent_before
    await _bot(env).handle_update(_msg(OP1, "/smena off"))
    lead2 = await _lead(env, phone="+79270000099")
    assert any(lead2["number"] in m["text"] for m in env.tg.to(OPERATOR_CHAT))  # nobody on shift → group


# --- clients -------------------------------------------------------------------------------------------
async def test_contact_must_be_own_and_binds_leads(env: Env) -> None:
    lead = await _lead(env)  # phone +79271234567
    bot = _bot(env)
    await bot.handle_update(_msg(CLIENT, contact={"phone_number": "79271234567", "user_id": 12345}))
    assert "кнопкой" in env.tg.to(CLIENT)[-1]["text"]  # someone else's contact is not proof
    await bot.handle_update(_msg(CLIENT, contact={"phone_number": "+7 927 123-45-67", "user_id": CLIENT}))
    texts = [m["text"] for m in env.tg.to(CLIENT)]
    assert any("Номер подтверждён" in t and lead["number"] in t for t in texts)
    listing = env.tg.to(CLIENT)[-1]
    assert lead["number"] in listing["text"] and "✖ Отменить заявку" in _labels(listing)

    await env.client.post(f"/api/v1/admin/leads/{lead['id']}/status", json={"status": "accepted"}, headers=env.admin)
    await env.drain()
    assert any("Принята мастером" in m["text"] for m in env.tg.to(CLIENT))


async def test_start_menu_and_username_autobind(env: Env) -> None:
    lead = await _lead(env, telegram_username="@Ivan_Driver")
    await _bot(env).handle_update(_msg(CLIENT, "/start", username="ivan_driver"))
    texts = [m["text"] for m in env.tg.to(CLIENT)]
    assert any("ГРУЗСПЕЦСЕРВИС" in t for t in texts)
    assert any(lead["number"] in t and "Telegram-нику" in t for t in texts)
    assert [b["text"] for b in env.tg.to(CLIENT)[0]["keyboard"][0]] == ["🔎 Найти заявку", "📋 Мои заявки"]


async def test_client_question_and_operator_reply_roundtrip(env: Env) -> None:
    lead = await _lead(env)
    bot = _bot(env)
    await bot.handle_update(_msg(CLIENT, f"/start {lead['public_token']}"))
    await bot.handle_update(_msg(CLIENT, "Сколько ещё ждать мастера?"))
    assert "Передал вопрос" in env.tg.to(CLIENT)[-1]["text"]
    await env.drain()
    question = next(m for m in env.tg.to(OPERATOR_CHAT) if "Вопрос клиента" in m["text"])
    assert "Сколько ещё ждать" in question["text"]
    assert question["force_reply"] == "Ответ клиенту"  # the app opens «reply» automatically

    group_reply = _msg(OPERATOR_CHAT, "Будем через 15 минут", reply_to=question["message_id"], first_name="Мария")
    group_reply["message"]["chat"]["type"] = "supergroup"
    await bot.handle_update(group_reply)
    assert "Ответ отправлен" in env.tg.to(OPERATOR_CHAT)[-1]["text"]
    await env.drain()
    answer = env.tg.to(CLIENT)[-1]["text"]
    assert lead["number"] in answer and "Будем через 15 минут" in answer


async def test_reply_to_card_reaches_client(env: Env) -> None:
    lead = await _lead(env)
    await _bot(env).handle_update(_msg(CLIENT, f"/start {lead['public_token']}"))
    card = next(m for m in env.tg.to(OPERATOR_CHAT) if lead["number"] in m["text"])
    reply = _msg(OPERATOR_CHAT, "Перезвоню через минуту", reply_to=card["message_id"])
    reply["message"]["chat"]["type"] = "supergroup"
    await _bot(env).handle_update(reply)
    await env.drain()
    assert "Перезвоню через минуту" in env.tg.to(CLIENT)[-1]["text"]


async def test_client_cancel(env: Env) -> None:
    lead = await _lead(env)
    bot = _bot(env)
    hexid = lead["id"].replace("-", "")
    await bot.handle_update(_cb(CLIENT, f"cl:x:{hexid}"))  # not bound to this chat yet
    assert env.tg.answers[-1]["text"] == "Заявка не найдена"
    await bot.handle_update(_msg(CLIENT, f"/start {lead['public_token']}"))
    await bot.handle_update(_cb(CLIENT, f"cl:x:{hexid}"))
    assert "Отменить заявку" in env.tg.to(CLIENT)[-1]["text"]
    await bot.handle_update(_cb(CLIENT, f"cl:y:{hexid}"))
    assert env.tg.answers[-1]["text"] == "Заявка отменена"
    await env.drain()
    detail = (await env.client.get(f"/api/v1/admin/leads/{lead['id']}", headers=env.admin)).json()
    assert detail["status"] == "cancelled" and detail["history"][-1]["actor"] == "client:telegram"
    assert any("отменил" in m["text"] for m in env.tg.to(OPERATOR_CHAT))


async def test_client_cannot_cancel_after_dispatch(env: Env) -> None:
    lead = await _lead(env)
    for status in ("accepted", "on_the_way"):
        await env.client.post(f"/api/v1/admin/leads/{lead['id']}/status", json={"status": status}, headers=env.admin)
    bot = _bot(env)
    await bot.handle_update(_msg(CLIENT, f"/start {lead['public_token']}"))
    await bot.handle_update(_cb(CLIENT, f"cl:y:{lead['id'].replace('-', '')}"))
    assert "нельзя" in env.tg.answers[-1]["text"]
    async with env.container.session_factory() as s:
        row = await s.scalar(select(Lead).where(Lead.number == lead["number"]))
        assert row is not None and row.status == "on_the_way"


async def test_public_settings_expose_bot_link(env: Env) -> None:
    data = (await env.client.get("/api/v1/settings/public")).json()
    assert data["telegram_bot"] == {"username": "test_bot", "url": "https://t.me/test_bot"}
    assert data["messengers"]["telegram"] == {
        "title": "Telegram",
        "url": "https://t.me/test_bot",
        "is_placeholder": False,
    }
    assert data["messengers"]["max"]["is_placeholder"] is True  # Max stays a placeholder


async def test_find_leads_by_typed_phone(env: Env) -> None:
    lead = await _lead(env)  # phone +79271234567
    await _lead(env, phone="+79270000055")  # someone else's lead must not show up
    bot = _bot(env)
    await bot.handle_update(_msg(CLIENT, "🔎 Найти заявку"))
    assert "Напишите телефон" in env.tg.to(CLIENT)[-1]["text"]
    await bot.handle_update(_msg(CLIENT, "8 927 123-45-67"))
    texts = [m["text"] for m in env.tg.to(CLIENT)]
    assert any(f"Нашёл заявки: {lead['number']}" in t for t in texts)
    assert lead["number"] in env.tg.to(CLIENT)[-1]["text"]  # the list with buttons follows
    async with env.container.session_factory() as s:
        bound = (await s.scalars(select(ClientChannel).where(ClientChannel.address == str(CLIENT)))).all()
        assert len(bound) == 1
    await env.client.post(f"/api/v1/admin/leads/{lead['id']}/status", json={"status": "accepted"}, headers=env.admin)
    await env.drain()
    assert any("Принята мастером" in m["text"] for m in env.tg.to(CLIENT))


async def test_find_by_unknown_phone(env: Env) -> None:
    await _bot(env).handle_update(_msg(CLIENT, "+7 999 111-22-33"))
    assert "не нашёл" in env.tg.to(CLIENT)[-1]["text"]


async def test_find_by_phone_is_rate_limited(env: Env) -> None:
    bot = _bot(env)
    for n in range(6):
        await bot.handle_update(_msg(CLIENT, f"+7999000000{n}"))
    await bot.handle_update(_msg(CLIENT, "+79990000009"))
    assert "Слишком много попыток" in env.tg.to(CLIENT)[-1]["text"]


async def test_question_with_digits_is_not_mistaken_for_phone(env: Env) -> None:
    lead = await _lead(env)
    bot = _bot(env)
    await bot.handle_update(_msg(CLIENT, f"/start {lead['public_token']}"))
    await bot.handle_update(_msg(CLIENT, "Перезвоните на 8 927 000 11 22, пожалуйста, после 18:00"))
    assert "Передал вопрос" in env.tg.to(CLIENT)[-1]["text"]
