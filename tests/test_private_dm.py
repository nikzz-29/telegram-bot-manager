"""The DM surface: profile, chats, plans, and the inline purchase flow.

Same rule as `test_smoke`: no database, no Redis, no Telegram. Everything the
handlers do beyond a `send()` call is a pure function of facts, which is why the
text shaping and the callback parsing were kept out of the handlers themselves —
this suite calls those functions directly.

DECISION: the purchase is tested as a chain, not per step. What actually breaks
is a button whose data the *next* step cannot parse, so each test takes the
`callback_data` a keyboard really emits and feeds it to the parser the handler
really uses. Asserting the two halves independently would pass while the flow was
broken end to end — which is exactly the bug the first draft of this module had.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from aiogram.filters import Command
from aiogram.types import User
import pytest

from bot import access
from bot.__main__ import PRIVATE_COMMANDS
from bot.commands import private
from bot.commands.private import (
    PROFILE_CHAT_PREVIEW,
    TERMS,
    _authorized_chat,
    _chat_keyboard,
    _chats_text,
    _display_name,
    _parse_plan,
    _plans_keyboard,
    _plans_text,
    _profile_text,
    _term_keyboard,
)
from core.billing import MAX_MONTHS
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
# grouping taken back out rather than demanding raw digits.
GROUPING = (" ", " ", ",", " ")


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


@pytest.fixture
def owned(monkeypatch: pytest.MonkeyPatch) -> FakeUow:
    """Two chats, both administered by `OPERATOR_ID` and nobody else."""
    uow = FakeUow([make_chat(1), make_chat(2)])
    monkeypatch.setattr(private, "UnitOfWork", lambda: uow)
    return uow


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
def test_every_published_dm_command_has_a_handler() -> None:
    """A command in the menu that no router answers is a dead button."""
    router = private.build_router()
    answered: set[str] = set()
    for handler in router.message.handlers:
        for applied in handler.filters or []:
            if isinstance(applied.callback, Command):
                # `commands` also admits compiled patterns; the menu only ever
                # publishes plain names, so those are the ones to match against.
                answered.update(name for name in applied.callback.commands if isinstance(name, str))
    published = {name for name, _ in PRIVATE_COMMANDS}
    assert published <= answered, published - answered


@pytest.mark.parametrize("locale", SUPPORTED_LOCALES)
def test_every_published_dm_command_is_described_in_both_locales(locale: str) -> None:
    t = translator(locale)
    for name, description_key in PRIVATE_COMMANDS:
        assert t.has(description_key), (locale, name)


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
def callback_data(keyboard: Any) -> list[str]:
    return [button.callback_data for row in keyboard.inline_keyboard for button in row]


def test_the_plan_button_carries_a_plan_the_next_step_can_parse() -> None:
    """`dm:chat:<plan>` — the bug this catches is a prefix the next step misses."""
    for data in callback_data(_plans_keyboard(RU)):
        assert _parse_plan(data.split(":")[-1]) in PURCHASABLE_PLANS


def test_the_chat_button_carries_both_the_plan_and_the_chat() -> None:
    chats = [make_chat(1), make_chat(2)]
    for data in callback_data(_chat_keyboard(Plan.PRO, chats, RU)):
        parts = data.split(":")
        assert len(parts) == 4  # the shape `term_step` checks before parsing
        assert _parse_plan(parts[2]) is Plan.PRO
        assert int(parts[3]) in {chat.id for chat in chats}


def test_the_term_button_carries_every_decision_the_invoice_needs() -> None:
    for data in callback_data(_term_keyboard(Plan.BUSINESS, 42, RU)):
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
    labels = [
        button.text for row in _term_keyboard(Plan.PRO, 1, RU).inline_keyboard for button in row
    ]
    for months, label in zip(TERMS, labels, strict=True):
        assert str(stars * months) in ungrouped(label)


def test_no_button_exceeds_telegrams_callback_data_limit() -> None:
    # A plausible worst case: the priciest plan, a large chat row id, longest term.
    keyboards = [
        _plans_keyboard(RU),
        _chat_keyboard(Plan.WHITE_LABEL, [make_chat(2_147_483_647)], RU),
        _term_keyboard(Plan.WHITE_LABEL, 2_147_483_647, RU),
    ]
    for keyboard in keyboards:
        for data in callback_data(keyboard):
            assert len(data.encode()) <= CALLBACK_DATA_LIMIT, data


# --- the authorization re-check -------------------------------------------------
async def test_a_chat_you_administer_resolves(owned: FakeUow) -> None:
    chat = await _authorized_chat(OPERATOR_ID, "1")
    assert chat is not None
    assert chat.id == 1


async def test_a_replayed_button_cannot_buy_a_plan_for_someone_elses_chat(
    owned: FakeUow,
) -> None:
    """Callback data is client-supplied: the chat id in it proves nothing."""
    assert await _authorized_chat(STRANGER_ID, "1") is None


async def test_an_unknown_chat_id_resolves_to_nothing(owned: FakeUow) -> None:
    assert await _authorized_chat(OPERATOR_ID, "4242") is None


@pytest.mark.parametrize("raw", ["", "abc", "1;DROP", "1.5", " 1", "--1"])
async def test_a_malformed_chat_id_is_refused_before_it_reaches_the_database(
    owned: FakeUow, raw: str
) -> None:
    assert await _authorized_chat(OPERATOR_ID, raw) is None
    assert not owned.chats.asked_for  # rejected without a query


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
    ]
    for screen in screens:
        assert "{" not in screen, (locale, screen)
        assert "}" not in screen, (locale, screen)
