"""Pure-unit smoke tests: no database, no Redis, no Telegram.

Anything needing real infrastructure lives in the integration suites added in
Stage 7 and runs against testcontainers.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.engine.default import DefaultDialect

from core.anti_flood import FloodPolicy, SlidingWindowRateLimiter
from core.audit import ACTION_ICONS
from core.durations import (
    MAX_RESTRICTION,
    MIN_RESTRICTION,
    clamp_restriction,
    format_duration,
    parse_duration,
    parse_optional_duration,
)
from core.features import effective_plan, has_feature, in_grace_period
from core.registry import MODULE_SPECS, ModuleRegistry, registry
from core.stop_words import StopWordMatcher, matcher_for, normalize
from db import models
from db.base import Base
from db.types import StrEnumType
from i18n.runtime import LOCALES_DIR, localization
from shared.enums import ModuleName, Plan
from shared.errors import InvalidDurationError
from shared.plans import Feature

NOW = datetime(2026, 8, 9, tzinfo=UTC)


def _chat(**kwargs: object) -> models.Chat:
    """A detached Chat instance for testing the pure plan-resolution helpers."""
    defaults: dict[str, object] = {
        "plan": Plan.FREE,
        "plan_expires_at": None,
        "grace_until": None,
    }
    return models.Chat(**{**defaults, **kwargs})


# --- plans and features -------------------------------------------------------
def test_plan_feature_gate() -> None:
    assert has_feature(Plan.FREE, Feature.MODERATION)
    assert not has_feature(Plan.FREE, Feature.STATS)
    assert has_feature(Plan.PRO, Feature.STATS)
    assert has_feature(Plan.BUSINESS, Feature.AI_MODERATION)
    assert not has_feature(Plan.PRO, Feature.AI_MODERATION)


def test_effective_plan_keeps_paid_features_until_expiry() -> None:
    chat = _chat(plan=Plan.PRO, plan_expires_at=NOW + timedelta(days=1))
    assert effective_plan(chat, now=NOW) is Plan.PRO
    assert not in_grace_period(chat, now=NOW)


def test_effective_plan_honours_grace_window() -> None:
    chat = _chat(
        plan=Plan.PRO,
        plan_expires_at=NOW - timedelta(days=1),
        grace_until=NOW + timedelta(days=2),
    )
    assert effective_plan(chat, now=NOW) is Plan.PRO
    assert in_grace_period(chat, now=NOW)


def test_effective_plan_falls_back_to_free_after_grace() -> None:
    chat = _chat(
        plan=Plan.PRO,
        plan_expires_at=NOW - timedelta(days=5),
        grace_until=NOW - timedelta(days=1),
    )
    assert effective_plan(chat, now=NOW) is Plan.FREE
    assert not in_grace_period(chat, now=NOW)


# --- module registry ----------------------------------------------------------
def test_registry_exposes_every_declared_module() -> None:
    assert len(registry) == len(MODULE_SPECS)
    assert {spec.name for spec in registry} == set(ModuleName)


def test_registry_derives_required_plan_from_the_feature_matrix() -> None:
    assert registry.get(ModuleName.MODERATION).required_plan is Plan.FREE
    assert registry.get(ModuleName.STATS).required_plan is Plan.PRO
    assert registry.get(ModuleName.AI_MODERATION).required_plan is Plan.BUSINESS


def test_registry_filters_modules_by_plan() -> None:
    free = {spec.name.value for spec in registry.available_for_plan(Plan.FREE)}
    assert free == {"moderation", "entry"}
    assert "stats" in {spec.name.value for spec in registry.available_for_plan(Plan.PRO)}
    locked = {spec.name.value for spec in registry.locked_for_plan(Plan.PRO)}
    assert locked == {"ai_moderation", "crossban"}


def test_registry_commands_grow_with_the_plan() -> None:
    free = registry.commands_for_plan(Plan.FREE)
    business = registry.commands_for_plan(Plan.BUSINESS)
    assert {cmd.name for cmd in free} < {cmd.name for cmd in business}
    assert all(cmd.description_key for cmd in business)


def test_registry_rejects_duplicate_registration() -> None:
    local = ModuleRegistry()
    with pytest.raises(ValueError, match="already registered"):
        local.register(local.get(ModuleName.MODERATION))


def test_moderation_is_mandatory_and_on_by_default() -> None:
    spec = registry.get(ModuleName.MODERATION)
    assert spec.mandatory
    assert spec.enabled_by_default
    assert {s.name.value for s in registry.default_enabled()} == {"moderation", "entry"}


def test_module_configs_validate_to_their_declared_model() -> None:
    for spec in registry:
        assert isinstance(spec.default_config(), spec.config_model)


def test_miniapp_sections_have_unique_ordered_keys() -> None:
    sections = [spec.miniapp_section for spec in registry if spec.miniapp_section]
    assert len(sections) == len(registry)
    assert len({section.key for section in sections}) == len(sections)
    assert [s.order for s in sections] == sorted(s.order for s in sections)


# --- schema -------------------------------------------------------------------
def test_initial_schema_contains_required_entities() -> None:
    tables = Base.metadata.tables
    assert {"chats", "punishments", "payments", "chat_module_configs"} <= set(tables)
    assert tables["chats"].c.tg_chat_id.unique


def test_enum_columns_round_trip_as_enum_members() -> None:
    """`Mapped[Plan]` must not hand back a bare `str` — see `db.types`."""
    # `Column.type` is only `TypeEngine`; the round-trip hooks live on the
    # decorator, so assert the column really got ours before calling them.
    column_type = models.Chat.__table__.c.plan.type
    assert isinstance(column_type, StrEnumType)
    # The hooks take a dialect but never read it; a bare `DefaultDialect` keeps
    # the calls honest instead of sidestepping the signature with `None`.
    dialect = DefaultDialect()
    assert column_type.process_result_value("pro", dialect) is Plan.PRO
    assert column_type.process_bind_param(Plan.PRO, dialect) == "pro"
    assert column_type.process_result_value(None, dialect) is None
    # An unknown legacy value stays readable instead of breaking the query.
    assert column_type.process_result_value("legacy_tier", dialect) == "legacy_tier"


# --- durations ----------------------------------------------------------------
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("45s", timedelta(seconds=45)),
        ("30m", timedelta(minutes=30)),
        ("2h", timedelta(hours=2)),
        ("7d", timedelta(days=7)),
        ("1w", timedelta(weeks=1)),
    ],
)
def test_parse_duration(value: str, expected: timedelta) -> None:
    assert parse_duration(value) == expected


@pytest.mark.parametrize("value", ["one hour", "", "10", "5y", "-3h"])
def test_parse_duration_rejects_invalid_value(value: str) -> None:
    with pytest.raises(InvalidDurationError):
        parse_duration(value)


def test_parse_optional_duration_maps_permanent_to_none() -> None:
    assert parse_optional_duration(None) is None
    assert parse_optional_duration("2h") == timedelta(hours=2)


def test_clamp_restriction_respects_telegram_bounds() -> None:
    assert clamp_restriction(timedelta(seconds=1)) == MIN_RESTRICTION
    assert clamp_restriction(timedelta(days=9999)) is None  # permanent
    assert clamp_restriction(timedelta(hours=3)) == timedelta(hours=3)
    assert clamp_restriction(MAX_RESTRICTION) == MAX_RESTRICTION
    assert clamp_restriction(None) is None


def test_format_duration_round_trips_through_parse() -> None:
    for value in ("45s", "30m", "2h", "7d"):
        assert parse_duration(format_duration(parse_duration(value))) == parse_duration(value)


# --- stop words ---------------------------------------------------------------
def test_stop_word_matcher_is_case_insensitive() -> None:
    matcher = StopWordMatcher(["Scam", "casino"])
    assert matcher.find("This is a SCAM link") is not None
    assert matcher.find("A normal message") is None
    assert matcher.matches("visit our CASINO")


def test_stop_word_matcher_folds_homoglyphs_and_separators() -> None:
    """Spammers write "с a s i n o" with a Cyrillic с; the matcher must still catch it."""
    matcher = StopWordMatcher(["casino"])
    assert matcher.matches("сasino tonight")  # Cyrillic 'с'
    assert matcher.matches("c a s i n o")
    assert matcher.matches("c-a-s-i-n-o")
    assert matcher.matches("cAsInO")


def test_stop_word_matcher_supports_wildcards() -> None:
    matcher = StopWordMatcher(["crypt*"])
    assert matcher.matches("cheap crypto here")
    assert matcher.matches("cryptocurrency")
    assert not matcher.matches("a cryp")


def test_normalize_strips_invisible_characters() -> None:
    assert normalize("sc​am") == "scam"


def test_matcher_for_is_memoised() -> None:
    assert matcher_for(["scam"]) is matcher_for(["scam"])


def test_empty_matcher_never_matches() -> None:
    matcher = StopWordMatcher([])
    assert not matcher
    assert matcher.find("anything at all") is None


# --- anti-flood ---------------------------------------------------------------
def test_sliding_window_rate_limiter_blocks_flooding() -> None:
    limiter = SlidingWindowRateLimiter()
    policy = FloodPolicy(limit=2, window=timedelta(seconds=10))
    assert limiter.is_allowed("1:2", policy, NOW)
    assert limiter.is_allowed("1:2", policy, NOW + timedelta(seconds=1))
    assert not limiter.is_allowed("1:2", policy, NOW + timedelta(seconds=2))
    # The window slides: the first two hits have aged out by second 11.
    assert limiter.is_allowed("1:2", policy, NOW + timedelta(seconds=11))


def test_rate_limiter_keys_are_independent() -> None:
    limiter = SlidingWindowRateLimiter()
    policy = FloodPolicy(limit=1, window=timedelta(seconds=10))
    assert limiter.is_allowed("chat:1", policy, NOW)
    assert limiter.is_allowed("chat:2", policy, NOW)
    assert not limiter.is_allowed("chat:1", policy, NOW)


def test_rate_limiter_reset_clears_history() -> None:
    limiter = SlidingWindowRateLimiter()
    policy = FloodPolicy(limit=1, window=timedelta(seconds=10))
    assert limiter.is_allowed("1:2", policy, NOW)
    assert limiter.hit_count("1:2", policy.window, NOW) == 1
    limiter.reset("1:2")
    assert limiter.hit_count("1:2", policy.window, NOW) == 0
    assert limiter.is_allowed("1:2", policy, NOW)


# --- i18n ---------------------------------------------------------------------
# DECISION: these assert that a key *resolves*, not what it says. Pinning the
# exact copy made every wording change a test failure, which trains people to
# update the assertion without reading it. Fluent returns the key itself when it
# cannot resolve, so `!= key` is the real signal.
def test_fluent_localization_loads_resources() -> None:
    russian = localization("ru")
    assert russian.format_value("start-welcome") != "start-welcome"
    # Cyrillic somewhere in the string proves the ru bundle answered, not the
    # English fallback sitting behind it.
    assert any("Ѐ" <= char <= "ӿ" for char in russian.format_value("start-welcome"))
    assert russian.format_value("open-miniapp") != "open-miniapp"
    assert localization("en").format_value("start-welcome") != "start-welcome"


def test_unknown_locale_falls_back_to_english() -> None:
    german = localization("de").format_value("start-welcome")
    assert german != "start-welcome"
    assert german == localization("en").format_value("start-welcome")


def test_locales_define_the_same_keys() -> None:
    """A key present in one locale and missing in the other is a silent fallback."""
    keys = {
        lang: {
            line.split("=", 1)[0].strip()
            for line in (LOCALES_DIR / lang / "main.ftl").read_text("utf-8").splitlines()
            if "=" in line and not line.lstrip().startswith("#")
        }
        for lang in ("ru", "en")
    }
    assert keys["ru"] == keys["en"], {
        "ru_only": sorted(keys["ru"] - keys["en"]),
        "en_only": sorted(keys["en"] - keys["ru"]),
    }


def test_every_module_title_key_resolves_in_both_locales() -> None:
    for lang in ("ru", "en"):
        bundle = localization(lang)
        for spec in registry:
            assert bundle.format_value(spec.title_key) != spec.title_key, (lang, spec.title_key)
            assert bundle.format_value(spec.description_key) != spec.description_key


def test_every_command_description_key_resolves() -> None:
    bundle = localization("ru")
    for spec in registry:
        for command in spec.commands:
            assert bundle.format_value(command.description_key) != command.description_key


def test_every_audit_action_has_a_title_in_both_locales() -> None:
    """A missing key prints the raw action name (`lockdown_off`) into the log channel."""
    for lang in ("ru", "en"):
        bundle = localization(lang)
        for action in ACTION_ICONS:
            key = f"log-action-{action.replace('_', '-')}"
            assert bundle.format_value(key) != key, (lang, action)
