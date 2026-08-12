"""What an administrator sees when they ask the bot about their own chats.

The group `/stats` report answers "how is this chat doing" to the whole room.
This module answers a different question in a private chat: across every chat
this person administers, what has happened, and how much of it did they do.

DECISION: activity analytics sit behind `Feature.STATS` (Pro) but the moderation
counters do not. Message volume, the top-members board and growth are the
product being sold; how many warnings someone issued is a record of their own
work, and putting that behind a paywall would mean a free chat cannot see what
its own moderators did.

DECISION: a counter this module cannot compute yet is `None`, not `0`. The
difference matters to the reader — zero warnings is a fact about the chat, and a
missing number is a fact about the software — so an unavailable counter is left
off the screen rather than rendered as a confident zero.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape
from typing import Final

from core.features import features
from core.reports import TOP_LIMIT, sparkline
from core.stats import stats
from db.uow import UnitOfWork
from i18n.runtime import Translator
from shared.plans import Feature
from shared.schemas.api import StatsOverview
from shared.time_utils import utc_now


@dataclass(frozen=True, slots=True)
class StatsPeriod:
    """One of the windows the private-chat report offers."""

    slug: str
    days: int
    label_key: str

    def label(self, t: Translator) -> str:
        return t(self.label_key)


# Slugs travel in callback data (64 bytes for the whole payload), so they are
# short. The four windows answer four different questions: what happened today,
# what the week looked like, whether the month is trending, and whether the chat
# is growing at all.
PERIODS: Final[tuple[StatsPeriod, ...]] = (
    StatsPeriod("1d", 1, "report-period-1d"),
    StatsPeriod("7d", 7, "report-period-7d"),
    StatsPeriod("30d", 30, "report-period-30d"),
    StatsPeriod("90d", 90, "report-period-90d"),
)

# A week: long enough to have a shape, short enough that today still moves it.
DEFAULT_PERIOD: Final = PERIODS[1]

_BY_SLUG: Final[dict[str, StatsPeriod]] = {period.slug: period for period in PERIODS}


def period_for(slug: str) -> StatsPeriod | None:
    """Resolve a window by slug. `None` for anything else — this comes from input."""
    return _BY_SLUG.get(slug)


@dataclass(frozen=True, slots=True)
class ModerationCounters:
    """How much moderation happened in the window, and how much of it was yours.

    Everything but `actions` is optional: see the module docstring on why an
    uncomputed counter stays `None` instead of collapsing to zero.
    """

    actions: int
    warns: int | None = None
    punishments: int | None = None
    mine: int | None = None


class DmStatsService:
    """Assembles the private-chat report. One method per screen."""

    # --- reads ----------------------------------------------------------------
    async def counters(
        self,
        *,
        chat_id: int,
        period: StatsPeriod,
        viewer_tg_id: int,
        now: datetime | None = None,
    ) -> ModerationCounters:
        """Moderation totals for one chat over one window."""
        since = (now or utc_now()) - timedelta(days=period.days)
        async with UnitOfWork() as uow:
            actions = await uow.moderation_logs.count_since(chat_id, since)
        return ModerationCounters(actions=actions)

    # --- rendering ------------------------------------------------------------
    async def chat_report(
        self,
        *,
        chat_id: int,
        title: str,
        period: StatsPeriod,
        viewer_tg_id: int,
        t: Translator,
    ) -> str:
        """The report for one chat, as the message body the DM shows."""
        lines = [t("report-chat-title", chat=escape(title), period=period.label(t)), ""]

        if await features.has(chat_id, Feature.STATS):
            overview = await stats.overview(chat_id, days=period.days)
            lines.extend(_activity_lines(overview, t))
        else:
            lines.extend((t("report-locked-title"), t("report-locked-hint")))
        lines.append("")

        counters = await self.counters(chat_id=chat_id, period=period, viewer_tg_id=viewer_tg_id)
        lines.extend(_counter_lines(counters, t))
        return "\n".join(lines)

    async def overall_report(
        self,
        *,
        chats: Sequence[tuple[int, str]],
        period: StatsPeriod,
        viewer_tg_id: int,
        t: Translator,
    ) -> str:
        """One line per chat plus the totals, for someone who runs several.

        `chats` is `(chat.id, title)` — the caller has already loaded and
        authorised them, and re-reading the rows here would only risk showing a
        chat the caller decided not to.
        """
        header = [
            t("report-overall-title", period=period.label(t)),
            t("report-overall-chats", count=len(chats)),
        ]
        if not chats:
            return "\n".join((*header, "", t("report-overall-none")))

        rows: list[str] = []
        total_messages = 0
        total_actions = 0
        for chat_id, title in chats:
            counters = await self.counters(
                chat_id=chat_id, period=period, viewer_tg_id=viewer_tg_id
            )
            messages = 0
            if await features.has(chat_id, Feature.STATS):
                messages = (await stats.overview(chat_id, days=period.days)).total_messages
            total_messages += messages
            total_actions += counters.actions
            rows.append(
                t(
                    "report-overall-row",
                    chat=escape(title),
                    messages=messages,
                    actions=counters.actions,
                )
            )

        return "\n".join(
            (
                *header,
                "",
                t("report-messages", count=total_messages),
                t("report-moderation-title"),
                f"└ {t('report-moderation-actions', count=total_actions)}",
                "",
                *rows,
            )
        )


def _activity_lines(overview: StatsOverview, t: Translator) -> list[str]:
    """The Pro block: volume, reach, growth, the sparkline and the top board."""
    lines = [
        t("report-messages", count=overview.total_messages),
        t("report-active", count=overview.total_active_users),
        t(
            "report-flow",
            joins=overview.total_joins,
            leaves=overview.total_leaves,
            growth=overview.net_growth,
        ),
    ]
    chart = sparkline([point.messages for point in overview.series])
    if chart:
        lines.append(t("report-chart", chart=chart))
    if not overview.series:
        lines.append(t("report-empty"))
        return lines

    if overview.top_users:
        lines.extend(("", t("report-top-title")))
        for place, entry in enumerate(overview.top_users[:TOP_LIMIT], start=1):
            name = entry.display_name or (f"@{entry.username}" if entry.username else "")
            lines.append(
                t(
                    "report-top-row",
                    place=place,
                    user=escape(name or str(entry.tg_user_id)),
                    messages=entry.messages,
                )
            )
    return lines


def _counter_lines(counters: ModerationCounters, t: Translator) -> list[str]:
    """The moderation block, with the tree drawn around whatever is present."""
    values: list[str] = [t("report-moderation-actions", count=counters.actions)]
    if counters.warns is not None:
        values.append(t("report-moderation-warns", count=counters.warns))
    if counters.punishments is not None:
        values.append(t("report-moderation-punishments", count=counters.punishments))
    if counters.mine is not None:
        values.append(t("report-moderation-mine", count=counters.mine))

    lines = [t("report-moderation-title")]
    for index, value in enumerate(values):
        branch = "└" if index == len(values) - 1 else "├"
        lines.append(f"{branch} {value}")
    return lines


dm_stats = DmStatsService()


__all__ = [
    "DEFAULT_PERIOD",
    "PERIODS",
    "DmStatsService",
    "ModerationCounters",
    "StatsPeriod",
    "dm_stats",
    "period_for",
]
