"""LLM provider interface (OpenAI-compatible chat with tool calling, streamed)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ToolCallsRequested:
    calls: list[ToolCall]


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(frozen=True)
class Finished:
    reason: str | None = None
    model: str | None = None


LLMEvent = TextDelta | ToolCallsRequested | Usage | Finished


class LLMUnavailable(Exception):
    """Provider can't answer right now (network, quota, 5xx, timeout) → caller falls back to FAQ."""


@dataclass
class ChatRequest:
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] = field(default_factory=list)
    max_tokens: int = 400
    temperature: float = 0.3


class LLMProvider(Protocol):
    name: str

    def stream(self, request: ChatRequest) -> AsyncIterator[LLMEvent]: ...
