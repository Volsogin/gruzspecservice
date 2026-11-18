"""Lead intake end-to-end: every type, multipart + photos, idempotency, anti-spam, outbox."""

from __future__ import annotations

import asyncio
import io

import pytest
from PIL import Image
from sqlalchemy import func, select

from app.db.models import Lead, OutboxMessage
from tests.conftest import OPERATOR_CHAT, Env, lead_payload


@pytest.mark.parametrize("lead_type", ["repair", "onsite", "tow", "parts", "corporate", "callback"])
async def test_create_each_type(env: Env, lead_type: str) -> None:
    resp = await env.client.post("/api/v1/leads", json=lead_payload(lead_type))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["number"].startswith("GS-") and body["status"] == "new"
    assert body["status_label"] == "Заявка получена"
    assert body["tracking_url"] == f"https://site.test/order/{body['public_token']}"
    assert body["telegram_bind_url"] == f"https://t.me/test_bot?start={body['public_token']}"
    assert body["summary"]["phone_masked"] == "+7 *** *** 45 67"
    assert len(body["public_token"]) >= 32

    async with env.container.session_factory() as s:
        lead = await s.scalar(select(Lead).where(Lead.number == body["number"]))
        assert lead is not None and lead.phone == "+79271234567" and lead.consent_given
        assert lead.consent_version == "2026-11-v1" and lead.consent_at is not None
        assert lead.ip_hash and "127.0.0.1" not in lead.ip_hash
    if lead_type == "onsite":
        assert lead.dispatch_zone == "inside" and lead.lat == 51.55
    if lead_type == "corporate":
        assert lead.details["inn"] == "7707083893" and lead.details["fleet_types"] == ["dump", "tractor"]

    await env.drain()
    assert any(m.recipient == "ops@example.test" for m in env.email.sent)
    operator_tg = env.tg.to(OPERATOR_CHAT)
    assert len(operator_tg) == 1 and body["number"] in operator_tg[0]["text"]
    assert any("st:" in (b.callback_data or "") for row in operator_tg[0]["buttons"] for b in row)


async def test_numbers_are_sequential(env: Env) -> None:
    a = (await env.client.post("/api/v1/leads", json=lead_payload("callback"))).json()["number"]
    b = (await env.client.post("/api/v1/leads", json=lead_payload("callback", phone="+79270000001"))).json()["number"]
    assert int(b.split("-")[1]) == int(a.split("-")[1]) + 1


async def test_validation_error_format(env: Env) -> None:
    resp = await env.client.post("/api/v1/leads", json={"lead_type": "repair", "phone": "123", "consent": False})
    assert resp.status_code == 422
    err = resp.json()["error"]
    assert err["code"] == "validation_error"
    assert {"phone", "consent", "name", "vehicle_brand", "description"} <= set(err["fields"])


async def test_onsite_operator_message_has_2gis_link(env: Env) -> None:
    await env.client.post("/api/v1/leads", json=lead_payload("onsite"))
    await env.drain()
    text = env.tg.to(OPERATOR_CHAT)[0]["text"]
    assert "2gis.ru/geo/46.020000,51.550000" in text and "в зоне 30 минут" in text


async def test_client_confirmation_email(env: Env) -> None:
    resp = await env.client.post("/api/v1/leads", json=lead_payload("repair", email="client@example.com"))
    await env.drain()
    client_mails = [m for m in env.email.sent if m.recipient == "client@example.com"]
    assert len(client_mails) == 1
    assert resp.json()["tracking_url"] in client_mails[0].text
    assert "t.me/test_bot?start=" in client_mails[0].text


def _jpeg_with_gps() -> bytes:
    img = Image.new("RGB", (800, 600), (200, 30, 30))
    exif = Image.Exif()
    exif[0x010F] = "SecretCam"  # Make
    exif[0x8825] = {1: "N", 2: (51.0, 32.0, 0.0), 3: "E", 4: (46.0, 1.0, 0.0)}  # GPS IFD
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


async def test_multipart_with_photos_strips_exif(env: Env) -> None:
    raw = _jpeg_with_gps()
    assert Image.open(io.BytesIO(raw)).getexif().get_ifd(0x8825)
    png = io.BytesIO()
    Image.new("RGBA", (300, 200), (0, 0, 255, 128)).save(png, "PNG")
    data = {k: str(v) for k, v in lead_payload("repair").items()}
    files = [
        ("photos", ("../../etc/passwd.jpg", raw, "image/jpeg")),
        ("photos", ("x.png", png.getvalue(), "image/png")),
    ]
    resp = await env.client.post("/api/v1/leads", data=data, files=files)
    assert resp.status_code == 201, resp.text
    assert resp.json()["summary"]["photos_count"] == 2

    order = (await env.client.get(f"/api/v1/orders/{resp.json()['public_token']}")).json()
    photos = order["summary"]["photos"]
    assert len(photos) == 2 and all(p["preview_url"].endswith("-preview.webp") for p in photos)
    key = photos[0]["url"].split("/media/")[1]
    assert ".." not in key and "passwd" not in key
    stored = env.container.storage.path_for(key).read_bytes()
    cleaned = Image.open(io.BytesIO(stored))
    assert not cleaned.getexif() and not cleaned.getexif().get_ifd(0x8825)
    media = await env.client.get(f"/media/{key}")
    assert media.status_code == 200 and "immutable" in media.headers["cache-control"]


async def test_fake_image_rejected(env: Env) -> None:
    data = {k: str(v) for k, v in lead_payload("repair").items()}
    resp = await env.client.post(
        "/api/v1/leads", data=data, files=[("photos", ("photo.jpg", b"#!/bin/sh\necho pwned\n", "image/jpeg"))]
    )
    assert resp.status_code == 422 and "photos" in resp.json()["error"]["fields"]
    async with env.container.session_factory() as s:
        assert await s.scalar(select(func.count()).select_from(Lead).where(Lead.type == "repair")) == 0


async def test_too_many_and_too_big_files(env: Env) -> None:
    data = {k: str(v) for k, v in lead_payload("repair").items()}
    img = _jpeg_with_gps()
    resp = await env.client.post(
        "/api/v1/leads", data=data, files=[("photos", (f"{i}.jpg", img, "image/jpeg")) for i in range(6)]
    )
    assert resp.status_code == 422
    big = b"\xff\xd8\xff" + b"0" * (5 * 1024 * 1024 + 10)
    resp = await env.client.post("/api/v1/leads", data=data, files=[("photos", ("big.jpg", big, "image/jpeg"))])
    assert resp.status_code == 422 and "МБ" in resp.json()["error"]["fields"]["photos"]


async def test_body_size_limit(env: Env) -> None:
    resp = await env.client.post(
        "/api/v1/leads",
        content=b"x" * 10,
        headers={"content-length": str(100 * 1024 * 1024), "content-type": "application/json"},
    )
    assert resp.status_code == 413 and resp.json()["error"]["code"] == "payload_too_large"


async def test_idempotency(env: Env) -> None:
    headers = {"Idempotency-Key": "3f1c2c9e-test-key-0001"}
    first = await env.client.post("/api/v1/leads", json=lead_payload("callback"), headers=headers)
    second = await env.client.post("/api/v1/leads", json=lead_payload("callback"), headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert second.headers["Idempotent-Replayed"] == "true"
    conflict = await env.client.post("/api/v1/leads", json=lead_payload("callback", name="Пётр"), headers=headers)
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "idempotency_conflict"
    async with env.container.session_factory() as s:
        assert await s.scalar(select(func.count()).select_from(Lead)) == 1
        # operator e-mail + operator Telegram — exactly once
        assert await s.scalar(select(func.count()).select_from(OutboxMessage)) == 2


async def test_honeypot(env: Env) -> None:
    resp = await env.client.post("/api/v1/leads", json=lead_payload("callback", website="http://spam.example"))
    assert resp.status_code == 400 and resp.json()["error"]["code"] == "rejected"


async def test_rate_limit_by_phone(env: Env) -> None:
    for _ in range(5):
        assert (await env.client.post("/api/v1/leads", json=lead_payload("callback"))).status_code == 201
    resp = await env.client.post("/api/v1/leads", json=lead_payload("callback"))
    assert resp.status_code == 429 and "Retry-After" in resp.headers


@pytest.mark.parametrize("settings_overrides", [{"form_token_required": True, "form_min_fill_seconds": 0.5}])
async def test_form_token_flow(env: Env) -> None:
    missing = await env.client.post("/api/v1/leads", json=lead_payload("callback"))
    assert missing.status_code == 400 and missing.json()["error"]["code"] == "form_token_missing"
    schema = (await env.client.get("/api/v1/forms/callback")).json()
    too_fast = await env.client.post("/api/v1/leads", json=lead_payload("callback", form_token=schema["form_token"]))
    assert too_fast.status_code == 400 and too_fast.json()["error"]["code"] == "form_too_fast"
    await asyncio.sleep(0.6)
    ok = await env.client.post("/api/v1/leads", json=lead_payload("callback", form_token=schema["form_token"]))
    assert ok.status_code == 201
    wrong_form = await env.client.post("/api/v1/leads", json=lead_payload("repair", form_token=schema["form_token"]))
    assert wrong_form.status_code == 400


async def test_unknown_service_and_estimate(env: Env) -> None:
    resp = await env.client.post(
        "/api/v1/leads",
        json=lead_payload("repair", service_slug="nope", estimate_id="00000000-0000-0000-0000-000000000000"),
    )
    assert resp.status_code == 422
    assert set(resp.json()["error"]["fields"]) == {"service_slug", "estimate_id"}


async def test_outbox_retry_does_not_break_lead(env: Env) -> None:
    env.email.fail_next = 1
    resp = await env.client.post("/api/v1/leads", json=lead_payload("callback"))
    assert resp.status_code == 201
    await env.container.outbox.process_batch()
    async with env.container.session_factory() as s:
        failed = await s.scalar(select(OutboxMessage).where(OutboxMessage.channel == "email"))
        assert failed is not None and failed.status == "pending" and failed.attempts == 1 and failed.last_error
