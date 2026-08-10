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
from core.stats import DEFAULT_PERIOD_DAYS, MAX_PERIOD_DAYS, stats
from i18n.runtime import Translator, translator
from shared.enums import ModuleName, StatEventType
from shared.logging import get_logger
from shared.schemas.api import StatsOverview
from shared.schemas.module_configs import StatsConfig

logger = get_logger(__name__)

# How long a `/stats` answer stays before removing itself. Long enough to read a
# week of numbers, short enough that a busy chat is not paved with old reports.
REPORT_TTL: Final = timedelta(minutes=5)

# Bars for the activity sparkline, lightest to heaviest.
_BLOCKS: Final = "▁▂▃▄▅▆▇█"

# Sparkline width: one column per day of the default window, and never so wide
# that a phone wraps the line.
MAX_COLUMNS: Final = 14

_is_admin = IsChatAdmin()


def sparkline(values: list[int]) -> str:
    """A one-line activity chart, no image and no dependency.

    DECISION: a text sparkline rather than a rendered PNG. It costs nothing to
    produce, survives being forwarded, and the Mini App is where the real chart
    lives — this is the glanceable version.
    """
    if not values:
        return ""
    trimmed = values[-MAX_COLUMNS:]
    peak = max(trimmed)
    if peak <= 0:
        return _BLOCKS[0] * len(trimmed)
    span = len(_BLOCKS) - 1
    return "".join(_BLOCKS[round(value / peak * span)] for value in trimmed)


def _format_top(overview: StatsOverview, t: Translator) -> list[str]:
    if not overview.top_users:
        return []
    lines = [t("stats-top-title")]
    for place, entry in enumerate(overview.top_users[:10], start=1):
        name = entry.display_name or (f"@{entry.username}" if entry.username else "")
        lines.append(
            t(
                "stats-top-row",
                place=place,
                user=name or str(entry.tg_user_id),
                messages=entry.messages,
            )
        )
    return lines


def format_overview(overview: StatsOverview, *, title: str, t: Translator) -> str:
    """Render an overview as the chat-facing report."""
    lines = [
        t("stats-title", chat=title, days=overview.period_days),
        t("stats-messages", count=overview.total_messages),
        t("stats-active", count=overview.total_active_users),
        t("stats-joins", count=overview.total_joins),
        t("stats-leaves", count=overview.total_leaves),
        t("stats-growth", count=overview.net_growth),
    ]
    chart = sparkline([point.messages for point in overview.series])
    if chart:
        lines.append(t("stats-chart", chart=chart))
    lines.extend(_format_top(overview, t))
    if not overview.series:
        lines.append(t("stats-empty"))
    return "\n".join(lines)


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
    async def stats_command(
        message: Message, command: CommandObject, ctx: ChatContext
    ) -> None:
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


__all__ = ["MAX_COLUMNS", "REPORT_TTL", "build_router", "format_overview", "sparkline"]
