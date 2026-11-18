"""Minimal Telegram Bot API client and notifier (httpx, no extra SDK)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.integrations.notifiers.base import InlineButton, OutgoingMessage, SendError, SendResult

logger = logging.getLogger(__name__)


class TelegramApiError(SendError):
    def __init__(self, method: str, status: int, description: str) -> None:
        permanent = status in (400, 403, 404)
        super().__init__(f"telegram {method}: {status} {description}", permanent=permanent)
        self.status = status
        self.description = description


def keyboard(buttons: list[list[InlineButton]]) -> dict[str, Any]:
    rows = []
    for row in buttons:
        rendered = []
        for b in row:
            item: dict[str, Any] = {"text": b.text}
            if b.url:
                item["url"] = b.url
            else:
                item["callback_data"] = b.callback_data or "noop"
            rendered.append(item)
        rows.append(rendered)
    return {"inline_keyboard": rows}


class TelegramClient:
    def __init__(
        self,
        token: str,
        base_url: str = "https://api.telegram.org",
        timeout: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
        proxy: str | None = None,
    ) -> None:
        self._base = f"{base_url.rstrip('/')}/bot{token}"
        # Proxy applies to Telegram only (http://, https:// or socks5:// e.g. a local v2rayN/xray port);
        # trust_env=False so a global HTTP(S)_PROXY doesn't silently change the route.
        self._http = httpx.AsyncClient(timeout=timeout, transport=transport, proxy=proxy, trust_env=False)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def call(self, method: str, payload: dict[str, Any], timeout: float | None = None) -> Any:
        try:
            response = await self._http.post(
                f"{self._base}/{method}", json=payload, timeout=timeout or self._http.timeout
            )
        except httpx.HTTPError as exc:
            # Never include the URL: it contains the bot token.
            raise SendError(f"telegram {method}: network error {type(exc).__name__}") from None
        try:
            body = response.json()
        except ValueError:
            raise SendError(f"telegram {method}: bad response {response.status_code}") from None
        if not body.get("ok"):
            raise TelegramApiError(
                method, int(body.get("error_code", response.status_code)), str(body.get("description", ""))
            )
        return body.get("result")

    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        *,
        buttons: list[list[InlineButton]] | None = None,
        reply_to_message_id: int | None = None,
        reply_keyboard: list[list[dict[str, Any]]] | None = None,
    ) -> dict[str, Any]:
        """`buttons` → inline keyboard; `reply_keyboard` → persistent keyboard under the input
        (e.g. `[[{"text": "📱 Поделиться номером", "request_contact": True}]]`)."""
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text[:4096],
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        }
        if buttons:
            payload["reply_markup"] = keyboard(buttons)
        elif reply_keyboard:
            payload["reply_markup"] = {"keyboard": reply_keyboard, "resize_keyboard": True, "is_persistent": True}
        if reply_to_message_id:
            payload["reply_parameters"] = {"message_id": reply_to_message_id, "allow_sending_without_reply": True}
        result: dict[str, Any] = await self.call("sendMessage", payload)
        return result

    async def edit_message_text(
        self, chat_id: int | str, message_id: int, text: str, buttons: list[list[InlineButton]] | None = None
    ) -> None:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text[:4096],
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
            "reply_markup": keyboard(buttons or []),
        }
        try:
            await self.call("editMessageText", payload)
        except TelegramApiError as exc:
            if "message is not modified" not in exc.description:
                raise

    async def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> None:
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text[:200]
        await self.call("answerCallbackQuery", payload)

    async def get_updates(self, offset: int | None, timeout: int = 25) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            payload["offset"] = offset
        result: list[dict[str, Any]] = await self.call("getUpdates", payload, timeout=timeout + 10)
        return result

    async def delete_webhook(self) -> None:
        await self.call("deleteWebhook", {"drop_pending_updates": False})

    async def set_webhook(self, url: str, secret_token: str) -> None:
        await self.call(
            "setWebhook", {"url": url, "secret_token": secret_token, "allowed_updates": ["message", "callback_query"]}
        )


class TelegramNotifier:
    channel = "telegram"

    def __init__(self, client: TelegramClient) -> None:
        self.client = client

    async def send(self, message: OutgoingMessage) -> SendResult:
        result = await self.client.send_message(
            message.recipient,
            message.html or message.text,
            buttons=message.buttons or None,
            reply_to_message_id=message.reply_to_message_id,
        )
        return SendResult(external_id=str(result.get("message_id")))
