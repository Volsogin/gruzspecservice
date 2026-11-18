"""Health checks and the Telegram webhook."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header, Request
from sqlalchemy import text

from app.api.deps import ContainerDep
from app.api.v1.schemas import HealthOut, ReadyOut
from app.core.errors import NotFound, Unauthorized
from app.core.security import constant_time_equals

router = APIRouter()


@router.get("/healthz", response_model=HealthOut, tags=["system"], summary="Liveness")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", response_model=ReadyOut, tags=["system"], summary="Readiness: БД и интеграции")
async def readyz(container: ContainerDep) -> dict[str, Any]:
    try:
        async with container.session_factory() as session:
            await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    s = container.settings
    integrations = {
        "smtp": s.smtp_enabled,
        "telegram": s.telegram_enabled,
        "operator_telegram": s.operator_telegram_enabled,
        "operator_email": s.operator_email is not None,
        "llm": container.llm is not None,
        "geocoder": container.geocoder is not None,
    }
    return {"status": "ok" if db_ok else "degraded", "database": db_ok, "integrations": integrations}


@router.post("/api/v1/telegram/webhook", tags=["system"], include_in_schema=False)
async def telegram_webhook(
    request: Request,
    container: ContainerDep,
    secret: Annotated[str | None, Header(alias="X-Telegram-Bot-Api-Secret-Token")] = None,
) -> dict[str, bool]:
    s = container.settings
    if container.telegram_bot is None or s.telegram_mode != "webhook" or s.telegram_webhook_secret is None:
        raise NotFound("Not found")
    if not constant_time_equals(secret, s.telegram_webhook_secret.get_secret_value()):
        raise Unauthorized("bad secret")
    await container.telegram_bot.handle_update(await request.json())
    return {"ok": True}
