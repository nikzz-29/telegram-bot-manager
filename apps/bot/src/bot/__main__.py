"""Bot process entrypoint: `python -m bot`.

The whole process is assembled here and nowhere else — logging, cache, the
dispatcher's middleware chain, the module routers, and the outbound sender. Each
of those knows how to configure itself; this file only decides the order.

DECISION: how updates arrive is `bot.runner`'s problem, not this file's. Polling
and webhook differ only in that one call, and keeping the choice there means the
assembly and the teardown below are identical either way.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Final
from urllib.parse import urlparse

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllPrivateChats,
    MenuButtonCommands,
    MenuButtonWebApp,
    WebAppInfo,
)

from bot import lifecycle, middlewares, modules
from bot.commands import payments, private
from bot.runner import run_updates
from core.admins import admins
from core.billing import billing
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

# The DM command menu, in the order it is shown. These are the platform's own
# commands rather than any module's, so they are written here instead of derived
# from the registry — `bot.commands.private` is the only file that answers them.
#
# DECISION: the operator console is deliberately absent from this list. Its
# command name comes from `PANEL_COMMAND` and only the ids in `SUPERADMIN_IDS`
# may use it, so publishing it here would put a door in every user's menu that
# answers nothing for all but a handful of accounts. `bot.commands.private`
# answers it with silence for everyone else, and leaving it out of
# `setMyCommands` is the other half of keeping it unadvertised — the name is the
# one thing a curious member does not already have.
PRIVATE_COMMANDS: Final[tuple[tuple[str, str], ...]] = (
    ("profile", "cmd-profile"),
    ("chats", "cmd-chats"),
    ("plans", "cmd-plans"),
    ("help", "cmd-help"),
)


def build_dispatcher() -> Dispatcher:
    """The dispatcher, with the spec's middleware chain and every module router."""
    dispatcher = Dispatcher()
    middlewares.setup(dispatcher)
    # Lifecycle is ungated: an inactive chat must receive the promotion or
    # re-add update that makes it active again.
    dispatcher.include_router(lifecycle.build_router())
    modules.setup(dispatcher)
    # Private-chat commands sit outside the module system: `/start` has to answer
    # before the user has any chat, let alone a plan.
    dispatcher.include_router(private.build_router())
    # Checkout updates carry no chat context either — the payload is the context —
    # and they arrive in whatever chat the invoice was opened from.
    dispatcher.include_router(payments.build_router())
    return dispatcher


async def _publish_commands(bot: Bot) -> None:
    """Register both command menus. Best-effort.

    DECISION: the group list is derived from `ModuleSpec.commands` rather than
    written out here. The registry is already the single source of truth for what
    a module offers, and the menu is one more consumer of it. The private list is
    not — those commands belong to no module, and `PRIVATE_COMMANDS` is where
    they are written down.

    DECISION: only admin-scoped commands are published to groups. `/warns` is
    open to everyone but putting it in the all-members menu invites a whole chat
    to poke at the bot; anyone who knows to type it still gets an answer.

    DECISION: the chat menu button opens the Mini App for every user. The API
    still derives permissions from signed Telegram init data, so exposing the
    entrance does not expose another user's chats. Telegram only accepts HTTPS
    Web App URLs; local development therefore falls back to the command menu.
    """
    # The menu is global, so it can only be in one language; the per-chat
    # `language` setting still governs every reply the bot actually sends.
    t = translator(DEFAULT_LOCALE)
    group_commands = [
        BotCommand(command=command.name, description=t(command.description_key))
        for module in LIVE_MODULES
        for command in registry.get(module).commands
        if command.admin_only
    ]
    private_commands = [
        BotCommand(command=name, description=t(description_key))
        for name, description_key in PRIVATE_COMMANDS
    ]

    try:
        await bot.set_my_commands(group_commands, scope=BotCommandScopeAllChatAdministrators())
    except TelegramAPIError as exc:
        logger.warning("bot.commands_publish_failed", operation="group", error=str(exc))

    try:
        await bot.set_my_commands(private_commands, scope=BotCommandScopeAllPrivateChats())
    except TelegramAPIError as exc:
        logger.warning("bot.commands_publish_failed", operation="private", error=str(exc))

    url = get_settings().webapp_url.strip()
    parsed = urlparse(url)
    menu_button = (
        MenuButtonWebApp(text=t("open-miniapp"), web_app=WebAppInfo(url=url))
        if parsed.scheme == "https" and bool(parsed.netloc)
        else MenuButtonCommands()
    )
    if isinstance(menu_button, MenuButtonCommands):
        logger.warning("bot.webapp_menu_fallback", webapp_url=url or None)
    try:
        await bot.set_chat_menu_button(menu_button=menu_button)
    except TelegramAPIError as exc:
        logger.warning("bot.commands_publish_failed", operation="menu_button", error=str(exc))


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
    billing.bind(bot)
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
    allowed_updates = sorted(
        {*dispatcher.resolve_used_update_types(), "edited_message", "my_chat_member"}
    )
    try:
        await run_updates(bot, dispatcher, allowed_updates=allowed_updates)
    finally:
        # Drain: a moderation action already decided must still reach Telegram.
        # This is why the runner handles SIGTERM instead of letting the default
        # disposition kill the process — a hard kill never reaches this block.
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
