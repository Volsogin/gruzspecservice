"""Content, bootstrap caching, forms, calculator, dispatch zone, reviews/cases, geocoder, system endpoints."""

from __future__ import annotations

import gzip
import json

import brotli
import httpx
import pytest

from app.integrations.geocoder.dgis import DgisGeocoder
from tests.conftest import Env, lead_payload


async def test_health(env: Env) -> None:
    assert (await env.client.get("/healthz")).json() == {"status": "ok"}
    ready = (await env.client.get("/readyz")).json()
    assert ready["database"] is True and ready["integrations"]["llm"] is False


async def test_error_format_and_security_headers(env: Env) -> None:
    resp = await env.client.get("/api/v1/cases/99999")
    assert resp.status_code == 404 and resp.json() == {"error": {"code": "not_found", "message": "Кейс не найден"}}
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'none'" in resp.headers["content-security-policy"]
    assert resp.headers["x-request-id"]
    missing = await env.client.get("/api/v1/nope")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"


async def test_public_settings(env: Env) -> None:
    data = (await env.client.get("/api/v1/settings/public")).json()
    assert data["company"]["legal_name"] == "ООО «ГРУЗСПЕЦСЕРВИС»"
    assert data["contacts"]["phone"] == "+79603555765"
    assert data["address"]["lat"] and data["address"]["lon"]
    assert data["work_status"]["is_open"] is True and data["timezone"] == "Europe/Saratov"
    assert data["stats"]["is_demo"] is True
    assert set(data["review_links"]) >= {"yandex", "2gis"}


async def test_bootstrap_etag_and_compression(env: Env) -> None:
    resp = await env.client.get("/api/v1/bootstrap", headers={"Accept-Encoding": "br"})
    assert resp.headers["content-encoding"] == "br" and resp.headers["etag"]
    body = json.loads(resp.content) if resp.content[:1] == b"{" else json.loads(brotli.decompress(resp.content))
    assert {"settings", "services", "stats", "reviews", "work_status", "dispatch_zone", "brands"} <= set(body)
    assert len(body["services"]) >= 6 and len(body["reviews"]["top"]) == 6
    etag = resp.headers["etag"]
    cached = await env.client.get("/api/v1/bootstrap", headers={"If-None-Match": etag})
    assert cached.status_code == 304
    gz = await env.client.get("/api/v1/bootstrap", headers={"Accept-Encoding": "gzip"})
    assert gz.headers["content-encoding"] == "gzip" and gz.headers["etag"] == etag
    raw = gz.content if gz.content[:1] == b"{" else gzip.decompress(gz.content)
    assert json.loads(raw)["settings"]["company"]["name"] == "ГРУЗСПЕЦСЕРВИС"


async def test_services_have_prefill_and_required_set(env: Env) -> None:
    services = (await env.client.get("/api/v1/services")).json()
    slugs = {s["slug"] for s in services}
    assert {
        "sto-repair",
        "onsite-repair",
        "onsite-diagnostics",
        "auto-electrician",
        "tow-truck",
        "parts",
        "fleet-service",
    } <= slugs
    tow = next(s for s in services if s["slug"] == "tow-truck")
    assert tow["form_type"] == "tow"
    assert tow["prefill"] == {"lead_type": "tow", "service_slug": "tow-truck", "location_mode": "onsite"}


@pytest.mark.parametrize("form_type", ["repair", "onsite", "tow", "parts", "corporate", "callback"])
async def test_form_schemas(env: Env, form_type: str) -> None:
    schema = (await env.client.get(f"/api/v1/forms/{form_type}")).json()
    names = {f["name"] for f in schema["fields"]}
    assert {"phone", "consent"} <= names and schema["form_token"]
    assert schema["consent"]["version"] == "2026-11-v1"
    if form_type in ("onsite", "tow"):
        loc = next(f for f in schema["fields"] if f["name"] == "location")
        assert loc["wire_fields"] == ["lat", "lon", "address"] and schema["location_mode"] == "onsite"
    if form_type == "corporate":
        assert {"company_name", "inn", "fleet_size", "email"} <= names
        assert next(f for f in schema["fields"] if f["name"] == "email")["required"] is True
    assert (await env.client.get("/api/v1/forms/chat_handoff")).status_code == 404


async def test_privacy(env: Env) -> None:
    data = (await env.client.get("/api/v1/legal/privacy")).json()
    assert data["version"] == "2026-11-v1" and data["is_placeholder"] is True


async def test_calculator(env: Env) -> None:
    options = (await env.client.get("/api/v1/calculator/options")).json()
    assert {"man", "kamaz", "shacman", "gazon-next", "ural-next"} <= {b["slug"] for b in options["brands"]}
    assert {"diagnostics", "engine", "towing"} <= {w["slug"] for w in options["work_types"]}
    est = (
        await env.client.post(
            "/api/v1/calculator/estimate", json={"brand": "Камаз", "work_type": "diagnostics", "urgent": True}
        )
    ).json()
    # 2500 × 0.9 = 2250 → +20% = 2700
    assert est["price_from"] == 2700 and est["price_label"] == "от 2 700 ₽"
    assert sum(line["amount"] for line in est["breakdown"]) == 2700 and "условные" in est["disclaimer"]
    bad = await env.client.post("/api/v1/calculator/estimate", json={"brand": "Zaporozhets", "work_type": "xxx"})
    assert bad.status_code == 422 and set(bad.json()["error"]["fields"]) == {"brand", "work_type"}

    lead = await env.client.post("/api/v1/leads", json=lead_payload("repair", estimate_id=est["estimate_id"]))
    assert lead.status_code == 201
    detail = (await env.client.get(f"/api/v1/admin/leads/{lead.json()['id']}", headers=env.admin)).json()
    assert detail["source"] == "calculator" and detail["estimate"]["price_from"] == 2700


async def test_dispatch_zone_and_check(env: Env) -> None:
    zone = (await env.client.get("/api/v1/dispatch/zone")).json()
    assert zone["radius_km"] == 15 and zone["eta_minutes"] == 30
    assert zone["geojson"]["geometry"]["type"] == "Polygon"
    center = zone["center"]
    inside = (
        await env.client.post("/api/v1/dispatch/check", json={"lat": center["lat"] + 0.02, "lon": center["lon"]})
    ).json()
    assert inside["zone"] == "inside" and inside["eta_minutes"]
    region = (await env.client.post("/api/v1/dispatch/check", json={"lat": 51.03, "lon": 45.70})).json()
    assert region["zone"] == "region" and region["eta_minutes"] is None and "30" not in region["message"]
    outside = (await env.client.post("/api/v1/dispatch/check", json={"lat": 55.75, "lon": 37.62})).json()
    assert outside["zone"] == "outside"
    invalid = await env.client.post("/api/v1/dispatch/check", json={"lat": 200, "lon": 0})
    assert invalid.status_code == 422 and invalid.json()["error"]["fields"]


async def test_reviews_and_cases(env: Env) -> None:
    page = (await env.client.get("/api/v1/reviews?limit=20")).json()
    assert page["total"] == 10 and all(r["is_demo"] for r in page["items"])
    assert {r["source"] for r in page["items"]} == {"yandex", "2gis", "own"}
    summary = (await env.client.get("/api/v1/reviews/summary")).json()
    assert 4 <= summary["average_rating"] <= 5 and summary["total"] == 10
    assert summary["review_links"]["yandex"].startswith("https://yandex.ru/")
    assert summary["review_links"]["2gis"] == "https://2gis.ru/saratov/firm/70000001089127839/tab/reviews"
    assert summary["review_links"]["placeholders"] == ["yandex"]
    with_case = next(r for r in page["items"] if r["has_case"])
    case = (await env.client.get(f"/api/v1/cases/{with_case['case_id']}")).json()
    assert case["photos"]["before"] and case["photos"]["after"] and case["work_done"]
    assert case["reviews"][0]["id"] == with_case["id"]
    photo = await env.client.get(case["photos"]["after"][0]["preview_url"].replace("https://api.site.test", ""))
    assert photo.status_code == 200 and photo.headers["content-type"] == "image/webp"
    filtered = (await env.client.get("/api/v1/reviews?source=2gis")).json()
    assert filtered["items"] and all(r["source"] == "2gis" for r in filtered["items"])


async def test_geocoder_not_configured(env: Env) -> None:
    resp = await env.client.post("/api/v1/geo/geocode", json={"query": "Саратов"})
    assert resp.status_code == 501 and resp.json()["error"]["code"] == "geocoder_not_configured"


async def test_dgis_geocoder_parsing_with_mock() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "meta": {"code": 200},
                "result": {
                    "total": 1,
                    "items": [
                        {
                            "name": "Автокомбинатовская, 15",
                            "full_name": "Саратов, Автокомбинатовская, 15",
                            "address_name": "Автокомбинатовская, 15",
                            "type": "building",
                            "point": {"lat": 51.6, "lon": 45.95},
                        }
                    ],
                },
            },
        )

    geo = DgisGeocoder("fake-key", transport=httpx.MockTransport(handler))
    items = await geo.geocode("Саратов, Автокомбинатовская 15")
    assert items[0].lat == 51.6 and items[0].full_name.startswith("Саратов")
    await geo.geocode("Саратов, Автокомбинатовская 15")  # cached
    assert len(calls) == 1
    assert calls[0].url.path == "/3.0/items/geocode" and calls[0].url.params["fields"] == "items.point"
