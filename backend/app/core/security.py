"""Small security primitives: constant-time token checks, hashing, signed form tokens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

from app.core.errors import AppError


def constant_time_equals(provided: str | None, expected: str | None) -> bool:
    """Compare secrets without leaking timing information; empty values never match."""
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided.encode(), expected.encode())


def new_public_token() -> str:
    """Unguessable token for public order links (192 bits, URL/Telegram-start safe)."""
    return secrets.token_urlsafe(24)


def hash_ip(ip: str | None, secret: str) -> str | None:
    """Keyed hash of the client IP: lets us rate-limit and spot abuse without storing raw IPs."""
    if not ip:
        return None
    return hmac.new(secret.encode(), ip.encode(), hashlib.sha256).hexdigest()[:32]


class FormTokenError(AppError):
    status_code = 400
    code = "form_token_invalid"


class FormTokenSigner:
    """Issues `form_token`s with an embedded timestamp to detect bots that submit instantly."""

    def __init__(self, secret: str) -> None:
        self._key = hashlib.sha256(b"form-token:" + secret.encode()).digest()

    def _sign(self, payload: bytes) -> str:
        return base64.urlsafe_b64encode(hmac.new(self._key, payload, hashlib.sha256).digest()[:16]).decode()

    def issue(self, form_type: str, now: float | None = None) -> str:
        issued = int((now if now is not None else time.time()) * 1000)
        payload = f"{form_type}.{issued}"
        return f"{payload}.{self._sign(payload.encode())}"

    def verify(self, token: str, form_type: str, *, min_age: float, max_age: float, now: float | None = None) -> None:
        """Raise FormTokenError unless the token is authentic, for this form and not too fast/old."""
        try:
            token_type, issued_raw, signature = token.rsplit(".", 2)
            issued = int(issued_raw) / 1000
        except ValueError as exc:
            raise FormTokenError("Обновите страницу и отправьте форму ещё раз") from exc
        expected = self._sign(f"{token_type}.{issued_raw}".encode())
        if not hmac.compare_digest(signature, expected) or token_type != form_type:
            raise FormTokenError("Обновите страницу и отправьте форму ещё раз")
        age = (now if now is not None else time.time()) - issued
        if age < min_age:
            raise FormTokenError(
                "Форма отправлена слишком быстро. Проверьте данные и отправьте ещё раз", code="form_too_fast"
            )
        if age > max_age:
            raise FormTokenError("Форма устарела. Обновите страницу и отправьте ещё раз", code="form_expired")
