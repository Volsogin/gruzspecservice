"""Structured logging with request-id and PII masking."""

from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_PHONE_RE = re.compile(r"(?<!\d)(\+?[78])[\s\-()]*(\d{3})[\s\-()]*(\d{3})[\s\-]*(\d{2})[\s\-]*(\d{2})(?!\d)")
_EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
_TOKEN_RE = re.compile(r"(bot)\d+:[A-Za-z0-9_-]{20,}")


def mask_pii(text: str) -> str:
    """Mask phone numbers, e-mails and bot tokens in free text."""
    text = _PHONE_RE.sub(lambda m: f"+7***{m.group(4)}{m.group(5)}", text)
    text = _EMAIL_RE.sub(lambda m: f"{m.group(1)}***@{m.group(2)}", text)
    return _TOKEN_RE.sub(r"\1***", text)


class PiiMaskingFilter(logging.Filter):
    """Rewrites the formatted message so PII never reaches the log sink."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        record.msg = mask_pii(message)
        record.args = None
        return True


_RESERVED = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = request_id_var.get()
        if rid:
            payload["request_id"] = rid
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = mask_pii(str(value)) if isinstance(value, str) else value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        rid = request_id_var.get()
        base = super().format(record)
        return f"{base} [rid={rid}]" if rid else base


def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    """Configure root logging once at startup."""
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(PiiMaskingFilter())
    handler.setFormatter(
        JsonFormatter() if json_output else TextFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "aiosqlite", "multipart", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # uvicorn's access log prints full URLs incl. order tokens; our middleware logs requests instead.
    logging.getLogger("uvicorn.access").disabled = True
