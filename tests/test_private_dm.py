"""The DM surface: navigation, profile, chats, plans, the guide, and the buy flow.

Same rule as `test_smoke`: no database, no Redis, no Telegram. Everything the
handlers do beyond a `send()`/`edit()` call is a pure function of facts, which is
why the text shaping, the keyboards and the callback parsing were kept out of the
handlers themselves — this suite calls those directly.

DECISION: the purchase is tested as a chain, not per step. What actually breaks
is a button whose data the *next* step cannot parse, so each test takes the
`callback_data` a keyboard really emits and feeds it to the parser the handler
really uses. Asserting the two halves independently would pass while the flow was
broken end to end — which is exactly the bug the first draft of this module had.

DECISION: navigation is tested as "every screen offers a way out". A DM that
edits itself in place has no scrollback to fall back on, so a screen whose
keyboard omits the home button is a genuine dead end — that is the property, not
the exact buttons any one screen carries.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, User
import pytest

from bot import access
from bot.__main__ import PRIVATE_COMMANDS
from bot.commands import private
from bot.commands.private import (
    CB_CHAT,
    CB_CHATS,
    CB_DIGEST,
    CB_GUIDE,
    CB_HOME,
    CB_PAGE,
    CB_PLANS,
    CB_PROFILE,
    PROFILE_CHAT_PREVIEW,
    TERMS,
    _authorized_chat,
    _chat_options,
    _chats_screen,
    _chats_text,
    _choose_chat_screen,
    _choose_term_screen,
    _digest_screen,
    _display_name,
    _guide_index_screen,
    _guide_page_screen,
    _help_screen,
    _menu_screen,
    _notice_screen,
    _parse_plan,
    _period_options,
    _plan_options,
    _plans_screen,
    _plans_text,
    _profile_screen,
    _profile_text,
    _report_screen,
    _term_options,
)
from bot.guide import PAGES
from core.billing import MAX_MONTHS
from core.dm_stats import DEFAULT_PERIOD, PERIODS, period_for
from db.models import Chat
from i18n.runtime import SUPPORTED_LOCALES, translator
from shared.config import get_settings
from shared.enums import ChatType, Plan
from shared.plans import PLAN_PRICES, PURCHASABLE_PLANS

# Telegram's own ceiling on `callback_data`. Every button built here has to fit,
# and the longest is a white_label purchase for a chat with a large row id.
CALLBACK_DATA_LIMIT = 64

OPERATOR_ID = 111_222_333
STRANGER_ID = 999_888_777
NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)

RU = translator("ru")

# Fluent groups numbers for the locale — `4 999` in ru, `4,999` in en. That is
# correct for a price, so assertions about amounts compare against text with the
# grouping taken back out rather than demanding raw digits. The ru separator is a
# no-break space (U+00A0 in this CLDR build; U+202F in some), never a plain one,
# so both belong here or `4\xa0999` slips past unstripped.
GROUPING = (" ", "\xa0", " ", ",")


def ungrouped(text: str) -> str:
    for separator in GROUPING:
        text = text.replace(separator, "")
    return text


def make_chat(chat_id: int = 1, **overrides: Any) -> Chat:
    chat = Chat(
        id=chat_id,
        tg_chat_id=-1_001_999_888_000 - chat_id,
        title=f"Chat {chat_id}",
        type=ChatType.SUPERGROUP,
        plan=Plan.FREE,
        plan_expires_at=None,
        grace_until=None,
        owner_tg_id=OPERATOR_ID,
        language="ru",
        timezone="UTC",
        is_active=True,
        settings={},
    )
    for key, value in overrides.items():
        setattr(chat, key, value)
    return chat


def make_user(**overrides: Any) -> User:
    fields: dict[str, Any] = {
        "id": OPERATOR_ID,
        "is_bot": False,
        "first_name": "Ada",
        "last_name": "Lovelace",
        "username": "ada",
        "language_code": "ru",
    }
    fields.update(overrides)
    return User(**fields)


class FakeChatRepo:
    def __init__(self, chats: list[Chat]) -> None:
        self.chats = chats
        self.asked_for: list[int] = []

    async def list_for_admin(self, tg_user_id: int) -> list[Chat]:
        self.asked_for.append(tg_user_id)
        return [chat for chat in self.chats if chat.owner_tg_id == tg_user_id]


class FakeUow:
    def __init__(self, chats: list[Chat]) -> None:
        self.chats = FakeChatRepo(chats)

    async def __aenter__(self) -> FakeUow:
        return self

    async def __aexit__(self, *exc_info: Any) -> bool:
        return False


class FakeDmStats:
    """Stands in for `core.dm_stats.dm_stats` in the two async screens.

    The report text itself is `core.dm_stats`'s own tested concern; here the only
    thing that matters is the keyboard wrapped around whatever it returns.
    """

    async def overall_report(self, **_: Any) -> str:
        return "digest"

    async def chat_report(self, **_: Any) -> str:
        return "report"


@pytest.fixture
def owned(monkeypatch: pytest.MonkeyPatch) -> FakeUow:
    """Two chats, both administered by `OPERATOR_ID` and nobody else."""
    uow = FakeUow([make_chat(1), make_chat(2)])
    monkeypatch.setattr(private, "UnitOfWork", lambda: uow)
    return uow


def grid_data(grid: Any) -> list[str]:
    """The callback data a keyboard grid emits, skipping URL/WebApp buttons."""
    return [button.callback_data for row in grid for button in row if button.callback_data]


def screen_data(screen: Any) -> list[str]:
    return grid_data(screen.keyboard.inline_keyboard) if screen.keyboard else []


def screen_labels(screen: Any) -> list[str]:
    """The visible button text on a screen, in reading order."""
    grid = screen.keyboard.inline_keyboard if screen.keyboard else []
    return [button.text for row in grid for button in row]


# --- the panel gate -------------------------------------------------------------
def test_only_listed_operators_may_open_the_panel(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings().model_copy(update={"superadmin_ids": str(OPERATOR_ID)})
    monkeypatch.setattr(access, "get_settings", lambda: settings)
    assert access.may_open_panel(OPERATOR_ID)
    assert not access.may_open_panel(STRANGER_ID)


def test_an_empty_operator_list_admits_nobody(monkeypatch: pytest.MonkeyPatch) -> None:
    """A blank `SUPERADMIN_IDS` must not read as "everyone"."""
    settings = get_settings().model_copy(update={"superadmin_ids": ""})
    monkeypatch.setattr(access, "get_settings", lambda: settings)
    assert not access.may_open_panel(OPERATOR_ID)


# --- the published command menu -------------------------------------------------
def _answered_command_names() -> set[str]:
    """Every plain command name some message handler in the router answers."""
    router = private.build_router()
    answered: set[str] = set()
    for handler in router.message.handlers:
        for applied in handler.filters or []:
            if isinstance(applied.callback, Command):
                # `commands` also admits compiled patterns; the menu only ever
                # publishes plain names, so those are the ones to match against.
                answered.update(name for name in applied.callback.commands if isinstance(name, str))
    return answered


def _handler_answering(name: str) -> Any:
    """The message handler bound to `/name`, so a test can call it directly."""
    router = private.build_router()
    for handler in router.message.handlers:
        for applied in handler.filters or []:
            command = applied.callback
            if isinstance(command, Command) and name in [
                candidate for candidate in command.commands if isinstance(candidate, str)
            ]:
                return handler.callback
    return None


def test_every_published_dm_command_has_a_handler() -> None:
    """A command in the menu that no router answers is a dead button."""
    published = {name for name, _ in PRIVATE_COMMANDS}
    assert published <= _answered_command_names(), published - _answered_command_names()


@pytest.mark.parametrize("locale", SUPPORTED_LOCALES)
def test_every_published_dm_command_is_described_in_both_locales(locale: str) -> None:
    t = translator(locale)
    for name, description_key in PRIVATE_COMMANDS:
        assert t.has(description_key), (locale, name)


def test_the_operator_console_is_answered_but_never_listed() -> None:
    """The Mini App's door is unlisted on purpose: only its name guards it.

    It must be a real handler (so an operator who knows the name gets in) and it
    must be absent from the published menu (so nobody else is even shown it).
    """
    console = get_settings().panel_command_name
    assert console in _answered_command_names()
    assert console not in {name for name, _ in PRIVATE_COMMANDS}


async def test_the_console_hands_an_operator_the_panel_and_a_stranger_silence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The id check is the boundary; the silence is what keeps it unadvertised.

    A refusal would confirm the command exists to anyone who guessed its name, so
    a stranger's tap has to produce no send at all — not an error, not a "not for
    you". This exercises the handler body, where that decision lives.
    """
    settings = get_settings().model_copy(update={"superadmin_ids": str(OPERATOR_ID)})
    monkeypatch.setattr(access, "get_settings", lambda: settings)
    sent: list[tuple[int, str]] = []

    async def fake_send(chat_id: int, text: str, **_: Any) -> None:
        sent.append((chat_id, text))

    monkeypatch.setattr(private, "send", fake_send)
    console = _handler_answering(get_settings().panel_command_name)
    assert console is not None

    await console(SimpleNamespace(from_user=make_user(id=OPERATOR_ID), chat=SimpleNamespace(id=1)))
    assert sent == [(1, RU("admin-welcome"))]

    await console(SimpleNamespace(from_user=make_user(id=STRANGER_ID), chat=SimpleNamespace(id=2)))
    assert len(sent) == 1  # the stranger's tap added nothing


# --- delivery: a button edits in place, a command sends new ---------------------
async def test_a_button_edits_in_place_while_a_command_sends_new(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A DM that grew by a screen per tap is unreadable in a minute, so a button
    redraws the message it lives on and only a command adds one.
    """
    edited: list[tuple[int, int, str]] = []
    sent: list[tuple[int, str]] = []

    async def fake_edit(chat_id: int, message_id: int, text: str, **_: Any) -> None:
        edited.append((chat_id, message_id, text))

    async def fake_send(chat_id: int, text: str, **_: Any) -> None:
        sent.append((chat_id, text))

    monkeypatch.setattr(private, "edit", fake_edit)
    monkeypatch.setattr(private, "send", fake_send)
    screen = _menu_screen(RU)

    query = SimpleNamespace(message=SimpleNamespace(chat=SimpleNamespace(id=7), message_id=42))
    await private._redraw(cast(CallbackQuery, query), screen)
    assert edited == [(7, 42, screen.text)]
    assert not sent  # a redraw never sends a second message

    edited.clear()
    await private._reply(cast(Message, SimpleNamespace(chat=SimpleNamespace(id=7))), screen)
    assert sent == [(7, screen.text)]
    assert not edited  # a command never edits an existing one


async def test_a_redraw_is_silent_when_its_message_is_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A button on a message the user deleted must not blow up on `.message.id`."""
    called = False

    async def fake_edit(*_a: Any, **_k: Any) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(private, "edit", fake_edit)
    await private._redraw(cast(CallbackQuery, SimpleNamespace(message=None)), _menu_screen(RU))
    assert not called


# --- profile --------------------------------------------------------------------
def test_profile_names_the_person_however_it_can() -> None:
    assert _display_name(make_user(), RU) == "Ada Lovelace"
    assert _display_name(make_user(last_name=None), RU) == "Ada"
    # A user with no name at all still has to be addressable.
    nameless = make_user(first_name="", last_name=None, username="ada")
    assert _display_name(nameless, RU) == "@ada"
    anonymous = make_user(first_name="", last_name=None, username=None)
    # The id has to come out copy-pasteable, not digit-grouped for the locale.
    assert _display_name(anonymous, RU) == f"id{OPERATOR_ID}"


def test_the_profile_id_stays_copy_pasteable() -> None:
    """Fluent groups bare numbers per locale; an id in <code> must not be."""
    for locale in SUPPORTED_LOCALES:
        text = _profile_text(make_user(), [], translator(locale))
        assert f"<code>{OPERATOR_ID}</code>" in text, locale


def test_profile_lists_chats_up_to_the_preview_then_counts_the_rest() -> None:
    chats = [make_chat(i) for i in range(1, PROFILE_CHAT_PREVIEW + 3)]
    text = _profile_text(make_user(), chats, RU)
    for chat in chats[:PROFILE_CHAT_PREVIEW]:
        assert chat.title in text
    for chat in chats[PROFILE_CHAT_PREVIEW:]:
        assert chat.title not in text
    # The overflow line points at the command that shows the full list.
    assert "/chats" in text


def test_profile_of_a_user_with_no_chats_still_renders() -> None:
    text = _profile_text(make_user(), [], RU)
    assert "Ada Lovelace" in text
    assert "{" not in text  # no placeable leaked out of the plural selector


# --- chats ----------------------------------------------------------------------
def test_chats_shows_the_renewal_date_only_for_a_paid_plan() -> None:
    paid = make_chat(1, plan=Plan.PRO, plan_expires_at=NOW, title="Paid")
    free = make_chat(2, title="Free chat")
    text = _chats_text([paid, free], RU)
    assert "10.08.2026" in text
    # The Free row must not carry a date — it has no expiry to show.
    free_line = next(line for line in text.splitlines() if "Free chat" in line)
    assert "10.08.2026" not in free_line


def test_a_paid_chat_with_no_expiry_is_rendered_as_open_ended() -> None:
    """A plan set by hand has no `plan_expires_at`; formatting one would crash."""
    chat = make_chat(1, plan=Plan.BUSINESS, plan_expires_at=None)
    text = _chats_text([chat], RU)
    assert RU("plan-business") in text


def test_a_chat_without_a_title_gets_a_placeholder() -> None:
    text = _chats_text([make_chat(1, title=None)], RU)
    assert RU("dm-chat-untitled") in text


def test_no_chats_explains_how_to_get_one() -> None:
    assert _chats_text([], RU) == RU("dm-chats-empty")


def test_a_chat_title_with_markup_is_escaped_in_the_body() -> None:
    """A title lands inside a <b> tag; a raw `<` would make Telegram drop it all."""
    text = _chats_text([make_chat(1, title="<b>evil</b>")], RU)
    assert "<b>evil</b>" not in text
    assert "&lt;b&gt;evil&lt;/b&gt;" in text


# --- plans ----------------------------------------------------------------------
def test_plans_quotes_every_purchasable_plan_and_no_other() -> None:
    text = _plans_text(RU)
    for plan in PURCHASABLE_PLANS:
        assert str(PLAN_PRICES[plan].stars) in ungrouped(text)
        assert PLAN_PRICES[plan].usd in text
    assert RU("plan-free") not in text  # Free is not for sale
    assert str(MAX_MONTHS) in text


def test_free_is_never_offered_as_something_to_buy() -> None:
    assert _parse_plan(Plan.FREE.value) is None
    assert _parse_plan("nonsense") is None
    for plan in PURCHASABLE_PLANS:
        assert _parse_plan(plan.value) is plan


# --- the purchase, followed the way a user walks it -----------------------------
def test_the_plan_button_carries_a_plan_the_next_step_can_parse() -> None:
    """`dm:chat:<plan>` — the bug this catches is a prefix the next step misses."""
    for data in grid_data(_plan_options(RU)):
        assert data.startswith(f"{CB_CHAT}:")
        assert _parse_plan(data.split(":")[-1]) in PURCHASABLE_PLANS


def test_the_chat_button_carries_both_the_plan_and_the_chat() -> None:
    chats = [make_chat(1), make_chat(2)]
    for data in grid_data(_chat_options(Plan.PRO, chats, RU)):
        parts = data.split(":")
        assert len(parts) == 4  # the shape `term_step` checks before parsing
        assert _parse_plan(parts[2]) is Plan.PRO
        assert int(parts[3]) in {chat.id for chat in chats}


def test_the_term_button_carries_every_decision_the_invoice_needs() -> None:
    for data in grid_data(_term_options(Plan.BUSINESS, 42, RU)):
        parts = data.split(":")
        assert len(parts) == 5  # the shape `buy_step` checks before parsing
        assert _parse_plan(parts[2]) is Plan.BUSINESS
        assert int(parts[3]) == 42
        assert int(parts[4]) in TERMS


def test_every_offered_term_is_one_billing_will_accept() -> None:
    """A button offering 24 months would mint an invoice the ledger refuses."""
    assert all(1 <= months <= MAX_MONTHS for months in TERMS)


def test_the_term_button_prices_the_whole_term_not_one_month() -> None:
    stars = PLAN_PRICES[Plan.PRO].stars
    labels = [button.text for row in _term_options(Plan.PRO, 1, RU) for button in row]
    for months, label in zip(TERMS, labels, strict=True):
        assert str(stars * months) in ungrouped(label)


def test_no_button_exceeds_telegrams_callback_data_limit() -> None:
    # Plausible worst cases: the priciest plan, a large chat row id, longest term,
    # and the per-chat report's period switcher (which carries the id and a slug).
    big = 2_147_483_647
    grids = [
        _plan_options(RU),
        _chat_options(Plan.WHITE_LABEL, [make_chat(big)], RU),
        _term_options(Plan.WHITE_LABEL, big, RU),
        _period_options(RU, f"dm:sc:{big}", DEFAULT_PERIOD),
    ]
    for grid in grids:
        for data in grid_data(grid):
            assert len(data.encode()) <= CALLBACK_DATA_LIMIT, data


# --- authorization: a callback's chat id is never trusted -----------------------
@pytest.mark.parametrize("raw", ["", "abc", "1;DROP", "1.5", " 1", "--1"])
async def test_a_malformed_chat_id_resolves_to_nothing(owned: FakeUow, raw: str) -> None:
    """Callback data is client-supplied; a junk id must fail closed, not crash.

    `--1` is the one that bit: `lstrip("-")` would have peeled both dashes and let
    it reach `int()` as a live exception in a handler anyone can trigger.
    """
    assert await _authorized_chat(OPERATOR_ID, raw) is None


async def test_a_chat_you_administer_resolves(owned: FakeUow) -> None:
    chat = await _authorized_chat(OPERATOR_ID, "1")
    assert chat is not None and chat.id == 1


async def test_a_chat_you_do_not_administer_is_refused(owned: FakeUow) -> None:
    """The hole this closes: buying a plan for someone else's chat by its id."""
    assert await _authorized_chat(STRANGER_ID, "1") is None


# --- navigation: no screen is a dead end ----------------------------------------
def test_the_root_menu_links_to_every_section() -> None:
    data = screen_data(_menu_screen(RU))
    assert CB_PROFILE in data
    assert CB_CHATS in data
    assert CB_PLANS in data
    assert CB_GUIDE in data
    # Statistics opens on a default window, so its button carries a period.
    assert any(item.startswith(f"{CB_DIGEST}:") for item in data)


def test_every_non_root_screen_offers_the_way_home() -> None:
    plan = next(iter(PURCHASABLE_PLANS))
    chat = make_chat(1)
    screens = [
        _profile_screen(make_user(), [chat], RU),
        _chats_screen([chat], RU),
        _chats_screen([], RU),  # even the empty list is not a trap
        _plans_screen(RU),
        _choose_chat_screen(plan, [chat], RU),
        _choose_term_screen(plan, chat, RU),
        _guide_index_screen(RU),
        _guide_page_screen(PAGES[0], RU),
        _help_screen(RU),
        _notice_screen(RU("dm-chat-unavailable"), RU),
    ]
    for screen in screens:
        assert CB_HOME in screen_data(screen), screen.text


async def test_the_async_report_screens_also_offer_the_way_home(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The digest and a single report edit in place too, so they need an exit."""
    monkeypatch.setattr(private, "dm_stats", FakeDmStats())
    chats = [make_chat(1), make_chat(2)]
    digest = await _digest_screen(chats, DEFAULT_PERIOD, OPERATOR_ID, RU)
    report = await _report_screen(chats[0], DEFAULT_PERIOD, OPERATOR_ID, RU)
    assert CB_HOME in screen_data(digest)
    assert CB_HOME in screen_data(report)


# --- the statistics window switcher ---------------------------------------------
def test_every_period_button_names_a_window_the_handler_can_resolve() -> None:
    for data in grid_data(_period_options(RU, CB_DIGEST, DEFAULT_PERIOD)):
        assert period_for(data.split(":")[-1]) is not None


def test_the_current_window_is_the_only_one_marked() -> None:
    """Without the mark, switching windows looks like a bot ignoring the tap."""
    marked = RU("dm-stats-period-current", period=DEFAULT_PERIOD.label(RU))
    labels = [
        button.text for row in _period_options(RU, CB_DIGEST, DEFAULT_PERIOD) for button in row
    ]
    assert labels.count(marked) == 1
    for period in PERIODS:
        if period is not DEFAULT_PERIOD:
            assert period.label(RU) in labels


# --- the manual -----------------------------------------------------------------
def test_the_guide_index_lists_every_page() -> None:
    data = set(screen_data(_guide_index_screen(RU)))
    for page in PAGES:
        assert f"{CB_PAGE}:{page.slug}" in data


def test_a_guide_page_offers_only_the_neighbours_that_exist() -> None:
    """The list is not a ring: the first page has no previous, the last no next."""
    first = screen_labels(_guide_page_screen(PAGES[0], RU))
    last = screen_labels(_guide_page_screen(PAGES[-1], RU))
    assert RU("guide-nav-prev") not in first
    assert RU("guide-nav-next") in first
    assert RU("guide-nav-prev") in last
    assert RU("guide-nav-next") not in last


# --- rendering ------------------------------------------------------------------
@pytest.mark.parametrize("locale", SUPPORTED_LOCALES)
def test_no_dm_screen_leaks_a_placeable_in_either_locale(locale: str) -> None:
    """A missing plural branch shows up as a literal `{$count}` in the chat.

    The check is for braces rather than a bare `$`: the plans screen quotes a
    price in dollars, so `$4.99` is content, while `{` never is.
    """
    t = translator(locale)
    chats = [make_chat(i, plan=Plan.PRO, plan_expires_at=NOW) for i in range(1, 6)]
    screens = [
        _profile_text(make_user(), [], t),
        _profile_text(make_user(), chats, t),
        _chats_text([], t),
        _chats_text(chats, t),
        _plans_text(t),
        _menu_screen(t).text,
        _help_screen(t).text,
        _guide_index_screen(t).text,
    ]
    for screen in screens:
        assert "{" not in screen, (locale, screen)
        assert "}" not in screen, (locale, screen)
