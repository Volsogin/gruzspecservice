"""Application configuration.

All configuration comes from environment variables (optionally a `.env` file).
Secrets have no defaults and are never written to logs.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    """Typed view of the process environment."""

    model_config = SettingsConfigDict(
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- general -------------------------------------------------------------
    app_env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    log_json: bool = True
    public_base_url: str = "http://localhost:5173"
    api_base_url: str = "http://localhost:8000"
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:3000"]
    )
    secret_key: SecretStr = Field(default_factory=lambda: SecretStr(secrets.token_urlsafe(32)))
    trusted_hosts: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["*"])

    # --- storage ---------------------------------------------------------------
    database_url: str = f"sqlite+aiosqlite:///{BACKEND_DIR / 'var' / 'dev.db'}"
    db_echo: bool = False
    media_dir: Path = BACKEND_DIR / "var" / "media"
    media_url_prefix: str = "/media"
    mail_dump_dir: Path = BACKEND_DIR / "var" / "mail"
    frontend_dist_dir: Path | None = None
    seeds_dir: Path = BACKEND_DIR / "seeds"

    # --- request limits ----------------------------------------------------------
    max_body_bytes: int = 27 * 1024 * 1024
    max_upload_files: int = 5
    max_upload_bytes: int = 5 * 1024 * 1024
    max_image_pixels: int = 40_000_000

    # --- anti-spam ---------------------------------------------------------------
    rate_limit_enabled: bool = True
    leads_per_ip_per_hour: int = 20
    leads_per_phone_per_hour: int = 5
    orders_per_ip_per_minute: int = 30
    chat_messages_per_ip_per_minute: int = 20
    form_token_required: bool = False
    form_min_fill_seconds: float = 3.0
    form_token_max_age_seconds: int = 6 * 3600

    # --- background work -----------------------------------------------------------
    run_background_tasks: bool = True
    outbox_poll_seconds: float = 2.0
    outbox_max_attempts: int = 8

    # --- notifications: e-mail -------------------------------------------------------
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = True
    smtp_ssl: bool = False
    smtp_from: str = "ГРУЗСПЕЦСЕРВИС <no-reply@localhost>"
    smtp_timeout_seconds: float = 15.0
    operator_email: str | None = None

    # --- notifications: Telegram --------------------------------------------------------
    telegram_bot_token: SecretStr | None = None
    bot_username: str | None = None
    operator_tg_chat_id: int | None = None
    telegram_api_base: str = "https://api.telegram.org"
    telegram_mode: Literal["polling", "webhook", "off"] = "polling"
    telegram_webhook_secret: SecretStr | None = None

    # --- notifications: Max (stub) -------------------------------------------------------
    max_bot_token: SecretStr | None = None
    max_bot_username: str | None = None

    # --- admin ---------------------------------------------------------------------
    admin_token: SecretStr | None = None

    # --- LLM (OpenRouter) ------------------------------------------------------------
    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "google/gemini-2.5-flash-lite"
    llm_fallback_models: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["openai/gpt-4.1-nano"])
    llm_max_tokens: int = 400
    llm_temperature: float = 0.3
    llm_timeout_seconds: float = 25.0
    llm_daily_request_limit: int = 400
    llm_daily_token_limit: int = 400_000
    chat_max_message_chars: int = 1000
    chat_max_messages_per_session: int = 40
    chat_history_window: int = 12
    chat_operator_wait_minutes: int = 10

    # --- 2GIS ------------------------------------------------------------------------
    dgis_api_key: SecretStr | None = None
    dgis_catalog_base: str = "https://catalog.api.2gis.com/3.0"

    # --- caching -----------------------------------------------------------------------
    bootstrap_cache_seconds: int = 30

    @field_validator("cors_origins", "trusted_hosts", "llm_fallback_models", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("operator_email", "smtp_host", "smtp_user", "bot_username", "max_bot_username", mode="before")
    @classmethod
    def _empty_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator(
        "telegram_bot_token",
        "openrouter_api_key",
        "dgis_api_key",
        "admin_token",
        "smtp_password",
        "max_bot_token",
        "telegram_webhook_secret",
        "operator_tg_chat_id",
        "frontend_dist_dir",
        mode="before",
    )
    @classmethod
    def _empty_secret_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("secret_key", mode="before")
    @classmethod
    def _secret_key_or_random(cls, value: object) -> object:
        # An empty SECRET_KEY must never become an empty HMAC key: fall back to a per-process random one.
        if value is None or (isinstance(value, str) and not value.strip()):
            return secrets.token_urlsafe(32)
        return value

    # --- derived flags ---------------------------------------------------------------------
    @property
    def telegram_enabled(self) -> bool:
        return self.telegram_bot_token is not None

    @property
    def operator_telegram_enabled(self) -> bool:
        return self.telegram_enabled and self.operator_tg_chat_id is not None

    @property
    def smtp_enabled(self) -> bool:
        return self.smtp_host is not None

    @property
    def llm_enabled(self) -> bool:
        return self.openrouter_api_key is not None

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def tracking_url(self, public_token: str) -> str:
        """Public link to the order page rendered by the frontend."""
        return f"{self.public_base_url.rstrip('/')}/order/{public_token}"

    def telegram_bind_url(self, public_token: str) -> str | None:
        if not self.bot_username:
            return None
        return f"https://t.me/{self.bot_username.lstrip('@')}?start={public_token}"

    def max_bind_url(self, public_token: str) -> str | None:
        if not self.max_bot_username:
            return None
        return f"https://max.ru/{self.max_bot_username.lstrip('@')}?start={public_token}"


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings singleton (overridable in tests)."""
    return Settings()
