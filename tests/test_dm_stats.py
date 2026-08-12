"""The private-chat statistics report, rendered without a database.

Same rule as `test_smoke` and `test_private_dm`: no Postgres, no Redis, no
Telegram. `core.dm_stats` reaches for exactly three module-level symbols —
`UnitOfWork`, `features` and `stats` — so each of them is replaced here and the
report is exercised as the pure text shaping it is.

DECISION: nothing asserts wording. Fluent echoes a key back when it cannot
resolve it, so `t(key) != key` is the check that a line exists at all, and the
numbers are compared against what the fakes were told to return. Wording is being
edited in the locales in parallel; the shape of the screen is what has to hold.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from core import dm_stats as module
from core.dm_stats import (
    ACTION_LABELS,
    BREAKDOWN_LIMIT,
    DEFAULT_PERIOD,
    OTHER_ACTION_LABEL,
    PERIODS,
    ModerationCounters,
    StatsPeriod,
    dm_stats,
    period_for,
)
from core.reports import sparkline
from i18n.runtime import SUPPORTED_LOCALES, translator
from shared.enums import PunishmentType
from shared.plans import Feature
from shared.schemas.api import StatPoint, StatsOverview, TopUser

RU = translator("ru")
NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)

VIEWER_ID = 111_222_333
OTHER_MODERATOR_ID = 444_555_666

# A title an owner really could have typed: markup that must be escaped, an
# ampersand, and a Fluent placeable that must stay inert data.
HOSTILE_TITLE = '<b>Chat</b> & {$count} "quoted"'


class FakeModerationLogs:
    """The four log reads the report makes, answered from a table of rows.

    `bonus` makes one chat busier than another without a second fixture, which is
    what the digest's ordering needs.
    """

    def __init__(
        self,
        rows: list[tuple[str, int | None]],
        previous: int = 0,
        bonus: dict[int, int] | None = None,
    ) -> None:
        self.rows = rows
        self.previous = previous
        self.bonus = bonus or {}

    async def count_since(
        self, chat_id: int, since: datetime, *, until: datetime | None = None
    ) -> int:
        # `until` is only ever passed for the window before this one.
        if until is not None:
            return self.previous
        return len(self.rows) + self.bonus.get(chat_id, 0)

    async def count_for_moderator(self, chat_id: int, moderator_tg_id: int, since: datetime) -> int:
        if moderator_tg_id <= 0:
            return 0
        return sum(1 for _, moderator in self.rows if moderator == moderator_tg_id)

    async def moderator_split(self, chat_id: int, since: datetime) -> dict[str, int]:
        automated = [row for row in self.rows if row[1] is None or row[1] <= 0]
        humans = {row[1] for row in self.rows if row[1] is not None and row[1] > 0}
        return {"automated": len(automated), "moderators": len(humans)}

    async def count_by_action(
        self, chat_id: int, since: datetime, *, limit: int = 20
    ) -> list[tuple[str, int]]:
        totals: dict[str, int] = {}
        for action, _ in self.rows:
            totals[action] = totals.get(action, 0) + 1
        return sorted(totals.items(), key=lambda item: (-item[1], item[0]))[:limit]


class FakeWarns:
    def __init__(self, issued: int) -> None:
        self.issued = issued

    async def count_issued(self, chat_id: int, since: datetime) -> int:
        return self.issued


class FakePunishments:
    def __init__(self, by_type: dict[str, int]) -> None:
        self.by_type = by_type

    async def count_issued_by_type(self, chat_id: int, since: datetime) -> dict[str, int]:
        return dict(self.by_type)


class FakeUow:
    def __init__(
        self,
        *,
        rows: list[tuple[str, int | None]] | None = None,
        warns: int = 0,
        punishments: dict[str, int] | None = None,
        previous: int = 0,
        bonus: dict[int, int] | None = None,
    ) -> None:
        self.moderation_logs = FakeModerationLogs(rows or [], previous=previous, bonus=bonus)
        self.warns = FakeWarns(warns)
        self.punishments = FakePunishments(punishments or {})

    async def __aenter__(self) -> FakeUow:
        return self

    async def __aexit__(self, *exc_info: Any) -> bool:
        return False


class FakeFeatures:
    """The plan gate, answering the same way for every chat."""

    def __init__(self, *, pro: bool) -> None:
        self.pro = pro
        self.asked: list[Feature] = []

    async def has(self, chat_id: int, feature: Feature) -> bool:
        self.asked.append(feature)
        return self.pro


class FakeStats:
    def __init__(self, overview: StatsOverview) -> None:
        self.overview_value = overview
        self.calls: list[tuple[int, int]] = []

    async def overview(self, chat_id: int, *, days: int = 7) -> StatsOverview:
        self.calls.append((chat_id, days))
        return self.overview_value


def make_overview(**overrides: Any) -> StatsOverview:
    series = [
        StatPoint(
            date=date(2026, 8, 6) + timedelta(days=offset),
            messages=messages,
            active_users=5,
            joins=1,
            leaves=0,
            moderation_actions=0,
        )
        for offset, messages in enumerate((10, 40, 90, 20, 5))
    ]
    fields: dict[str, Any] = {
        "period_days": 7,
        "total_messages": 165,
        "total_active_users": 12,
        "total_joins": 5,
        "total_leaves": 2,
        "net_growth": 3,
        "series": series,
        "top_users": [TopUser(tg_user_id=900_001, messages=90, display_name="Ada")],
    }
    fields.update(overrides)
    return StatsOverview(**fields)


def install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    uow: FakeUow | None = None,
    pro: bool = True,
    overview: StatsOverview | None = None,
) -> tuple[FakeFeatures, FakeStats]:
    """Point the module's three collaborators at fakes."""
    fake_uow = uow or FakeUow()
    fake_features = FakeFeatures(pro=pro)
    fake_stats = FakeStats(overview or make_overview())
    monkeypatch.setattr(module, "UnitOfWork", lambda: fake_uow)
    monkeypatch.setattr(module, "features", fake_features)
    monkeypatch.setattr(module, "stats", fake_stats)
    return fake_features, fake_stats


def busy_chat(bonus: dict[int, int] | None = None) -> FakeUow:
    """One week of a chat that needed real moderation."""
    rows: list[tuple[str, int | None]] = [
        ("warn", VIEWER_ID),
        ("warn", VIEWER_ID),
        ("warn", OTHER_MODERATOR_ID),
        ("mute", VIEWER_ID),
        ("ban", OTHER_MODERATOR_ID),
        ("auto_delete", None),
        ("auto_delete", None),
        ("warn", 0),  # an automatic warn: the sentinel, not a person
        ("auto_unmute", None),
    ]
    return FakeUow(
        rows=rows,
        warns=4,
        punishments={PunishmentType.MUTE.value: 1, PunishmentType.BAN.value: 1},
        previous=5,
        bonus=bonus,
    )


# --- windows ------------------------------------------------------------------
@pytest.mark.parametrize("period", PERIODS)
def test_every_offered_window_resolves_by_its_slug(period: StatsPeriod) -> None:
    assert period_for(period.slug) is period
    assert period.days > 0
    # The label is copy, not a fallback: an unresolved key would read as the key.
    for locale in SUPPORTED_LOCALES:
        t = translator(locale)
        assert period.label(t) != period.label_key


@pytest.mark.parametrize("slug", ["", "1D", "7", "8d", "nonsense", "1d;drop", "365d"])
def test_an_unknown_window_resolves_to_nothing(slug: str) -> None:
    """Slugs arrive inside callback data, which is whatever the client sent."""
    assert period_for(slug) is None


def test_the_default_window_is_one_of_the_offered_ones() -> None:
    assert DEFAULT_PERIOD in PERIODS


# --- the counter block --------------------------------------------------------
def test_a_missing_counter_stays_off_the_screen_but_a_zero_is_shown() -> None:
    known = module._counter_lines(ModerationCounters(actions=0, warns=0), RU)
    assert RU("report-moderation-warns", count=0) in "\n".join(known)

    unknown = module._counter_lines(ModerationCounters(actions=0), RU)
    text = "\n".join(unknown)
    assert RU("report-moderation-actions", count=0) in text
    # Nothing about warnings at all — not "0", which would be a claim.
    assert "report-moderation-warns" not in text
    assert RU("report-moderation-warns", count=0) not in text


@pytest.mark.parametrize(
    "counters",
    [
        ModerationCounters(actions=3),
        ModerationCounters(actions=3, warns=1),
        ModerationCounters(actions=3, warns=1, punishments=2, mine=1),
        ModerationCounters(actions=3, warns=1, punishments=2, mine=1, automated=1, moderators=2),
        # A hole in the middle: the tree must still close on the last line present.
        ModerationCounters(actions=3, mine=1),
        ModerationCounters(actions=3, moderators=0),
    ],
)
def test_the_tree_branches_on_every_line_but_the_last(counters: ModerationCounters) -> None:
    lines = module._counter_lines(counters, RU)
    body = lines[1:]
    assert body, "the block always has at least the total"
    assert all(line.startswith("├ ") for line in body[:-1])
    assert body[-1].startswith("└ ")
    assert sum(line.startswith("└") for line in lines) == 1


def test_the_counter_block_counts_one_line_per_present_counter() -> None:
    full = ModerationCounters(actions=9, warns=4, punishments=2, mine=3, automated=4, moderators=2)
    assert len(module._counter_lines(full, RU)) == 7  # title + six counters


# --- the trend line -----------------------------------------------------------
def test_the_trend_names_the_previous_total_and_signs_the_change() -> None:
    rising = module._trend_lines(ModerationCounters(actions=9, previous=5), RU)[0]
    assert rising == RU("report-moderation-trend", previous=5, delta="+4")
    falling = module._trend_lines(ModerationCounters(actions=2, previous=5), RU)[0]
    assert falling == RU("report-moderation-trend", previous=5, delta="-3")


def test_a_period_with_nothing_on_either_side_says_nothing_about_the_trend() -> None:
    assert module._trend_lines(ModerationCounters(actions=0, previous=0), RU) == []
    assert module._trend_lines(ModerationCounters(actions=4), RU) == []


# --- the breakdown ------------------------------------------------------------
def test_the_breakdown_sums_actions_that_share_a_label() -> None:
    counters = ModerationCounters(actions=5, breakdown=(("auto_unmute", 3), ("auto_unban", 2)))
    lines = module._breakdown_lines(counters, RU)
    label = RU(ACTION_LABELS["auto_unmute"])
    assert len(lines) == 2  # title plus the single merged row
    assert RU("report-breakdown-row", label=label, count=5) in lines


def test_an_unmapped_action_lands_in_the_tail_instead_of_disappearing() -> None:
    counters = ModerationCounters(actions=7, breakdown=(("warn", 4), ("something_new", 3)))
    lines = module._breakdown_lines(counters, RU)
    assert RU("report-breakdown-row", label=RU(OTHER_ACTION_LABEL), count=3) in lines


def test_the_breakdown_prints_a_bounded_number_of_rows_and_keeps_the_total() -> None:
    breakdown = tuple((action, index + 1) for index, action in enumerate(ACTION_LABELS))
    lines = module._breakdown_lines(ModerationCounters(actions=0, breakdown=breakdown), RU)
    assert len(lines) == 1 + BREAKDOWN_LIMIT + 1  # title, the top rows, the tail


def test_a_chat_with_no_actions_has_no_breakdown_block() -> None:
    assert module._breakdown_lines(ModerationCounters(actions=0), RU) == []


@pytest.mark.parametrize("locale", SUPPORTED_LOCALES)
def test_every_action_label_is_translated_in_both_locales(locale: str) -> None:
    """The labels are looked up by variable, so no static check covers them."""
    t = translator(locale)
    for key in (*ACTION_LABELS.values(), OTHER_ACTION_LABEL):
        assert t.has(key), (locale, key)


# --- the reads ----------------------------------------------------------------
async def test_the_counters_come_from_the_repositories(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, uow=busy_chat())
    counters = await dm_stats.counters(
        chat_id=1, period=DEFAULT_PERIOD, viewer_tg_id=VIEWER_ID, now=NOW
    )
    assert counters.actions == 9
    assert counters.warns == 4
    assert counters.punishments == 2  # one mute plus one ban
    assert counters.mine == 3
    assert counters.previous == 5
    assert dict(counters.breakdown)["warn"] == 4


async def test_the_bot_is_never_counted_as_a_moderator(monkeypatch: pytest.MonkeyPatch) -> None:
    """NULL and the `0` sentinel both mean "the bot did this on its own"."""
    install(monkeypatch, uow=busy_chat())
    counters = await dm_stats.counters(
        chat_id=1, period=DEFAULT_PERIOD, viewer_tg_id=VIEWER_ID, now=NOW
    )
    assert counters.automated == 4  # three NULLs and one sentinel row
    assert counters.moderators == 2  # the viewer and one colleague, not the bot


async def test_asking_as_the_sentinel_credits_nobody(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, uow=busy_chat())
    counters = await dm_stats.counters(chat_id=1, period=DEFAULT_PERIOD, viewer_tg_id=0, now=NOW)
    assert counters.mine == 0


async def test_the_digest_read_skips_the_single_chat_extras(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Those reads are multiplied by every chat someone administers."""
    install(monkeypatch, uow=busy_chat())
    counters = await dm_stats.counters(
        chat_id=1, period=DEFAULT_PERIOD, viewer_tg_id=VIEWER_ID, now=NOW, detailed=False
    )
    assert counters.actions == 9
    assert counters.mine == 3
    assert counters.automated is None
    assert counters.moderators is None
    assert counters.previous is None
    assert counters.breakdown == ()


# --- the paid gate ------------------------------------------------------------
@pytest.mark.parametrize("locale", SUPPORTED_LOCALES)
async def test_a_free_chat_loses_the_analytics_and_keeps_the_moderation(
    monkeypatch: pytest.MonkeyPatch, locale: str
) -> None:
    t = translator(locale)
    gate, activity = install(monkeypatch, uow=busy_chat(), pro=False)
    text = await dm_stats.chat_report(
        chat_id=1, title="Chat", period=DEFAULT_PERIOD, viewer_tg_id=VIEWER_ID, t=t
    )

    assert gate.asked == [Feature.STATS]
    assert not activity.calls, "a locked chat must not be charged a statistics read"
    assert t("report-locked-title") in text
    assert t("report-messages", count=165) not in text
    # The record of the admins' own work is not for sale.
    assert t("report-moderation-title") in text
    assert t("report-moderation-actions", count=9) in text
    assert t("report-moderation-mine", count=3) in text


async def test_a_pro_chat_gets_the_charts_and_the_board(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, activity = install(monkeypatch, uow=busy_chat())
    text = await dm_stats.chat_report(
        chat_id=7, title="Chat", period=DEFAULT_PERIOD, viewer_tg_id=VIEWER_ID, t=RU
    )
    assert activity.calls == [(7, DEFAULT_PERIOD.days)]
    assert RU("report-messages", count=165) in text
    assert RU("report-top-title") in text
    assert "Ada" in text
    # The busiest day of the fixture series, named by its ISO date.
    assert RU("report-peak", date="2026-08-08", count=90) in text
    assert RU("report-locked-title") not in text


async def test_the_moderation_chart_waits_for_data_that_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`StatDaily.moderation_actions` is all zeros until something records it."""
    install(monkeypatch, uow=busy_chat())
    flat = await dm_stats.chat_report(
        chat_id=1, title="Chat", period=DEFAULT_PERIOD, viewer_tg_id=VIEWER_ID, t=RU
    )
    assert RU("report-chart-moderation", chart=sparkline([0, 0, 0, 0, 0])) not in flat

    load = [0, 1, 2, 3, 4]
    series = [
        point.model_copy(update={"moderation_actions": actions})
        for point, actions in zip(make_overview().series, load, strict=True)
    ]
    install(monkeypatch, uow=busy_chat(), overview=make_overview(series=series))
    loaded = await dm_stats.chat_report(
        chat_id=1, title="Chat", period=DEFAULT_PERIOD, viewer_tg_id=VIEWER_ID, t=RU
    )
    assert RU("report-chart-moderation", chart=sparkline(load)) in loaded


async def test_a_chat_with_no_history_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, overview=make_overview(series=[], top_users=[], total_messages=0))
    text = await dm_stats.chat_report(
        chat_id=1, title="Chat", period=DEFAULT_PERIOD, viewer_tg_id=VIEWER_ID, t=RU
    )
    assert RU("report-empty") in text
    assert RU("report-top-title") not in text


# --- the digest ---------------------------------------------------------------
async def test_a_digest_with_no_chats_explains_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install(monkeypatch)
    text = await dm_stats.overall_report(
        chats=[], period=DEFAULT_PERIOD, viewer_tg_id=VIEWER_ID, t=RU
    )
    assert RU("report-overall-none") in text
    assert RU("report-overall-chats", count=0) in text
    # No tree, no rows: there is nothing to total up.
    assert "└" not in text


async def test_the_digest_totals_every_chat_and_leads_with_the_busiest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install(monkeypatch, uow=busy_chat(bonus={2: 5}))
    text = await dm_stats.overall_report(
        chats=[(1, "Quiet"), (2, "Loud")],
        period=DEFAULT_PERIOD,
        viewer_tg_id=VIEWER_ID,
        t=RU,
    )
    # Both chats answer from the same fake, so the totals are twice one chat plus
    # the five extra actions chat 2 was given.
    assert RU("report-moderation-actions", count=23) in text
    assert RU("report-moderation-warns", count=8) in text
    assert RU("report-moderation-punishments", count=4) in text
    assert RU("report-moderation-mine", count=6) in text
    assert RU("report-messages", count=330) in text
    # Summed across chats, a head count would double-count a shared moderator.
    assert RU("report-moderation-moderators", count=2) not in text

    rows = [line for line in text.splitlines() if line.startswith("•")]
    assert len(rows) == 2
    assert "Loud" in rows[0] and "Quiet" in rows[1]


# --- what reaches the chat ----------------------------------------------------
@pytest.mark.parametrize("locale", SUPPORTED_LOCALES)
async def test_no_screen_leaks_a_placeable(monkeypatch: pytest.MonkeyPatch, locale: str) -> None:
    """A missing plural branch shows up as a literal `{$count}` in the chat."""
    t = translator(locale)
    install(monkeypatch, uow=busy_chat())
    screens = [
        await dm_stats.chat_report(
            chat_id=1, title="Chat", period=period, viewer_tg_id=VIEWER_ID, t=t
        )
        for period in PERIODS
    ]
    install(monkeypatch, uow=busy_chat(), pro=False)
    screens.append(
        await dm_stats.chat_report(
            chat_id=1, title="Chat", period=DEFAULT_PERIOD, viewer_tg_id=VIEWER_ID, t=t
        )
    )
    install(monkeypatch, uow=FakeUow())
    screens.append(
        await dm_stats.overall_report(chats=[], period=DEFAULT_PERIOD, viewer_tg_id=VIEWER_ID, t=t)
    )
    screens.append(
        await dm_stats.overall_report(
            chats=[(1, "One"), (2, "Two")], period=DEFAULT_PERIOD, viewer_tg_id=VIEWER_ID, t=t
        )
    )
    for screen in screens:
        assert "{" not in screen, (locale, screen)
        assert "}" not in screen, (locale, screen)


async def test_a_chat_title_is_markup_from_a_stranger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parse mode is HTML and a title is whatever its owner typed.

    Braces in the title survive as text, which is the point: Fluent must treat an
    argument as data and never as syntax, so the report cannot be made to render
    something the copy does not say.
    """
    install(monkeypatch, uow=busy_chat())
    chat = await dm_stats.chat_report(
        chat_id=1, title=HOSTILE_TITLE, period=DEFAULT_PERIOD, viewer_tg_id=VIEWER_ID, t=RU
    )
    digest = await dm_stats.overall_report(
        chats=[(1, HOSTILE_TITLE)], period=DEFAULT_PERIOD, viewer_tg_id=VIEWER_ID, t=RU
    )
    for text in (chat, digest):
        assert "<b>Chat</b>" not in text
        assert "&lt;b&gt;Chat&lt;/b&gt;" in text
        assert "&amp;" in text
        # The placeable in the title stayed a literal instead of being filled in.
        assert "{$count}" in text
        assert "{$count} " in text or text.endswith("{$count}") or '{$count} "' in text
