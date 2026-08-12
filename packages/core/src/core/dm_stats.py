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

DECISION: the screen answers the questions an owner actually asks at the end of a
week, in this order. How much moderation was there (`actions`), what was it
(`breakdown`), how much of it did *I* do (`mine`), how much did the bot do
without anyone (`automated`), how many people were working (`moderators`), and is
it getting better or worse (`previous`). The automated split is the number that
changes how the rest is read: forty actions is a busy week for a team of three
and a quiet one if the bot handled thirty-eight of them by itself.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape
from typing import Final

from core.features import features
from core.reports import TOP_LIMIT, sparkline, top_user_label
from core.stats import stats
from db.uow import UnitOfWork
from i18n.runtime import Translator
from shared.enums import PunishmentType
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


# How many groups the breakdown prints before the tail is summed into one line.
# Five fits a phone screen without scrolling; the tail is never dropped, because a
# breakdown whose parts do not add up to the total reads as a broken report.
BREAKDOWN_LIMIT: Final = 5

# The action strings `core.moderation` writes, mapped to the noun the breakdown
# prints. The map is explicit rather than derived from the action name so that the
# copy stays reviewable, and two actions may share a label — `auto_unmute` and
# `auto_unban` are one thing to the reader, "restrictions the bot lifted on time".
#
# An action missing from here is summed into `report-action-other` instead of
# being discarded: a module added later must not silently shrink the total.
ACTION_LABELS: Final[dict[str, str]] = {
    "warn": "report-action-warn",
    "mute": "report-action-mute",
    "ban": "report-action-ban",
    "kick": "report-action-kick",
    "auto_delete": "report-action-delete",
    "alert_admins": "report-action-alert",
    "nothing": "report-action-flagged",
    "unwarn": "report-action-unwarn",
    "unmute": "report-action-unmute",
    "unban": "report-action-unban",
    "auto_unmute": "report-action-auto-lift",
    "auto_unban": "report-action-auto-lift",
}

OTHER_ACTION_LABEL: Final = "report-action-other"


@dataclass(frozen=True, slots=True)
class ModerationCounters:
    """How much moderation happened in the window, and how much of it was yours.

    Everything but `actions` is optional: see the module docstring on why an
    uncomputed counter stays `None` instead of collapsing to zero.

    `automated` counts what the bot did with no human behind it, `moderators` how
    many people were at work, `previous` the same total one window earlier, and
    `breakdown` is `(action, count)` largest first — raw action strings, because
    naming them is the renderer's job.
    """

    actions: int
    warns: int | None = None
    punishments: int | None = None
    mine: int | None = None
    automated: int | None = None
    moderators: int | None = None
    previous: int | None = None
    breakdown: tuple[tuple[str, int], ...] = ()


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
        detailed: bool = True,
    ) -> ModerationCounters:
        """Moderation totals for one chat over one window.

        `detailed=False` skips the reads only the single-chat screen prints. The
        digest calls this once per chat, so anything asked for here is multiplied
        by the number of chats a person administers.

        Warns come from `warns` and punishments from `punishments` rather than
        from the log: those tables are the record of the action, while a log row is
        its mirror into the audit channel.
        """
        moment = now or utc_now()
        window = timedelta(days=period.days)
        since = moment - window

        async with UnitOfWork() as uow:
            actions = await uow.moderation_logs.count_since(chat_id, since)
            mine = await uow.moderation_logs.count_for_moderator(chat_id, viewer_tg_id, since)
            warns = await uow.warns.count_issued(chat_id, since)
            by_type = await uow.punishments.count_issued_by_type(chat_id, since)
            if not detailed:
                return ModerationCounters(
                    actions=actions,
                    warns=warns,
                    punishments=_restrictions(by_type),
                    mine=mine,
                )
            split = await uow.moderation_logs.moderator_split(chat_id, since)
            previous = await uow.moderation_logs.count_since(chat_id, since - window, until=since)
            breakdown = await uow.moderation_logs.count_by_action(chat_id, since)

        return ModerationCounters(
            actions=actions,
            warns=warns,
            punishments=_restrictions(by_type),
            mine=mine,
            automated=split["automated"],
            moderators=split["moderators"],
            previous=previous,
            breakdown=tuple(breakdown),
        )

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
        lines.extend(_trend_lines(counters, t))
        breakdown = _breakdown_lines(counters, t)
        if breakdown:
            lines.extend(("", *breakdown))
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

        rows: list[tuple[int, int, str]] = []
        total_messages = 0
        totals = ModerationCounters(actions=0, warns=0, punishments=0, mine=0)
        for chat_id, title in chats:
            counters = await self.counters(
                chat_id=chat_id, period=period, viewer_tg_id=viewer_tg_id, detailed=False
            )
            messages = 0
            if await features.has(chat_id, Feature.STATS):
                messages = (await stats.overview(chat_id, days=period.days)).total_messages
            total_messages += messages
            totals = _add(totals, counters)
            rows.append(
                (
                    counters.actions,
                    messages,
                    t(
                        "report-overall-row",
                        chat=escape(title),
                        messages=messages,
                        actions=counters.actions,
                    ),
                )
            )

        # Busiest first: a digest of a dozen chats is read from the top, and the
        # one that needed the most moderation is the one worth reading about.
        rows.sort(key=lambda row: (-row[0], -row[1]))
        return "\n".join(
            (
                *header,
                "",
                t("report-messages", count=total_messages),
                *_counter_lines(totals, t),
                "",
                *(row for _, _, row in rows),
            )
        )


def _restrictions(by_type: dict[str, int]) -> int:
    """Mutes and bans issued. Kicks are counted, but not as a restriction.

    A kick removes nobody's right to speak — the person can walk straight back in
    — so folding it in here would inflate the one number an owner reads as "how
    often did we have to silence someone". It still shows up in the breakdown.
    """
    return by_type.get(PunishmentType.MUTE, 0) + by_type.get(PunishmentType.BAN, 0)


def _add(totals: ModerationCounters, counters: ModerationCounters) -> ModerationCounters:
    """Sum one chat's counters into the digest's running total.

    Only the additive ones. `moderators` is deliberately not summed: one person
    moderating three chats would be counted three times, and "9 moderators at
    work" for a team of three is a worse answer than no answer.
    """
    return ModerationCounters(
        actions=totals.actions + counters.actions,
        warns=(totals.warns or 0) + (counters.warns or 0),
        punishments=(totals.punishments or 0) + (counters.punishments or 0),
        mine=(totals.mine or 0) + (counters.mine or 0),
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

    peak = max(overview.series, key=lambda point: point.messages)
    if peak.messages:
        # ISO rather than a locale format: `08.11` and `11.08` are the same day to
        # two different readers, and this line exists to be quoted back at people.
        lines.append(t("report-peak", date=peak.date.isoformat(), count=peak.messages))

    load = [point.moderation_actions for point in overview.series]
    if any(load):
        # Rolled up from `StatEventType.MODERATION`, so this stays absent until
        # something records those events — an all-zero chart would claim a calm
        # week that nobody actually measured.
        lines.append(t("report-chart-moderation", chart=sparkline(load)))

    if overview.top_users:
        lines.extend(("", t("report-top-title")))
        for place, entry in enumerate(overview.top_users[:TOP_LIMIT], start=1):
            lines.append(
                t(
                    "report-top-row",
                    place=place,
                    user=top_user_label(entry),
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
    if counters.automated is not None:
        values.append(t("report-moderation-automated", count=counters.automated))
    if counters.moderators is not None:
        values.append(t("report-moderation-moderators", count=counters.moderators))

    lines = [t("report-moderation-title")]
    for index, value in enumerate(values):
        branch = "└" if index == len(values) - 1 else "├"
        lines.append(f"{branch} {value}")
    return lines


def _trend_lines(counters: ModerationCounters, t: Translator) -> list[str]:
    """Whether the load is rising or falling. Silent when there is nothing to say.

    Two empty windows in a row produce no line: "0, same as last time" is noise,
    and the tree above already said that nothing happened.
    """
    if counters.previous is None or (counters.previous == 0 and counters.actions == 0):
        return []
    delta = counters.actions - counters.previous
    # The sign is part of the meaning, so the delta is formatted here and passed as
    # text — a number would be grouped for the locale and lose its `+`.
    return [t("report-moderation-trend", previous=counters.previous, delta=f"{delta:+d}")]


def _breakdown_lines(counters: ModerationCounters, t: Translator) -> list[str]:
    """What the actions were, largest group first, tail summed into one row."""
    if not counters.breakdown:
        return []

    grouped: dict[str, int] = {}
    other = 0
    for action, count in counters.breakdown:
        label = ACTION_LABELS.get(action)
        if label is None:
            other += count
            continue
        grouped[label] = grouped.get(label, 0) + count

    ranked = sorted(grouped.items(), key=lambda item: (-item[1], item[0]))
    rest = other + sum(count for _, count in ranked[BREAKDOWN_LIMIT:])
    lines = [t("report-breakdown-title")]
    lines.extend(
        t("report-breakdown-row", label=t(label), count=count)
        for label, count in ranked[:BREAKDOWN_LIMIT]
    )
    if rest:
        lines.append(t("report-breakdown-row", label=t(OTHER_ACTION_LABEL), count=rest))
    return lines


dm_stats = DmStatsService()


__all__ = [
    "ACTION_LABELS",
    "BREAKDOWN_LIMIT",
    "DEFAULT_PERIOD",
    "PERIODS",
    "DmStatsService",
    "ModerationCounters",
    "StatsPeriod",
    "dm_stats",
    "period_for",
]
