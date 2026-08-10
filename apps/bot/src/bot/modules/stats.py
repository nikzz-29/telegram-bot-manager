"""The statistics module: counting what happens, and reporting it.

Spec §5.5 — message counters, activity over time, a top-10 board and an
optional daily digest. This module owns the *write* side for messages and the
`/stats` read; the rollups and the digest itself belong to the worker.

DECISION: the message counter is a passive handler that re-raises `SkipHandler`
rather than a middleware. A middleware would run for every chat on the platform
and then have to ask whether statistics are on; a handler inside this module's
router is already behind `ModuleGateMiddleware`, so a chat with statistics off
never pays for the check at all. `SkipHandler` is what keeps it passive — the
message continues to the engagement module and to every other router exactly as
if this one had not matched.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Final

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.facts import facts_from
from bot.filters import IsChatAdmin
from bot.replies import answer
from core.context import ChatContext, chat_context
from core.reports import format_overview
from core.stats import DEFAULT_PERIOD_DAYS, MAX_PERIOD_DAYS, stats
from i18n.runtime import translator
from shared.enums import ModuleName, StatEventType
from shared.logging import get_logger
from shared.schemas.module_configs import StatsConfig

logger = get_logger(__name__)

# How long a `/stats` answer stays before removing itself. Long enough to read a
# week of numbers, short enough that a busy chat is not paved with old reports.
REPORT_TTL: Final = timedelta(minutes=5)

_is_admin = IsChatAdmin()


def _requested_days(command: CommandObject) -> int:
    """`/stats 30` — the window, clamped to what the reports can serve."""
    argument = (command.args or "").strip()
    if not argument.isdigit():
        return DEFAULT_PERIOD_DAYS
    return max(1, min(int(argument), MAX_PERIOD_DAYS))


def build_router() -> Router:
    """The statistics router. Gated by `ModuleGateMiddleware` in `bot.modules`."""
    router = Router(name="stats")

    @router.message(Command("stats"), _is_admin)
    async def stats_command(message: Message, command: CommandObject, ctx: ChatContext) -> None:
        days = _requested_days(command)
        retention = ctx.limits.stats_retention_days
        if retention:
            days = min(days, retention)

        overview = await stats.overview(ctx.chat_id, days=days)
        await answer(
            message,
            format_overview(overview, title=ctx.title, t=translator(ctx.language)),
            ttl=REPORT_TTL,
        )

    @router.message(F.chat.type.in_({"group", "supergroup"}))
    async def count_message(message: Message, ctx: ChatContext, **_: Any) -> None:
        """Buffer one MESSAGE event, then step aside.

        Raises `SkipHandler` unconditionally: this handler exists for its side
        effect, and swallowing the update here would stop `/rep`, the triggers
        and every later router from ever seeing a message.
        """
        author = message.from_user
        if author is None or author.is_bot:
            raise SkipHandler

        facts = facts_from(message)
        if facts.is_service:
            # Joins and pins are counted from `chat_member`, not from the
            # service message Telegram may or may not send for them.
            raise SkipHandler

        config = await chat_context.config(ctx, ModuleName.STATS, StatsConfig)
        if config.track_messages:
            await stats.record(
                ctx.chat_id,
                StatEventType.MESSAGE,
                tg_user_id=author.id,
                payload={"kind": facts.content_kind},
            )
        raise SkipHandler

    return router


__all__ = ["REPORT_TTL", "build_router"]
