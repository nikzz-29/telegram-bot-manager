"""Stage 2 pure units: captcha generation, join screening, greeting rendering.

Same rule as `test_smoke`: no database, no Redis, no Telegram. Everything here
is a function that takes facts and returns a decision, which is exactly why the
screening and captcha logic was kept free of I/O.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast

from aiogram.enums import ChatMemberStatus
from aiogram.types import ChatMemberUpdated
import pytest

from bot.modules.entry import _is_organic_leave
from core.captcha import (
    EMOJI_CHOICES,
    EMOJI_POOL,
    MATH_CHOICES,
    build,
)
from core.entry import estimate_account_age, estimate_registration, screen_account
from core.greeting import MAX_LENGTH, Html, render_greeting, uses_placeholder
from i18n.runtime import localization
from shared.enums import CaptchaKind
from shared.schemas.module_configs import EntryConfig

NOW = datetime(2026, 8, 9, tzinfo=UTC)
TIMEOUT = timedelta(minutes=5)


# --- captcha generation ---------------------------------------------------------
@pytest.mark.parametrize("kind", list(CaptchaKind))
def test_every_captcha_kind_is_answerable(kind: CaptchaKind) -> None:
    """The correct token must be among the buttons, or the captcha is unsolvable."""
    challenge = build(kind, timeout=TIMEOUT, now=NOW)
    assert challenge.kind is kind
    assert challenge.expires_at == NOW + TIMEOUT
    assert challenge.options
    assert challenge.answer in {option.token for option in challenge.options}


@pytest.mark.parametrize("kind", list(CaptchaKind))
def test_captcha_prompt_key_resolves_in_both_locales(kind: CaptchaKind) -> None:
    challenge = build(kind, timeout=TIMEOUT, now=NOW)
    for lang in ("ru", "en"):
        bundle = localization(lang)
        rendered = bundle.format_value(challenge.prompt_key, challenge.prompt_args)
        assert rendered != challenge.prompt_key, (lang, challenge.prompt_key)
        for option in challenge.options:
            if option.label_is_key:
                assert bundle.format_value(option.label) != option.label


def test_button_captcha_token_is_unguessable() -> None:
    """A fixed token would let a bot press the right button without reading it."""
    tokens = {build(CaptchaKind.BUTTON, timeout=TIMEOUT).answer for _ in range(20)}
    assert len(tokens) == 20


def test_emoji_captcha_offers_distinct_choices() -> None:
    challenge = build(CaptchaKind.EMOJI, timeout=TIMEOUT, now=NOW)
    labels = [option.label for option in challenge.options]
    assert len(labels) == EMOJI_CHOICES
    assert len(set(labels)) == EMOJI_CHOICES  # no duplicate emoji to pick between
    assert set(labels) <= set(EMOJI_POOL)
    # The prompt shows the emoji to look for, and it is one of the buttons.
    assert challenge.prompt_args["emoji"] in labels


def test_math_captcha_answer_matches_its_prompt() -> None:
    for _ in range(20):
        challenge = build(CaptchaKind.MATH, timeout=TIMEOUT, now=NOW)
        left = int(challenge.prompt_args["left"])
        right = int(challenge.prompt_args["right"])
        assert challenge.answer == str(left + right)
        assert len(challenge.options) == MATH_CHOICES
        assert len({option.token for option in challenge.options}) == MATH_CHOICES


# --- account age estimation -----------------------------------------------------
def test_registration_estimate_rises_with_the_id() -> None:
    """Telegram hands out ids in roughly ascending order; the estimate must agree."""
    dates = []
    for uid in (100_000, 200_000_000, 1_500_000_000, 5_000_000_000, 7_500_000_000):
        date = estimate_registration(uid)
        assert date is not None, uid
        dates.append(date)
    assert dates == sorted(dates)


def test_registration_estimate_extrapolates_past_the_last_anchor() -> None:
    """New ids keep arriving after the table was written; they must read as new."""
    last = estimate_registration(7_600_000_000)
    beyond = estimate_registration(9_000_000_000)
    assert last is not None and beyond is not None
    assert beyond > last


def test_registration_estimate_rejects_impossible_ids() -> None:
    assert estimate_registration(0) is None
    assert estimate_registration(-5) is None


def test_account_age_is_never_negative() -> None:
    """An id newer than `now` would otherwise produce a negative age."""
    age = estimate_account_age(9_000_000_000, now=datetime(2020, 1, 1, tzinfo=UTC))
    assert age == timedelta()


# --- join screening -------------------------------------------------------------
def _config(**kwargs: object) -> EntryConfig:
    return EntryConfig.model_validate({"autoban_new_accounts": True, **kwargs})


def test_screening_is_off_unless_the_admin_enabled_it() -> None:
    config = _config(autoban_new_accounts=False, autoban_require_username=True)
    assert not screen_account(
        tg_user_id=7_500_000_000, username=None, has_photo=False, config=config, now=NOW
    )


def test_screening_never_flags_bots() -> None:
    """A bot added by an admin has no avatar and often no age; that is not a raid."""
    config = _config(autoban_require_username=True, autoban_require_photo=True)
    assert not screen_account(
        tg_user_id=7_500_000_000,
        username=None,
        has_photo=False,
        is_bot=True,
        config=config,
        now=NOW,
    )


def test_screening_only_applies_the_checks_that_are_on() -> None:
    """An anonymous-but-photographed member must pass a photo-only rule."""
    config = _config(autoban_require_username=False, autoban_require_photo=True)
    assert not screen_account(
        tg_user_id=100_000, username=None, has_photo=True, config=config, now=NOW
    )
    flagged = screen_account(
        tg_user_id=100_000, username="bob", has_photo=False, config=config, now=NOW
    )
    assert flagged.reasons == ("entry-reason-no-photo",)


def test_screening_collects_every_reason() -> None:
    config = _config(
        autoban_require_username=True,
        autoban_require_photo=True,
        autoban_min_account_age_days=3650,
    )
    result = screen_account(
        tg_user_id=7_500_000_000, username=None, has_photo=False, config=config, now=NOW
    )
    assert set(result.reasons) == {
        "entry-reason-no-username",
        "entry-reason-no-photo",
        "entry-reason-fresh-account",
    }


def test_screening_passes_an_established_account() -> None:
    config = _config(
        autoban_require_username=True,
        autoban_require_photo=True,
        autoban_min_account_age_days=30,
    )
    assert not screen_account(
        tg_user_id=100_000, username="oldtimer", has_photo=True, config=config, now=NOW
    )


def test_every_screening_reason_resolves_in_both_locales() -> None:
    config = _config(
        autoban_require_username=True,
        autoban_require_photo=True,
        autoban_min_account_age_days=3650,
    )
    result = screen_account(
        tg_user_id=7_500_000_000, username=None, has_photo=False, config=config, now=NOW
    )
    for lang in ("ru", "en"):
        bundle = localization(lang)
        for reason in result.reasons:
            assert bundle.format_value(reason) != reason, (lang, reason)


# --- greeting rendering ---------------------------------------------------------
def test_greeting_fills_every_placeholder() -> None:
    rendered = render_greeting(
        "Hi {name}, welcome to {chat}! Rules: {rules_link}",
        name="Bob",
        chat="Devs",
        rules_link="https://example.com/rules",
    )
    assert rendered == "Hi Bob, welcome to Devs! Rules: https://example.com/rules"


def test_greeting_escapes_substituted_values() -> None:
    """A member named `<script>` must not inject markup into the admin's text."""
    rendered = render_greeting("Hello {name}", name="<script>alert(1)</script>", chat="Devs")
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered


def test_greeting_keeps_the_admins_own_markup() -> None:
    rendered = render_greeting("<b>Welcome</b>, {name}", name="Bob", chat="Devs")
    assert rendered.startswith("<b>Welcome</b>")


def test_greeting_inserts_an_html_mention_verbatim() -> None:
    mention = Html('<a href="tg://user?id=7">Bob</a>')
    rendered = render_greeting("Hi {name}", name=mention, chat="Devs")
    assert rendered == f"Hi {mention}"


def test_greeting_survives_braces_an_admin_typed() -> None:
    """`str.format` would raise on these; the replace-based renderer must not."""
    rendered = render_greeting("Welcome {name} :{ } {unknown}", name="Bob", chat="Devs")
    assert rendered == "Welcome Bob :{ } {unknown}"


def test_greeting_is_truncated_to_a_sendable_length() -> None:
    rendered = render_greeting("x" * 10_000, name="Bob", chat="Devs")
    assert len(rendered) == MAX_LENGTH


def test_uses_placeholder_detects_references() -> None:
    assert uses_placeholder("Hi {name}", "name")
    assert not uses_placeholder("Hi {name}", "rules_link")


# --- organic-leave detection ----------------------------------------------------
def _transition(
    *, was: ChatMemberStatus, now: ChatMemberStatus, is_bot: bool = False
) -> ChatMemberUpdated:
    """A `ChatMemberUpdated` stripped to the three fields `_is_organic_leave` reads."""
    return cast(
        ChatMemberUpdated,
        SimpleNamespace(
            old_chat_member=SimpleNamespace(status=was),
            new_chat_member=SimpleNamespace(status=now, user=SimpleNamespace(is_bot=is_bot)),
        ),
    )


def test_a_member_leaving_on_their_own_is_organic_churn() -> None:
    event = _transition(was=ChatMemberStatus.MEMBER, now=ChatMemberStatus.LEFT)
    assert _is_organic_leave(event)


def test_a_ban_is_not_counted_as_a_leave() -> None:
    """A KICKED transition is already an admin action in the moderation feed;
    counting it as churn too would double-count the removal and bury the
    voluntary-departure signal an owner actually reads."""
    event = _transition(was=ChatMemberStatus.MEMBER, now=ChatMemberStatus.KICKED)
    assert not _is_organic_leave(event)


def test_a_bot_leaving_is_not_member_churn() -> None:
    """Bots never counted as members, so their departure is not a leave."""
    event = _transition(was=ChatMemberStatus.MEMBER, now=ChatMemberStatus.LEFT, is_bot=True)
    assert not _is_organic_leave(event)


def test_a_join_is_not_mistaken_for_a_leave() -> None:
    event = _transition(was=ChatMemberStatus.LEFT, now=ChatMemberStatus.MEMBER)
    assert not _is_organic_leave(event)
