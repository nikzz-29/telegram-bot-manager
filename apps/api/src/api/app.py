"""API process entrypoint: `uvicorn api.app:app`.

Assembled here and nowhere else — logging, cache, the Bot the admin check needs,
CORS, the exception handlers and the routers.

DECISION: the API constructs its own `Bot`. `AdminService` needs `getChatMember`
and the API is the one process that must never take an admin's word for their own
rights. The Bot is used for read-only membership queries only; everything the API
*sends* goes through the worker, so the two processes cannot fight over the same
send budget.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.errors import register_exception_handlers, use_problem_media_type
from api.middleware import RequestContextMiddleware
from api.routers import (
    account,
    auth,
    billing,
    chats,
    modules,
    platform,
    posts,
    reputation,
    stats,
    system,
    triggers,
)
from core.admins import admins
from core.billing import billing as billing_service
from core.cache import close_cache, setup_cache
from core.cryptobot import cryptobot
from core.redis_client import close_redis
from db.base import dispose_engine
from shared.config import get_settings
from shared.logging import configure_logging, get_logger

logger = get_logger(__name__)

API_PREFIX = "/api"

DESCRIPTION = """
REST API behind the Telegram Mini App admin panel.

Authenticate by posting the WebApp `initData` string to `/api/auth/telegram`,
then send the returned token as `Authorization: Bearer <token>` on every other
request. Tokens are short-lived; renew them with `/api/auth/refresh` rather than
re-posting `initData`, which Telegram only lets you use once.
""".strip()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.log_json)
    setup_cache()

    bot: Bot | None = None
    if settings.bot_token:
        bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        admins.bind(bot)
        # Stars invoice links are minted by the Bot API, so the panel's "buy"
        # button needs the same Bot the admin check already required.
        billing_service.bind(bot)
    else:
        # Not fatal: `/health`, `/meta` and the OpenAPI schema still serve, which
        # is what CI and the front-end build need. Any chat route will fail loudly.
        logger.warning("api.no_bot_token")

    logger.info("api.started", environment=settings.app_env, cors=settings.cors_origin_list)
    try:
        yield
    finally:
        if bot is not None:
            await bot.session.close()
        await cryptobot.close()
        await close_cache()
        await close_redis()
        await dispose_engine()
        logger.info("api.stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Telegram Bot Manager API",
        version="0.1.0",
        description=DESCRIPTION,
        lifespan=lifespan,
        # Served under the same prefix as the routes so the generated TS client
        # needs no base-path fixups.
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Accept-Language"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)

    app.include_router(system.router, prefix=API_PREFIX)
    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(account.router, prefix=API_PREFIX)
    app.include_router(chats.router, prefix=API_PREFIX)
    app.include_router(modules.router, prefix=API_PREFIX)
    app.include_router(triggers.router, prefix=API_PREFIX)
    app.include_router(posts.router, prefix=API_PREFIX)
    app.include_router(stats.router, prefix=API_PREFIX)
    app.include_router(reputation.router, prefix=API_PREFIX)
    app.include_router(billing.router, prefix=API_PREFIX)
    app.include_router(platform.router, prefix=API_PREFIX)

    # Not under `API_PREFIX` and not in the schema: Crypto Pay is configured with
    # this URL directly, and it authenticates by body signature, not by token.
    app.include_router(billing.webhook_router)

    # The container probe and the old smoke test both call bare `/health`.
    app.include_router(system.router, include_in_schema=False)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {"service": "tg-bot-manager-api", "docs": "/docs", "openapi": app.openapi_url or ""}

    use_problem_media_type(app)
    return app


app = create_app()

__all__ = ["API_PREFIX", "app", "create_app", "lifespan"]
