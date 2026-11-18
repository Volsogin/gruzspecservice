"""FastAPI dependencies: container, DB session, client IP, admin auth."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core.errors import NotConfigured, Unauthorized
from app.core.security import constant_time_equals


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


async def get_db(container: ContainerDep) -> AsyncIterator[AsyncSession]:
    async with container.session_factory() as session:
        yield session


DbDep = Annotated[AsyncSession, Depends(get_db)]


def client_ip(request: Request) -> str | None:
    # With uvicorn --proxy-headers and FORWARDED_ALLOW_IPS, request.client is the real client.
    return request.client.host if request.client else None


ClientIpDep = Annotated[str | None, Depends(client_ip)]


def require_admin(container: ContainerDep, authorization: Annotated[str | None, Header()] = None) -> str:
    """Bearer ADMIN_TOKEN, compared in constant time. Admin API is off when the token is unset."""
    expected = container.settings.admin_token
    if expected is None:
        raise NotConfigured("Админ-API отключено: задайте ADMIN_TOKEN", code="admin_disabled")
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not constant_time_equals(token.strip(), expected.get_secret_value()):
        raise Unauthorized(
            "Нужен заголовок Authorization: Bearer <ADMIN_TOKEN>", headers={"WWW-Authenticate": "Bearer"}
        )
    return "admin:api"


AdminDep = Annotated[str, Depends(require_admin)]
