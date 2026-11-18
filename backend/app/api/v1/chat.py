"""Chat assistant endpoints (SSE streaming)."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.deps import ClientIpDep, ContainerDep
from app.api.v1.schemas import (
    ERRORS,
    ChatMessageIn,
    ChatSessionIn,
    ChatSessionOut,
    ErrorResponse,
    HandoffIn,
    HandoffOut,
)

router = APIRouter(prefix="/chat", tags=["chat"])

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}

_SSE_DOC = (
    "Ответ — поток `text/event-stream`. События: `meta` {topic, session_status}; `delta` {text} — кусок ответа; "
    "`estimate` — карточка расчёта калькулятора; `action` {type: open_form|show_map|open_calculator|show_services|"
    "phone_required|consent_required|lead_created, ...}; `handoff` {status, live_chat}; `tool` {name}; "
    "`reset` — сбросить уже показанный текст (LLM упал, дальше идёт FAQ-ответ); `done` {message_id, text, topic, "
    "suggested_replies, mode: llm|faq|rule|operator, session_status}; `error` {code, message}. "
    "С `?stream=false` вернётся JSON `{events: [...]}` — удобно для curl и тестов."
)


def sse(event: dict[str, Any]) -> str:
    return f"event: {event['event']}\ndata: {json.dumps(event.get('data', {}), ensure_ascii=False, default=str)}\n\n"


@router.post("/sessions", response_model=ChatSessionOut, status_code=201, summary="Начать диалог")
async def create_session(body: ChatSessionIn, container: ContainerDep, ip: ClientIpDep) -> dict[str, Any]:
    return await container.chat.create_session(consent=body.consent, name=body.name, ip=ip)


@router.get(
    "/sessions/{session_id}/messages",
    response_model=ChatSessionOut,
    summary="История диалога",
    description="`after_id` — вернуть только новые сообщения (для догрузки после переподключения).",
)
async def messages(
    session_id: uuid.UUID, container: ContainerDep, after_id: Annotated[int | None, Query(ge=0)] = None
) -> dict[str, Any]:
    return await container.chat.get_messages(session_id, after_id)


@router.post(
    "/sessions/{session_id}/messages",
    summary="Отправить сообщение (ответ — SSE-поток)",
    description=_SSE_DOC,
    responses={**ERRORS, 404: {"model": ErrorResponse}, 200: {"content": {"text/event-stream": {}}}},
)
async def post_message(
    session_id: uuid.UUID, body: ChatMessageIn, container: ContainerDep, ip: ClientIpDep, stream: bool = True
) -> Any:
    turn = await container.chat.start_turn(session_id, body.text, consent=body.consent, ip=ip)
    events = container.chat.run_turn(turn)
    if not stream:
        return JSONResponse({"events": [e async for e in events]})

    async def body_iter() -> AsyncIterator[str]:
        async for event in events:
            yield sse(event)

    return StreamingResponse(body_iter(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post(
    "/sessions/{session_id}/handoff",
    response_model=HandoffOut,
    summary="Кнопка «Позвать оператора»",
    description="Передача оператору по явному действию пользователя. Если телефона нет — "
    "в `events` придёт `phone_required`; с телефоном и согласием создаётся заявка "
    "`chat_handoff` с расшифровкой диалога.",
    responses=ERRORS,
)
async def handoff(session_id: uuid.UUID, body: HandoffIn, container: ContainerDep, ip: ClientIpDep) -> dict[str, Any]:
    return await container.chat.handoff_by_button(
        session_id, phone=body.phone, name=body.name, consent=body.consent, ip=ip
    )


@router.post("/sessions/{session_id}/close", response_model=ChatSessionOut, summary="Завершить диалог")
async def close(session_id: uuid.UUID, container: ContainerDep) -> dict[str, Any]:
    result = await container.chat.close(session_id)
    return {**result, "messages": []}


@router.get(
    "/sessions/{session_id}/events",
    summary="SSE: ответы живого оператора",
    description="Долгоживущий поток для режима живого чата: событие `operator_message` "
    "{id, text, operator_name, created_at, session_status}; `ping` каждые 20 с.",
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def events(session_id: uuid.UUID, request: Request, container: ContainerDep) -> StreamingResponse:
    await container.chat.get_messages(session_id, after_id=10**12)  # 404 for unknown sessions
    hub = container.live_chat
    queue = hub.subscribe(session_id)

    async def stream() -> AsyncIterator[str]:
        try:
            yield sse({"event": "ready", "data": {}})
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20)
                    yield sse(event)
                except TimeoutError:
                    yield sse({"event": "ping", "data": {}})
        finally:
            hub.unsubscribe(session_id, queue)

    return StreamingResponse(stream(), media_type="text/event-stream", headers=SSE_HEADERS)
