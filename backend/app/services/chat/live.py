"""In-process pub/sub for chat sessions (operator replies → website over SSE)."""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.db.models import ChatMessage, ChatSession


class LiveChatHub:
    def __init__(self) -> None:
        self._subscribers: dict[uuid.UUID, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    def subscribe(self, session_id: uuid.UUID) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._subscribers[session_id].add(queue)
        return queue

    def unsubscribe(self, session_id: uuid.UUID, queue: asyncio.Queue[dict[str, Any]]) -> None:
        subs = self._subscribers.get(session_id)
        if subs:
            subs.discard(queue)
            if not subs:
                self._subscribers.pop(session_id, None)

    def publish(self, session_id: uuid.UUID, event: dict[str, Any]) -> None:
        for queue in list(self._subscribers.get(session_id, ())):
            if not queue.full():
                queue.put_nowait(event)

    async def post_operator_message(
        self, db: AsyncSession, session_id: uuid.UUID, text: str, operator_name: str
    ) -> ChatMessage | None:
        """Store an operator reply and push it to connected browsers. Caller commits."""
        chat = await db.get(ChatSession, session_id)
        if chat is None or chat.status == "closed":
            return None
        if chat.status != "operator":
            chat.status = "operator"
            chat.operator_joined_at = utcnow()
        message = ChatMessage(
            session_id=session_id,
            role="operator",
            content=text[:4000],
            mode="operator",
            meta={"operator_name": operator_name},
        )
        db.add(message)
        await db.flush()
        self.publish(
            session_id,
            {
                "event": "operator_message",
                "data": {
                    "id": message.id,
                    "text": message.content,
                    "operator_name": operator_name,
                    "created_at": message.created_at.isoformat(),
                    "session_status": chat.status,
                },
            },
        )
        return message
