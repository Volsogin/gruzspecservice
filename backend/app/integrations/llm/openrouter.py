"""OpenRouter provider (OpenAI-compatible `/chat/completions`, SSE streaming, tool calls)."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.integrations.llm.base import (
    ChatRequest,
    Finished,
    LLMEvent,
    LLMUnavailable,
    TextDelta,
    ToolCall,
    ToolCallsRequested,
    Usage,
)

logger = logging.getLogger(__name__)


class OpenRouterProvider:
    name = "openrouter"

    def __init__(
        self,
        api_key: str,
        model: str,
        fallback_models: list[str] | None = None,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout: float = 25.0,
        app_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        proxy: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._proxy = proxy
        self.model = model
        self.fallback_models = [m for m in (fallback_models or []) if m and m != model]
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._timeout = httpx.Timeout(timeout, connect=10.0)
        self._app_url = app_url
        self._transport = transport

    def _payload(self, request: ChatRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": request.messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "stream": True,
            "usage": {"include": True},
        }
        if self.fallback_models:
            payload["models"] = [self.model, *self.fallback_models]
        if request.tools:
            payload["tools"] = request.tools
            payload["tool_choice"] = "auto"
        return payload

    async def stream(self, request: ChatRequest) -> AsyncIterator[LLMEvent]:
        """One retry when the connection itself failed and nothing has been streamed yet (flaky networks/VPN)."""
        for attempt in (1, 2):
            started = False
            try:
                async for event in self._stream_once(request):
                    started = True
                    yield event
                return
            except LLMUnavailable as exc:
                if started or attempt == 2 or not str(exc).startswith("Connect"):
                    raise
                logger.warning("llm_connect_retry", extra={"reason": str(exc)})

    async def _stream_once(self, request: ChatRequest) -> AsyncIterator[LLMEvent]:
        headers = {"Authorization": f"Bearer {self._api_key}", "X-Title": "GRUZSPECSERVICE assistant"}
        if self._app_url:
            headers["HTTP-Referer"] = self._app_url
        tool_parts: dict[int, dict[str, str]] = {}
        finish_reason: str | None = None
        model: str | None = None
        try:
            async with (
                httpx.AsyncClient(
                    timeout=self._timeout, transport=self._transport, proxy=self._proxy, trust_env=False
                ) as client,
                client.stream("POST", self._url, json=self._payload(request), headers=headers) as resp,
            ):
                if resp.status_code != 200:
                    body = (await resp.aread())[:300].decode(errors="replace")
                    logger.warning("llm_http_error", extra={"status": resp.status_code, "body": body})
                    raise LLMUnavailable(f"status {resp.status_code}")
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue  # SSE comments such as ": OPENROUTER PROCESSING"
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except ValueError:
                        continue
                    if "error" in chunk:
                        raise LLMUnavailable(str(chunk["error"])[:200])
                    model = chunk.get("model", model)
                    if usage := chunk.get("usage"):
                        yield Usage(int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0))
                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta") or {}
                        if text := delta.get("content"):
                            yield TextDelta(text)
                        for tc in delta.get("tool_calls") or []:
                            part = tool_parts.setdefault(int(tc.get("index", 0)), {"id": "", "name": "", "args": ""})
                            part["id"] = tc.get("id") or part["id"]
                            fn = tc.get("function") or {}
                            part["name"] = fn.get("name") or part["name"]
                            part["args"] += fn.get("arguments") or ""
                        finish_reason = choice.get("finish_reason") or finish_reason
        except httpx.HTTPError as exc:
            raise LLMUnavailable(type(exc).__name__) from None

        if tool_parts:
            calls = [
                ToolCall(p["id"] or f"call_{i}", p["name"], p["args"] or "{}")
                for i, p in sorted(tool_parts.items())
                if p["name"]
            ]
            if calls:
                yield ToolCallsRequested(calls)
        yield Finished(finish_reason, model)
