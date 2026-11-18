"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

from app.admin import setup_admin
from app.api.v1 import admin as admin_api
from app.api.v1 import chat, content, leads, system, tools
from app.container import Container, build_container
from app.core.config import Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import BodySizeLimitMiddleware, RequestContextMiddleware, SecurityHeadersMiddleware

logger = logging.getLogger(__name__)

API_DESCRIPTION = """
API сайта грузового автосервиса **ООО «ГРУЗСПЕЦСЕРВИС»** (хакатон).

* Единый формат ошибок: `{"error": {"code", "message", "fields?"}}`.
* Поток заявки: `GET /services` → `GET /forms/{form_type}` → `POST /leads` → экран подтверждения →
  `GET /orders/{public_token}`.
* Все цифры, отзывы и цены в seed — **демонстрационные**.
"""

TAGS = [
    {"name": "content", "description": "Контент сайта: настройки, bootstrap, услуги, политика ПДн"},
    {"name": "forms", "description": "Схемы форм заявок по типам"},
    {"name": "leads", "description": "Приём заявок и статус по ссылке"},
    {"name": "calculator", "description": "Калькулятор «от N ₽»"},
    {"name": "dispatch", "description": "Выезд за 30 минут: зона, проверка точки, геокодер 2ГИС"},
    {"name": "reviews", "description": "Отзывы и кейсы «до/после»"},
    {"name": "chat", "description": "ИИ-ассистент и передача оператору"},
    {"name": "admin", "description": "Операторский API (Bearer ADMIN_TOKEN)"},
    {"name": "system", "description": "Health checks"},
]


class CachedStatic(StaticFiles):
    """Media file names contain a content hash → safe to cache "forever"."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    """Optional: serve the built SPA from the same origin, with index.html fallback."""
    index = dist / "index.html"
    app.mount("/assets", CachedStatic(directory=dist / "assets", check_dir=False), name="frontend-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> Response:
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(dist.resolve()):  # noqa: ASYNC240
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)
    container = container or build_container(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.media_dir.mkdir(parents=True, exist_ok=True)
        stop = asyncio.Event()
        tasks: list[asyncio.Task[None]] = []
        if settings.run_background_tasks:
            tasks.append(asyncio.create_task(container.outbox.run_forever(stop), name="outbox"))
            if container.telegram_bot is not None and settings.telegram_mode == "polling":
                tasks.append(asyncio.create_task(container.telegram_bot.run_polling(stop), name="telegram"))
        logger.info(
            "startup",
            extra={
                "env": settings.app_env,
                "llm": container.llm is not None,
                "telegram": settings.telegram_enabled,
                "smtp": settings.smtp_enabled,
            },
        )
        try:
            yield
        finally:
            stop.set()
            container.outbox.kick()
            for task in tasks:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            await container.aclose()

    app = FastAPI(
        title="ГРУЗСПЕЦСЕРВИС API",
        version="1.0.0",
        description=API_DESCRIPTION,
        openapi_tags=TAGS,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.state.container = container
    install_error_handlers(app)

    # Order matters: the last added runs first.
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "OPTIONS"],
        allow_headers=["Content-Type", "Idempotency-Key", "Authorization", "X-Request-ID", "If-None-Match"],
        expose_headers=["ETag", "X-Request-ID", "Idempotent-Replayed", "Retry-After"],
        max_age=600,
    )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.app_env == "prod")
    app.add_middleware(RequestContextMiddleware)

    app.include_router(system.router)
    for router in (content.router, leads.router, tools.router, chat.router, admin_api.router):
        app.include_router(router, prefix="/api/v1")

    app.mount(settings.media_url_prefix, CachedStatic(directory=settings.media_dir, check_dir=False), name="media")
    setup_admin(app, container)
    if settings.frontend_dist_dir and (settings.frontend_dist_dir / "index.html").is_file():
        _mount_frontend(app, settings.frontend_dist_dir)
    return app


def app_factory() -> FastAPI:
    """Entry point for `uvicorn --factory app.main:app_factory`."""
    return create_app()
