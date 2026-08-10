"""Application settings loaded from the environment (pydantic-settings)."""

from functools import lru_cache
from typing import Final

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# RFC 7518 §3.2: an HMAC-SHA256 key should be at least as long as the digest.
MIN_JWT_SECRET_BYTES: Final = 32
# Long enough to satisfy the RFC and pyjwt's key-length warning, so development
# runs quiet; the production validator below still rejects it by exact match.
PLACEHOLDER_JWT_SECRET: Final = "change-me-in-production-this-is-not-a-secret"


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
    ai_base_url: str = "https://api.openai.com/v1"
    ai_api_key: str = ""
    ai_model: str = "gpt-4o-mini"
    ai_timeout_seconds: float = 8.0
    ai_cache_ttl_seconds: int = 86_400
    ai_circuit_failure_threshold: int = 5
    ai_circuit_reset_seconds: int = 60

    # --- payments ---
    cryptobot_token: str = ""
    cryptobot_webhook_path: str = "/payments/cryptobot/webhook"
    payment_grace_days: int = 3
    payment_reminder_days: int = 3

    # --- platform operators ---
    superadmin_ids: str = ""
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
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

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
