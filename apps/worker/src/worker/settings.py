"""ARQ worker process — everything time-shifted runs here.

DECISION: the worker owns its own `Bot` instance rather than borrowing one from
the bot process. An unmute firing at 03:00 must not depend on a polling loop
being alive, and the worker has to be independently scalable: if the bot process
is redeploying, expiries still land.

DECISION: the job lists live in `worker.registry` and jobs append themselves with
a decorator. `WorkerSettings` then never imports the job modules it configures —
which is what keeps the import graph acyclic — and registering a job is one line
next to the job itself.
"""

from __future__ import annotations

from typing import Any, Final

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from arq.connections import RedisSettings

from core.cache import close_cache, setup_cache
from core.jobs import QUEUE_NAME, redis_settings, set_arq
from core.plan_settings import load_plan_overrides
from core.platform_settings import load_platform_settings
from core.redis_client import close_redis
from core.sender import sender
from db.base import dispose_engine
from shared.config import get_settings
from shared.logging import configure_logging, get_logger

# Importing the job package is what populates the registry lists below.
import worker.jobs  # noqa: F401  (side-effect import: job registration)
from worker.registry import CRON_JOBS, FUNCTIONS, job

logger = get_logger(__name__)

WorkerContext = dict[Any, Any]


@job
async def health_job(ctx: WorkerContext) -> str:
    """Liveness probe target: proves the worker can pick a job off the queue."""
    return "ok"


async def startup(ctx: WorkerContext) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.log_json)
    setup_cache()
    await load_platform_settings()
    await load_plan_overrides()
    # ARQ hands the worker its own pool; reuse it so a job enqueueing a
    # follow-up job does not open a second one.
    set_arq(ctx["redis"])

    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is required: the worker sends messages of its own.")
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    ctx["bot"] = bot
    await sender.start(bot)
    logger.info("worker.started", queue=QUEUE_NAME)


async def shutdown(ctx: WorkerContext) -> None:
    # Drain first: a job that queued a notification must not lose it on deploy.
    await sender.stop(drain=True)
    bot: Bot | None = ctx.get("bot")
    if bot is not None:
        await bot.session.close()
    await close_cache()
    await close_redis()
    await dispose_engine()
    logger.info("worker.stopped")


class WorkerSettings:
    """ARQ entrypoint: `arq worker.settings.WorkerSettings`."""

    functions: Final = FUNCTIONS
    cron_jobs: Final = CRON_JOBS
    on_startup = startup
    on_shutdown = shutdown
    redis_settings: Final[RedisSettings] = redis_settings()
    queue_name: Final = QUEUE_NAME
    max_jobs: Final = 20
    job_timeout: Final = 120
    keep_result: Final = 3600
    # DECISION: 3 tries. Job failures here are overwhelmingly transient (a 5xx
    # from Telegram, a connection reset), and every job is idempotent, so a
    # retry is cheap while a permanent failure still stops after three.
    max_tries: Final = 3


__all__ = ["WorkerSettings", "health_job"]
