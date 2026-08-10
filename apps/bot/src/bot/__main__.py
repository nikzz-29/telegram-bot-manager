"""Bot process entrypoint: `python -m bot`.

The whole process is assembled here and nowhere else — logging, cache, the
dispatcher's middleware chain, the module routers, and the outbound sender. Each
of those knows how to configure itself; this file only decides the order.

DECISION: long polling, not a webhook. A webhook needs a public TLS endpoint and
a reverse proxy in front of it, which is deployment complexity the project does
not need until it has the traffic to justify it. `start_polling` is swapped for
`start_webhook` in one place when that day comes.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Final

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllChatAdministrators,
    MenuButtonWebApp,
    WebAppInfo,
)

from bot import middlewares, modules
from bot.commands import private
from core.admins import admins
from core.cache import close_cache, setup_cache
from core.jobs import close_arq
from core.redis_client import close_redis
from core.registry import registry
from core.sender import sender
from core.subscription import subscription
from db.base import dispose_engine
from i18n.runtime import DEFAULT_LOCALE, translator
from shared.config import get_settings
from shared.enums import ModuleName
from shared.logging import configure_logging, get_logger

logger = get_logger(__name__)

# Modules whose routers this stage attaches. Advertising a command in the menu
# before its router exists would be a command that silently does nothing.
LIVE_MODULES: Final[tuple[ModuleName, ...]] = (
    ModuleName.MODERATION,
    ModuleName.ENTRY,
    ModuleName.STATS,
    ModuleName.ENGAGEMENT,
    ModuleName.AUTOPOST,
)


def build_dispatcher() -> Dispatcher:
    """The dispatcher, with the spec's middleware chain and every module router."""
    dispatcher = Dispatcher()
    middlewares.setup(dispatcher)
    modules.setup(dispatcher)
    # Private-chat commands sit outside the module system: `/start` has to answer
    # before the user has any chat, let alone a plan.
    dispatcher.include_router(private.build_router())
    return dispatcher


async def _publish_commands(bot: Bot) -> None:
    """Register the group command menu from the registry. Best-effort.

    DECISION: the command list is derived from `ModuleSpec.commands` rather than
    written out here. The registry is already the single source of truth for what
    a module offers, and the menu is one more consumer of it.

    DECISION: only admin-scoped commands are published. `/warns` is open to
    everyone but putting it in the all-members menu invites a whole chat to poke
    at the bot; anyone who knows to type it still gets an answer.
    """
    settings = get_settings()
    # The menu is global, so it can only be in one language; the per-chat
    # `language` setting still governs every reply the bot actually sends.
    t = translator(DEFAULT_LOCALE)
    commands = [
        BotCommand(command=command.name, description=t(command.description_key))
        for module in LIVE_MODULES
        for command in registry.get(module).commands
        if command.admin_only
    ]
    try:
        await bot.set_my_commands(commands, scope=BotCommandScopeAllChatAdministrators())
        if settings.webapp_url:
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text=t("menu-button"), web_app=WebAppInfo(url=settings.webapp_url)
                )
            )
    except TelegramAPIError as exc:
        logger.warning("bot.commands_publish_failed", error=str(exc))


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.log_json)
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is required to run the bot")

    setup_cache()
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    # `admins` needs a Bot for `getChatMember`; `subscription` needs it for the
    # same call against a channel; `sender` owns every outbound call.
    admins.bind(bot)
    subscription.bind(bot)
    await sender.start(bot)

    dispatcher = build_dispatcher()
    await _publish_commands(bot)

    me = await bot.me()
    logger.info("bot.started", username=me.username, bot_id=me.id)
    # DECISION: `allowed_updates` is stated explicitly rather than left to
    # `resolve_used_update_types()`, which derives the list from *handlers*.
    # The content filters and stop-words run as observer middleware on
    # `edited_message` and have no handler of their own, so the derived list
    # would omit that type and Telegram would never deliver it — turning
    # "post clean, then edit in the spam" into a free bypass.
    allowed_updates = sorted({*dispatcher.resolve_used_update_types(), "edited_message"})
    try:
        # Old updates are dropped: a mute the bot "missed" during a deploy has
        # long since stopped being the right response by the time it comes back.
        await dispatcher.start_polling(
            bot,
            handle_signals=False,
            drop_pending_updates=True,
            allowed_updates=allowed_updates,
        )
    finally:
        # Drain: a moderation action already decided must still reach Telegram.
        await sender.stop(drain=True)
        await bot.session.close()
        await close_cache()
        await close_arq()
        await close_redis()
        await dispose_engine()
        logger.info("bot.stopped")


def main() -> None:
    with contextlib.suppress(KeyboardInterrupt, asyncio.CancelledError):
        asyncio.run(run())


if __name__ == "__main__":
    main()
