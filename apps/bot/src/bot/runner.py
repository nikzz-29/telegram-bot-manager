"""How the bot receives updates: long polling in development, webhook in prod.

Spec §32. Both runners return when the process is asked to stop, which is what
lets `__main__` drain the outbound queue in a `finally` — a mute that has already
been decided must still reach Telegram even though the deploy is halfway done.

DECISION: the webhook is not deleted on shutdown. Telegram queues updates while
an endpoint is unreachable and redelivers them, so leaving it registered means a
restart loses nothing; deleting it would open a window on every deploy and, if
the process then crash-looped, would leave the bot silently unreachable.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal

from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from shared.config import get_settings
from shared.logging import get_logger

logger = get_logger(__name__)


async def _until_signalled() -> None:
    """Block until the supervisor asks the process to stop.

    DECISION: SIGTERM is handled explicitly. It is what `docker stop`, compose and
    every orchestrator send first, and its default disposition kills the process
    outright — no exception, no `finally`, and therefore no drain. Handling it
    turns a hard kill into an ordinary return from the runner.
    """
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        # Not implemented on Windows; there the process falls back to the
        # KeyboardInterrupt path in `main()`.
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    await stop.wait()


async def run_polling(bot: Bot, dispatcher: Dispatcher, *, allowed_updates: list[str]) -> None:
    """Long polling: no public endpoint, no TLS, no reverse proxy."""
    settings = get_settings()
    # `getUpdates` is refused with 409 while a webhook is registered, so flipping
    # USE_WEBHOOK back to false has to clear the one production left behind.
    await bot.delete_webhook(drop_pending_updates=settings.drop_pending_updates)
    logger.info("bot.polling_started")
    # `close_bot_session=False`: the session stays open for the drain that
    # `__main__` runs after this returns. aiogram would otherwise close it here
    # and the drain would silently open a second one.
    await dispatcher.start_polling(
        bot,
        close_bot_session=False,
        drop_pending_updates=settings.drop_pending_updates,
        allowed_updates=allowed_updates,
    )


async def run_webhook(bot: Bot, dispatcher: Dispatcher, *, allowed_updates: list[str]) -> None:
    """Webhook: Telegram pushes to `WEBHOOK_BASE_URL + WEBHOOK_PATH`.

    The secret token is sent by Telegram in `X-Telegram-Bot-Api-Secret-Token` and
    compared here; without it anyone who learns the URL can post fabricated
    updates, which is why production refuses to start when it is unset.
    """
    settings = get_settings()
    secret = settings.webhook_secret or None
    await bot.set_webhook(
        settings.webhook_url,
        secret_token=secret,
        allowed_updates=allowed_updates,
        drop_pending_updates=settings.drop_pending_updates,
    )

    app = web.Application()
    handler = SimpleRequestHandler(dispatcher=dispatcher, bot=bot, secret_token=secret)
    # DECISION: the route is added directly instead of through `handler.register`,
    # which also appends a shutdown hook that closes the bot session. That is the
    # same hazard as polling's `close_bot_session` — `__main__` drains the
    # outbound queue after this returns, and the drain must not have to reopen the
    # session it is sending on.
    app.router.add_route("POST", settings.webhook_path, handler.handle)
    setup_application(app, dispatcher, bot=bot)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=settings.webhook_host, port=settings.webhook_port)
    await site.start()
    logger.info("bot.webhook_started", url=settings.webhook_url, port=settings.webhook_port)
    try:
        await _until_signalled()
    finally:
        # Stops accepting connections and lets in-flight handlers finish.
        await runner.cleanup()


async def run_updates(bot: Bot, dispatcher: Dispatcher, *, allowed_updates: list[str]) -> None:
    """Dispatch to whichever runner the environment asked for."""
    runner = run_webhook if get_settings().use_webhook else run_polling
    await runner(bot, dispatcher, allowed_updates=allowed_updates)


__all__ = ["run_polling", "run_updates", "run_webhook"]
