"""Order tracking link, status pipeline, notifications, Telegram buttons and deep-link binding, admin API."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.db.models import ClientChannel, Lead
from app.integrations.notifiers.base import is_public_url, telegram_link
from tests.conftest import OPERATOR_CHAT, Env, lead_payload


async def _create(env: Env, lead_type: str = "onsite", **extra: Any) -> dict[str, Any]:
    resp = await env.client.post("/api/v1/leads", json=lead_payload(lead_type, **extra))
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_order_page(env: Env) -> None:
    lead = await _create(env, email="client@example.com")
    resp = await env.client.get(f"/api/v1/orders/{lead['public_token']}")
    assert resp.status_code == 200
    assert resp.headers["x-robots-tag"] == "noindex, nofollow" and resp.headers["cache-control"] == "no-store"
    order = resp.json()
    assert order["number"] == lead["number"] and order["status"] == "new"
    assert order["summary"]["phone_masked"] == "+7 *** *** 45 67"
    assert "9271234567" not in resp.text and "client@example.com" not in resp.text
    assert [s["status"] for s in order["steps"]] == ["new", "accepted", "on_the_way", "in_progress", "completed"]
    assert {"label": "Машина на ходу?", "value": "Нет"} in order["summary"]["details"]


async def test_order_not_found_is_uniform(env: Env) -> None:
    lead = await _create(env)
    unknown = await env.client.get("/api/v1/orders/" + "A" * 32)
    malformed = await env.client.get("/api/v1/orders/x")
    token = lead["public_token"]
    tampered = await env.client.get(f"/api/v1/orders/{token[:-1]}{'A' if token[-1] != 'A' else 'B'}")
    assert unknown.status_code == malformed.status_code == tampered.status_code == 404
    assert unknown.json() == malformed.json() == tampered.json()


async def test_order_rate_limit(env: Env) -> None:
    for _ in range(30):
        await env.client.get("/api/v1/orders/" + "B" * 32)
    assert (await env.client.get("/api/v1/orders/" + "B" * 32)).status_code == 429


async def test_status_pipeline_notifies_client(env: Env) -> None:
    lead = await _create(env, email="client@example.com")
    for status in ["accepted", "on_the_way", "in_progress", "completed"]:
        resp = await env.client.post(
            f"/api/v1/admin/leads/{lead['id']}/status", json={"status": status}, headers=env.admin
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == status
    await env.drain()
    client_mails = [m for m in env.email.sent if m.recipient == "client@example.com"]
    assert len(client_mails) == 5  # confirmation + 4 status changes
    assert "Готово" in client_mails[-1].subject and lead["tracking_url"] in client_mails[-1].text
    order = (await env.client.get(f"/api/v1/orders/{lead['public_token']}")).json()
    assert [h["status"] for h in order["history"]] == ["new", "accepted", "on_the_way", "in_progress", "completed"]
    assert all(s["done"] for s in order["steps"])
    detail = (await env.client.get(f"/api/v1/admin/leads/{lead['id']}", headers=env.admin)).json()
    assert detail["history"][1]["actor"] == "admin:api" and detail["allowed_transitions"] == []
    # operator Telegram card refreshed (buttons follow the status)
    assert env.tg.edits and env.tg.edits[-1]["buttons"] == []


async def test_invalid_transition(env: Env) -> None:
    lead = await _create(env, "repair")
    await env.client.post(f"/api/v1/admin/leads/{lead['id']}/status", json={"status": "accepted"}, headers=env.admin)
    resp = await env.client.post(
        f"/api/v1/admin/leads/{lead['id']}/status", json={"status": "on_the_way"}, headers=env.admin
    )
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "invalid_transition"


async def test_admin_auth(env: Env) -> None:
    assert (await env.client.get("/api/v1/admin/leads")).status_code == 401
    bad = await env.client.get("/api/v1/admin/leads", headers={"Authorization": "Bearer wrong"})
    assert bad.status_code == 401
    ok = await env.client.get("/api/v1/admin/leads", headers=env.admin)
    assert ok.status_code == 200 and ok.json()["total"] == 0


def _callback(lead_id: str, status: str, chat_id: int = OPERATOR_CHAT, message_id: int = 101) -> dict[str, Any]:
    return {
        "update_id": 1,
        "callback_query": {
            "id": "cq1",
            "from": {"id": 42, "username": "dispatcher"},
            "data": f"st:{lead_id.replace('-', '')}:{status}",
            "message": {"message_id": message_id, "chat": {"id": chat_id, "type": "supergroup"}},
        },
    }


async def test_telegram_buttons_change_status(env: Env) -> None:
    lead = await _create(env)
    await env.drain()
    card = env.tg.to(OPERATOR_CHAT)[0]
    labels = [b.text for row in card["buttons"] for b in row]
    assert labels == ["✅ Принять", "✖ Отменить"]

    bot = env.container.telegram_bot
    assert bot is not None
    await bot.handle_update(_callback(lead["id"], "accepted", message_id=card["message_id"]))
    assert env.tg.answers[-1]["text"] == "Статус: Принята мастером"
    edited = env.tg.edits[-1]
    assert edited["message_id"] == card["message_id"]
    assert [b.text for row in edited["buttons"] for b in row] == ["🚚 Выехали", "🔧 В работе", "✖ Отменить"]

    await bot.handle_update(_callback(lead["id"], "completed"))  # skipping steps is rejected
    assert "Нельзя" in env.tg.answers[-1]["text"]
    order = (await env.client.get(f"/api/v1/orders/{lead['public_token']}")).json()
    assert order["status"] == "accepted"
    detail = (await env.client.get(f"/api/v1/admin/leads/{lead['id']}", headers=env.admin)).json()
    assert detail["history"][-1]["actor"] == "telegram:dispatcher"


async def test_telegram_buttons_only_from_operator_chat(env: Env) -> None:
    lead = await _create(env)
    bot = env.container.telegram_bot
    assert bot is not None
    await bot.handle_update(_callback(lead["id"], "accepted", chat_id=777))
    assert env.tg.answers[-1]["text"] == "Недоступно"
    order = (await env.client.get(f"/api/v1/orders/{lead['public_token']}")).json()
    assert order["status"] == "new"


async def test_telegram_deep_link_binding(env: Env) -> None:
    lead = await _create(env)
    bot = env.container.telegram_bot
    assert bot is not None
    client_chat = 5550001
    await bot.handle_update(
        {
            "update_id": 2,
            "message": {
                "message_id": 1,
                "chat": {"id": client_chat, "type": "private"},
                "text": f"/start {lead['public_token']}",
            },
        }
    )
    assert lead["number"] in env.tg.to(client_chat)[-1]["text"]
    await bot.handle_update(
        {
            "update_id": 3,
            "message": {  # second /start must not duplicate the channel
                "message_id": 2,
                "chat": {"id": client_chat, "type": "private"},
                "text": f"/start {lead['public_token']}",
            },
        }
    )
    async with env.container.session_factory() as s:
        rows = (await s.scalars(select(ClientChannel).where(ClientChannel.kind == "telegram"))).all()
        assert len(rows) == 1 and rows[0].address == str(client_chat)

    await env.client.post(f"/api/v1/admin/leads/{lead['id']}/status", json={"status": "accepted"}, headers=env.admin)
    await env.drain()
    status_msgs = [m for m in env.tg.to(client_chat) if "Принята мастером" in m["text"]]
    assert len(status_msgs) == 1 and lead["tracking_url"] in status_msgs[0]["text"]
    assert (await env.client.get(f"/api/v1/orders/{lead['public_token']}")).json()["telegram_bound"] is True


async def test_telegram_bad_token(env: Env) -> None:
    bot = env.container.telegram_bot
    assert bot is not None
    await bot.handle_update(
        {
            "update_id": 4,
            "message": {"message_id": 1, "chat": {"id": 1, "type": "private"}, "text": "/start not-a-real-token"},
        }
    )
    assert "не найдена" in env.tg.to(1)[-1]["text"]


async def test_telegram_username_stored_for_operators_only(env: Env) -> None:
    lead = await _create(env, "callback")  # callback form has no telegram field → ignored
    lead2 = await _create(env, "repair", telegram_username="@ivan_driver", phone="+79270000002")
    async with env.container.session_factory() as s:
        row = await s.scalar(select(Lead).where(Lead.number == lead2["number"]))
        assert row is not None and row.telegram_username == "ivan_driver"
    await env.drain()
    assert any("@ivan_driver" in m["text"] for m in env.tg.to(OPERATOR_CHAT))
    assert lead["number"]


def test_public_url_detection() -> None:
    assert is_public_url("https://gruzspec.ru/order/x")
    for url in [
        "http://localhost:5173/order/x",
        "http://127.0.0.1:8000/a",
        "http://192.168.1.5/a",
        "https://site.test/x",
    ]:
        assert not is_public_url(url), url
    assert telegram_link("http://localhost:5173/o", "Открыть") == "http://localhost:5173/o"
    assert telegram_link("https://gruzspec.ru/o", "Открыть") == '<a href="https://gruzspec.ru/o">Открыть</a>'


async def test_bind_reply_without_url_button_on_localhost(env: Env) -> None:
    """Telegram rejects localhost URLs in buttons: in dev the link goes as text instead."""
    lead = await _create(env)
    bot = env.container.telegram_bot
    assert bot is not None
    await bot.handle_update(
        {
            "update_id": 7,
            "message": {
                "message_id": 1,
                "chat": {"id": 4242, "type": "private"},
                "text": f"/start {lead['public_token']}",
            },
        }
    )
    reply = env.tg.to(4242)[-1]
    assert reply["buttons"] == [] and lead["tracking_url"] in reply["text"]
