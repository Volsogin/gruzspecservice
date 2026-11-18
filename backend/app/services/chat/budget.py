"""Daily LLM budget (requests + tokens). When exhausted the assistant switches to FAQ mode."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import LlmUsage
from app.integrations.llm.base import Usage


class LlmBudget:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], daily_requests: int, daily_tokens: int
    ) -> None:
        self.session_factory = session_factory
        self.daily_requests = daily_requests
        self.daily_tokens = daily_tokens

    @staticmethod
    def _today() -> datetime:
        return datetime.now(UTC)

    async def can_spend(self) -> bool:
        async with self.session_factory() as session:
            row = await session.get(LlmUsage, self._today().date())
        if row is None:
            return True
        return row.requests < self.daily_requests and row.prompt_tokens + row.completion_tokens < self.daily_tokens

    async def record(self, usage: Usage | None) -> None:
        day = self._today().date()
        async with self.session_factory() as session:
            row = await session.scalar(select(LlmUsage).where(LlmUsage.day == day).with_for_update())
            if row is None:
                row = LlmUsage(day=day, requests=0, prompt_tokens=0, completion_tokens=0)
                session.add(row)
            row.requests += 1
            if usage:
                row.prompt_tokens += usage.prompt_tokens
                row.completion_tokens += usage.completion_tokens
            await session.commit()
