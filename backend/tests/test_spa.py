"""The built site is served by the API itself (one origin): SPA fallback, assets, API 404s stay JSON."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.conftest import Env

pytestmark = pytest.mark.anyio


@pytest.fixture
def settings_overrides(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    dist: Path = tmp_path_factory.mktemp("dist")
    (dist / "assets").mkdir()
    (dist / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    return {"frontend_dist_dir": dist}


async def test_spa_routes_fall_back_to_index(env: Env) -> None:
    for path in ("/", "/order/abcdefghijklmnopqrstuv", "/privacy", "/no-such-page"):
        resp = await env.client.get(path)
        assert resp.status_code == 200, path
        assert "id=root" in resp.text
        assert resp.headers["cache-control"] == "no-cache"


async def test_assets_are_cached_and_api_404_is_json(env: Env) -> None:
    asset = await env.client.get("/assets/app.js")
    assert asset.status_code == 200 and "immutable" in asset.headers["cache-control"]
    missing = await env.client.get("/api/v1/definitely-missing")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    assert (await env.client.get("/api/v1/bootstrap")).status_code == 200
