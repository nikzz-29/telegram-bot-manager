"""Application settings loaded from the environment (pydantic-settings)."""

from functools import lru_cache
import re
from typing import Final
from urllib.parse import urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# RFC 7518 §3.2: an HMAC-SHA256 key should be at least as long as the digest.
MIN_JWT_SECRET_BYTES: Final = 32
# Long enough to satisfy the RFC and pyjwt's key-length warning, so development
# runs quiet; the production validator below still rejects it by exact match.
PLACEHOLDER_JWT_SECRET: Final = "change-me-in-production-this-is-not-a-secret"
# Used when `PANEL_COMMAND` is unset or is not something Telegram would accept.
DEFAULT_PANEL_COMMAND: Final = "console"


class Settings(BaseSettings):
    # --- runtime ---
    app_env: str = "development"
    log_level: str = "INFO"
    log_json: bool = True

    # --- telegram ---
    bot_token: str = ""
    bot_username: str = ""
    use_webhook: bool = False
    webhook_base_url: str = ""
    webhook_path: str = "/telegram/webhook"
    webhook_secret: str = ""
    # Where the bot's own aiohttp server binds. This is the *internal* address the
    # reverse proxy forwards to; `webhook_base_url` is what Telegram is told.
    webhook_host: str = "0.0.0.0"
    webhook_port: int = 8081
    drop_pending_updates: bool = True

    # --- infrastructure ---
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5433/tg_manager"
    redis_url: str = "redis://localhost:6380/0"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_echo: bool = False

    # --- api ---
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_base_url: str = "http://localhost:8000"
    webapp_url: str = "http://localhost:5173"
    website_url: str = ""
    website_login_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    jwt_secret: str = PLACEHOLDER_JWT_SECRET
    jwt_ttl_seconds: int = 3600
    cors_origins: str = "*"
    init_data_ttl_seconds: int = 86_400  # spec: auth_date TTL <= 24h
    admin_cache_ttl_seconds: int = 300  # spec: getChatMember cached for 5 minutes

    # --- rate limits (Telegram API protection) ---
    global_send_rate: int = 30  # messages per second across all chats
    group_send_rate_per_minute: int = 20  # messages per minute per group
    sender_workers: int = 4

    # --- ai moderation ---
    ai_enabled: bool = True
    ai_base_url: str = "https://api.llm7.io/v1"
    ai_api_key: str = ""
    ai_model: str = "DeepSeek-V4-Flash-0731"
    ai_completion_path: str = "/chat/completions"
    ai_max_concurrency: int = Field(default=4, ge=1, le=64)
    ai_timeout_seconds: float = Field(default=8.0, gt=0.1, le=60.0)
    ai_cache_ttl_seconds: int = Field(default=86_400, ge=60, le=7 * 86_400)
    ai_circuit_failure_threshold: int = Field(default=5, ge=1, le=100)
    ai_circuit_reset_seconds: int = Field(default=60, ge=1, le=3_600)

    # --- payments ---
    cryptobot_token: str = ""
    # Which Crypto Pay network the token belongs to. One flag rather than a second
    # token variable: a token is issued for exactly one network (@CryptoBot for
    # live, @CryptoTestnetBot for test), so two of them side by side would only
    # create the mismatch where a live token is sent to the test host and every
    # invoice fails with an unauthorised error nobody can place.
    cryptobot_testnet: bool = False
    cryptobot_webhook_path: str = "/payments/cryptobot/webhook"
    payment_grace_days: int = 3
    payment_reminder_days: int = 3

    # --- platform operators ---
    superadmin_ids: str = ""
    # The command that hands the creator a button into the Mini App. Kept in
    # configuration and out of `setMyCommands` so the panel has no discoverable
    # entrance: everyone else sees a menu of moderation commands, and this one
    # only answers the ids in `superadmin_ids`. Renaming it is not a security
    # boundary — the id check is — but an unlisted name keeps curious members
    # from finding a door to rattle. Stored without the leading slash.
    panel_command: str = DEFAULT_PANEL_COMMAND
    global_ban_chat_threshold: int = 3

    # --- module defaults ---
    stats_retention_days: int = 30
    stats_flush_batch: int = 500

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @property
    def superadmin_id_list(self) -> tuple[int, ...]:
        raw = (self.superadmin_ids or "").replace(";", ",")
        return tuple(int(part) for part in raw.split(",") if part.strip().lstrip("-").isdigit())

    @property
    def panel_command_name(self) -> str:
        """`PANEL_COMMAND` as aiogram's `Command` filter needs it.

        Normalised rather than trusted: the natural thing to put in `.env` is
        `/console`, and a leading slash there would make the filter look for
        `//console` and never fire — a silent failure whose only symptom is the
        creator's command doing nothing. Telegram itself allows only
        `[a-z0-9_]{1,32}`, so anything outside that could never be typed as a
        command anyway and falls back to the default.
        """
        candidate = (self.panel_command or "").strip().lstrip("/").lower()
        if candidate and len(candidate) <= 32 and re.fullmatch(r"[a-z0-9_]+", candidate):
            return candidate
        return DEFAULT_PANEL_COMMAND

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def ai_moderation_available(self) -> bool:
        """Whether the configured provider has enough information to be called.

        API keys are deliberately not part of this check: keyless public and
        self-hosted OpenAI-compatible endpoints are valid providers. A provider
        that still requires authentication will fail open in ``core.ai_provider``.
        """
        endpoint = urlsplit(self.ai_base_url.strip())
        return bool(
            self.ai_enabled
            and endpoint.scheme in {"http", "https"}
            and endpoint.netloc
            and self.ai_model.strip()
        )

    @property
    def webhook_url(self) -> str:
        return f"{self.webhook_base_url.rstrip('/')}{self.webhook_path}"

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}

    @model_validator(mode="after")
    def _refuse_unsafe_production_config(self) -> "Settings":
        """Fail at startup rather than run production on the shipped defaults.

        DECISION: only checked when `APP_ENV` says production. Development and the
        test suite keep the placeholder so `task api` and `pytest` work with no
        setup, while the one configuration that actually faces Telegram cannot
        sign sessions with a secret that is printed in this file.
        """
        if not self.is_production:
            return self

        problems: list[str] = []
        if self.jwt_secret == PLACEHOLDER_JWT_SECRET:
            problems.append("JWT_SECRET is still the placeholder")
        elif len(self.jwt_secret.encode()) < MIN_JWT_SECRET_BYTES:
            problems.append(f"JWT_SECRET must be at least {MIN_JWT_SECRET_BYTES} bytes")
        if not self.bot_token:
            problems.append("BOT_TOKEN is empty")
        if "*" in self.cors_origin_list:
            problems.append("CORS_ORIGINS must name the panel's origin, not '*'")
        if self.use_webhook and not self.webhook_secret:
            # Without it, anyone who learns the URL can post fabricated updates.
            problems.append("WEBHOOK_SECRET is required when USE_WEBHOOK is on")
        if self.use_webhook and not self.webhook_base_url.startswith("https://"):
            # Telegram only delivers to HTTPS, and an empty base URL would make
            # `setWebhook` fail at startup with a much less obvious message.
            problems.append("WEBHOOK_BASE_URL must be an https:// URL when USE_WEBHOOK is on")
        if self.cryptobot_testnet:
            # Test-host invoices settle in play money, and `core.billing` cannot
            # tell them apart: a paid webhook extends the plan either way. Left
            # on in production it gives away every paid tier for free.
            problems.append("CRYPTOBOT_TESTNET must be off in production")

        if problems:
            raise ValueError("Unsafe production configuration: " + "; ".join(problems))
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def sync_database_url(url: str | None = None) -> str:
    """Return a psycopg-style URL for tooling that cannot use asyncpg."""
    target = url or get_settings().database_url
    return target.replace("+asyncpg", "")


__all__ = [
    "MIN_JWT_SECRET_BYTES",
    "PLACEHOLDER_JWT_SECRET",
    "Settings",
    "get_settings",
    "sync_database_url",
]
