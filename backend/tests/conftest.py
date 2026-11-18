"""Test fixtures: a migrated+seeded template SQLite DB copied per test, fakes for every integration."""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from alembic import command
from alembic.config import Config

from app.container import Container, build_container
from app.core.config import BACKEND_DIR, Settings
from app.db.session import create_engine, create_session_factory
from app.integrations.llm.base import ChatRequest, LLMEvent
from app.integrations.notifiers.base import InlineButton, LogNotifier, OutgoingMessage, SendError, SendResult
from app.integrations.notifiers.telegram import TelegramNotifier
from app.integrations.storage.base import LocalStorage
from app.main import create_app
from app.seeding import run_seed

OPERATOR_CHAT = -1001


class FakeNotifier:
    def __init__(self, channel: str) -> None:
        self.channel = channel
        self.sent: list[OutgoingMessage] = []
        self.fail_next = 0

    async def send(self, message: OutgoingMessage) -> SendResult:
        if self.fail_next:
            self.fail_next -= 1
            raise SendError("boom")
        self.sent.append(message)
        return SendResult(external_id=f"{self.channel}-{len(self.sent)}")


class FakeTelegram:
    """Duck-typed TelegramClient."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.edits: list[dict[str, Any]] = []
        self.answers: list[dict[str, Any]] = []
        self._next_id = 100

    async def send_message(
        self,
        chat_id: Any,
        text: str,
        *,
        buttons: list[list[InlineButton]] | None = None,
        reply_to_message_id: int | None = None,
        reply_keyboard: list[list[dict[str, Any]]] | None = None,
        force_reply: str | None = None,
    ) -> dict[str, Any]:
        self._next_id += 1
        self.sent.append(
            {
                "chat_id": chat_id,
                "text": text,
                "buttons": buttons or [],
                "message_id": self._next_id,
                "reply_to": reply_to_message_id,
                "keyboard": reply_keyboard,
                "force_reply": force_reply,
            }
        )
        return {"message_id": self._next_id}

    async def edit_message_text(
        self, chat_id: Any, message_id: int, text: str, buttons: list[list[InlineButton]] | None = None
    ) -> None:
        self.edits.append({"chat_id": chat_id, "message_id": message_id, "text": text, "buttons": buttons or []})

    async def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> None:
        self.answers.append({"id": callback_query_id, "text": text})

    async def aclose(self) -> None:
        return None

    def to(self, chat_id: Any) -> list[dict[str, Any]]:
        return [m for m in self.sent if m["chat_id"] == chat_id or str(m["chat_id"]) == str(chat_id)]


class FakeLLM:
    name = "fake"

    def __init__(self) -> None:
        self.script: list[list[LLMEvent] | Exception] = []
        self.requests: list[ChatRequest] = []

    async def stream(self, request: ChatRequest) -> AsyncIterator[LLMEvent]:
        self.requests.append(request)
        step = self.script.pop(0) if self.script else []
        if isinstance(step, Exception):
            raise step
        for event in step:
            yield event


@pytest.fixture(scope="session")
def template_db(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """Run real Alembic migrations + seeds once; tests copy the resulting file."""
    root = tmp_path_factory.mktemp("template")
    db_path, media = root / "template.db", root / "media"
    url = f"sqlite+aiosqlite:///{db_path}"
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "app/db/migrations"))
    cfg.attributes["database_url"] = url
    command.upgrade(cfg, "head")

    async def seed() -> None:
        engine = create_engine(url)
        async with create_session_factory(engine)() as session:
            await run_seed(session, BACKEND_DIR / "seeds", LocalStorage(media))
            await session.commit()
        await engine.dispose()

    asyncio.run(seed())
    return db_path, media


def make_settings(tmp: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "app_env": "test",
        "database_url": f"sqlite+aiosqlite:///{tmp / 'test.db'}",
        "media_dir": tmp / "media",
        "mail_dump_dir": tmp / "mail",
        "secret_key": "test-secret",
        "public_base_url": "https://site.test",
        "api_base_url": "https://api.site.test",
        "run_background_tasks": False,
        "log_json": False,
        "log_level": "INFO",  # INFO so every log call (and its `extra` keys) is exercised
        "operator_email": "ops@example.test",
        "telegram_bot_token": "123:FAKE",
        "bot_username": "test_bot",
        "operator_tg_chat_id": OPERATOR_CHAT,
        "admin_token": "test-admin-token",
        "openrouter_api_key": None,
        "dgis_api_key": None,
        "smtp_host": None,
        "form_token_required": False,
        "bootstrap_cache_seconds": 0,
        "chat_operator_wait_minutes": 10,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


class Env:
    """Everything a test needs: client, container and fakes."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        container: Container,
        email: FakeNotifier,
        tg: FakeTelegram,
        llm: FakeLLM | None,
    ) -> None:
        self.client = client
        self.container = container
        self.email = email
        self.tg = tg
        self.llm = llm

    async def drain(self) -> None:
        await self.container.outbox.drain()

    @property
    def admin(self) -> dict[str, str]:
        return {"Authorization": "Bearer test-admin-token"}


@pytest.fixture
def settings_overrides() -> dict[str, Any]:
    return {}


@pytest.fixture
def use_llm() -> bool:
    return False


@pytest.fixture
async def env(
    tmp_path: Path, template_db: tuple[Path, Path], settings_overrides: dict[str, Any], use_llm: bool
) -> AsyncIterator[Env]:
    db_path, media = template_db
    shutil.copy(db_path, tmp_path / "test.db")
    shutil.copytree(media, tmp_path / "media")
    settings = make_settings(tmp_path, **settings_overrides)
    email = FakeNotifier("email")
    tg = FakeTelegram()
    llm = FakeLLM() if use_llm else None
    container = build_container(
        settings,
        llm=llm,
        telegram_client=tg,
        geocoder=None,  # type: ignore[arg-type]
        notifiers={
            "email": email,
            "telegram": TelegramNotifier(tg),  # type: ignore[arg-type]
            "log": LogNotifier("log"),
            "max": FakeNotifier("max"),
        },
    )
    app = create_app(settings, container)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield Env(client, container, email, tg, llm)
    await container.aclose()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def lead_payload(lead_type: str = "repair", **extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"lead_type": lead_type, "name": "Иван", "phone": "8 (927) 123-45-67", "consent": True}
    per_type: dict[str, dict[str, Any]] = {
        "repair": {"vehicle_brand": "MAN", "description": "Стучит двигатель"},
        "onsite": {
            "vehicle_brand": "Volvo",
            "description": "Не заводится",
            "is_drivable": "no",
            "lat": 51.55,
            "lon": 46.02,
            "address": "Саратов, Сокурский тракт",
        },
        "tow": {"vehicle_type": "tractor", "destination": "our_sto", "is_drivable": "no", "lat": 51.6, "lon": 45.9},
        "parts": {
            "vehicle_brand": "КамАЗ",
            "description": "Колодки передние",
            "urgency": "today",
            "delivery": "pickup",
        },
        "corporate": {
            "company_name": "ООО Ромашка",
            "fleet_size": 12,
            "email": "fleet@example.com",
            "inn": "7707083893",
            "fleet_types": ["tractor", "dump"],
        },
        "callback": {},
    }
    return {**base, **per_type[lead_type], **extra}


@pytest.fixture
def no_rate_limit(env: Env) -> Iterator[None]:
    env.container.limiter.enabled = False
    yield
    env.container.limiter.enabled = True
