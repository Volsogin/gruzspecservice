"""Composition root: builds every service and integration once (dependency injection by hand).

Tests build the same container with fakes (LLM, notifiers, Telegram client, geocoder).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.ratelimit import RateLimiter
from app.core.security import FormTokenSigner
from app.db.session import create_engine, create_session_factory
from app.integrations.geocoder.dgis import DgisGeocoder, Geocoder
from app.integrations.llm.base import LLMProvider
from app.integrations.llm.openrouter import OpenRouterProvider
from app.integrations.notifiers.base import LogNotifier, Notifier
from app.integrations.notifiers.email import FileEmailNotifier, SmtpEmailNotifier
from app.integrations.notifiers.max import MaxNotifierStub
from app.integrations.notifiers.telegram import TelegramClient, TelegramNotifier
from app.integrations.storage.base import LocalStorage
from app.services.bootstrap import BootstrapCache
from app.services.chat.budget import LlmBudget
from app.services.chat.live import LiveChatHub
from app.services.chat.service import ChatService
from app.services.leads import LeadService
from app.services.outbox import OutboxDispatcher
from app.services.photos import PhotoService
from app.services.telegram_bot import TelegramBot

_UNSET = object()


@dataclass
class Container:
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    storage: LocalStorage
    photos: PhotoService
    limiter: RateLimiter
    signer: FormTokenSigner
    outbox: OutboxDispatcher
    leads: LeadService
    live_chat: LiveChatHub
    chat: ChatService
    bootstrap: BootstrapCache
    telegram_client: TelegramClient | None
    telegram_bot: TelegramBot | None
    geocoder: Geocoder | None
    llm: LLMProvider | None
    notifiers: dict[str, Notifier] = field(default_factory=dict)

    async def aclose(self) -> None:
        if self.telegram_client is not None:
            await self.telegram_client.aclose()
        await self.engine.dispose()


def _email_notifier(s: Settings) -> Notifier:
    if s.smtp_host:
        return SmtpEmailNotifier(
            host=s.smtp_host,
            port=s.smtp_port,
            sender=s.smtp_from,
            user=s.smtp_user,
            password=s.smtp_password.get_secret_value() if s.smtp_password else None,
            starttls=s.smtp_starttls,
            use_ssl=s.smtp_ssl,
            timeout=s.smtp_timeout_seconds,
        )
    return FileEmailNotifier(s.mail_dump_dir, s.smtp_from)


def build_container(
    settings: Settings,
    *,
    llm: LLMProvider | object | None = _UNSET,
    telegram_client: TelegramClient | object | None = _UNSET,
    geocoder: Geocoder | object | None = _UNSET,
    notifiers: dict[str, Notifier] | None = None,
) -> Container:
    engine = create_engine(settings.database_url, echo=settings.db_echo)
    session_factory = create_session_factory(engine)
    storage = LocalStorage(settings.media_dir, settings.media_url_prefix, settings.api_base_url)
    photos = PhotoService(
        storage,
        max_files=settings.max_upload_files,
        max_bytes=settings.max_upload_bytes,
        max_pixels=settings.max_image_pixels,
    )
    limiter = RateLimiter(enabled=settings.rate_limit_enabled)
    secret = settings.secret_key.get_secret_value()
    signer = FormTokenSigner(secret)

    if telegram_client is _UNSET:
        tg: TelegramClient | None = (
            TelegramClient(
                settings.telegram_bot_token.get_secret_value(),
                settings.telegram_api_base,
                proxy=settings.telegram_proxy_url,
            )
            if settings.telegram_bot_token
            else None
        )
    else:
        tg = telegram_client  # type: ignore[assignment]

    if notifiers is None:
        notifiers = {
            "email": _email_notifier(settings),
            "telegram": TelegramNotifier(tg) if tg else LogNotifier("telegram"),
            "max": MaxNotifierStub(),
            "log": LogNotifier("log"),
        }

    if llm is _UNSET:
        llm_provider: LLMProvider | None = (
            OpenRouterProvider(
                api_key=settings.openrouter_api_key.get_secret_value(),
                model=settings.llm_model,
                fallback_models=settings.llm_fallback_models,
                base_url=settings.openrouter_base_url,
                timeout=settings.llm_timeout_seconds,
                app_url=settings.public_base_url,
            )
            if settings.openrouter_api_key
            else None
        )
    else:
        llm_provider = llm  # type: ignore[assignment]

    if geocoder is _UNSET:
        geo: Geocoder | None = (
            DgisGeocoder(settings.dgis_api_key.get_secret_value(), settings.dgis_catalog_base)
            if settings.dgis_api_key
            else None
        )
    else:
        geo = geocoder  # type: ignore[assignment]

    outbox = OutboxDispatcher(session_factory, notifiers, settings, telegram=tg)
    bootstrap = BootstrapCache(session_factory, settings.bootstrap_cache_seconds, settings.bot_username)
    leads = LeadService(settings, session_factory, photos, limiter, signer, on_commit=outbox.kick)
    live = LiveChatHub()
    budget = LlmBudget(session_factory, settings.llm_daily_request_limit, settings.llm_daily_token_limit)
    chat = ChatService(
        settings, session_factory, leads, llm_provider, budget, live, limiter, geo, on_commit=outbox.kick
    )
    bot = TelegramBot(tg, session_factory, settings, live, on_commit=outbox.kick, limiter=limiter) if tg else None
    return Container(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        storage=storage,
        photos=photos,
        limiter=limiter,
        signer=signer,
        outbox=outbox,
        leads=leads,
        live_chat=live,
        chat=chat,
        bootstrap=bootstrap,
        telegram_client=tg,
        telegram_bot=bot,
        geocoder=geo,
        llm=llm_provider,
        notifiers=notifiers,
    )
