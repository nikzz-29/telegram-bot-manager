"""Per-module configuration models.

DECISION: defaults live in these Pydantic models (never in the DB schema), so a
chat row with an empty JSONB config is always valid and new options roll out
without a migration.
"""

from __future__ import annotations

from typing import Annotated, Any, Final

from pydantic import BaseModel, ConfigDict, Field, field_validator

from shared.enums import (
    AiVerdictLabel,
    AutobanAction,
    CaptchaKind,
    ModerationAction,
    WarnPunishment,
)
from shared.plans import (
    DEFAULT_CAPTCHA_TIMEOUT_MINUTES,
    DEFAULT_MUTE_HOURS,
    DEFAULT_WARN_LIFETIME_DAYS,
    DEFAULT_WARN_LIMIT,
    STOP_WORD_PRESETS,
)


class ModuleConfig(BaseModel):
    """Base for all module configs: strict, no unknown keys silently kept."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ContentFilters(ModuleConfig):
    """Each switch deletes the matching message type when enabled."""

    links: bool = False
    mentions: bool = False
    forwards: bool = False
    photos: bool = False
    videos: bool = False
    gifs: bool = False
    stickers: bool = False
    voices: bool = False
    video_notes: bool = False
    documents: bool = False
    channel_senders: bool = False

    @property
    def any_enabled(self) -> bool:
        return any(self.model_dump().values())


class ModerationConfig(ModuleConfig):
    warn_limit: int = Field(default=DEFAULT_WARN_LIMIT, ge=1, le=20)
    warn_punishment: WarnPunishment = WarnPunishment.MUTE
    warn_punishment_hours: int = Field(default=DEFAULT_MUTE_HOURS, ge=1, le=8_760)
    warn_lifetime_days: int = Field(default=DEFAULT_WARN_LIFETIME_DAYS, ge=1, le=365)

    stop_words: list[str] = Field(default_factory=list)
    stop_word_presets: list[str] = Field(default_factory=list)
    stop_word_action: ModerationAction = ModerationAction.DELETE
    stop_word_mute_hours: int = Field(default=1, ge=1, le=8_760)

    filters: ContentFilters = Field(default_factory=ContentFilters)
    filter_action: ModerationAction = ModerationAction.DELETE

    anti_flood_enabled: bool = True
    anti_flood_messages: int = Field(default=8, ge=2, le=100)
    anti_flood_seconds: int = Field(default=10, ge=1, le=600)
    anti_flood_mute_minutes: int = Field(default=10, ge=1, le=10_080)
    anti_flood_media_messages: int = Field(default=4, ge=1, le=100)
    anti_flood_media_seconds: int = Field(default=15, ge=1, le=600)

    log_channel_id: int | None = None
    delete_service_messages: bool = False
    exempt_admins: bool = True

    @field_validator("stop_word_presets")
    @classmethod
    def _known_presets(cls, value: list[str]) -> list[str]:
        unknown = [preset for preset in value if preset not in STOP_WORD_PRESETS]
        if unknown:
            raise ValueError(f"Unknown stop-word presets: {', '.join(sorted(unknown))}")
        return value

    @field_validator("stop_words")
    @classmethod
    def _clean_words(cls, value: list[str]) -> list[str]:
        cleaned = {word.strip().lower() for word in value if word.strip()}
        return sorted(cleaned)


class EntryConfig(ModuleConfig):
    captcha_enabled: bool = False
    captcha_kind: CaptchaKind = CaptchaKind.BUTTON
    captcha_timeout_minutes: int = Field(default=DEFAULT_CAPTCHA_TIMEOUT_MINUTES, ge=1, le=60)
    captcha_kick_on_timeout: bool = True

    greeting_enabled: bool = False
    greeting_text: str = Field(default="", max_length=4_000)
    greeting_media_file_id: str | None = None
    greeting_buttons: list[InlineButton] = Field(default_factory=list)
    greeting_delete_after_minutes: int = Field(default=0, ge=0, le=1_440)
    rules_link: str = ""

    autoban_new_accounts: bool = False
    autoban_require_username: bool = False
    autoban_require_photo: bool = False
    autoban_min_account_age_days: int = Field(default=0, ge=0, le=3_650)
    # What a flagged account gets. `CAPTCHA` issues a challenge even in a chat
    # where the captcha is otherwise off — the spec's "extra captcha" branch.
    autoban_action: AutobanAction = AutobanAction.CAPTCHA

    anti_raid_enabled: bool = False
    anti_raid_joins: int = Field(default=10, ge=2, le=200)
    anti_raid_seconds: int = Field(default=30, ge=5, le=3_600)
    anti_raid_lockdown_minutes: int = Field(default=15, ge=1, le=1_440)

    forced_subscription_enabled: bool = False
    forced_subscription_channel_id: int | None = None
    forced_subscription_channel_url: str = ""


class InlineButton(ModuleConfig):
    text: str = Field(min_length=1, max_length=64)
    url: str = Field(min_length=1, max_length=2_048)


class StatsConfig(ModuleConfig):
    track_messages: bool = True
    track_joins: bool = True
    daily_report_enabled: bool = False
    weekly_report_enabled: bool = False
    report_hour_utc: int = Field(default=9, ge=0, le=23)
    timezone: str = "UTC"


class EngagementConfig(ModuleConfig):
    reputation_enabled: bool = False
    reputation_keywords: list[str] = Field(default_factory=lambda: ["+", "спасибо", "thanks"])
    reputation_daily_limit: int = Field(default=10, ge=1, le=1_000)
    reputation_cooldown_seconds: int = Field(default=60, ge=0, le=86_400)

    levels_enabled: bool = False
    points_per_message: int = Field(default=1, ge=0, le=100)
    level_titles: dict[str, str] = Field(default_factory=dict)

    triggers_enabled: bool = False


class AutopostConfig(ModuleConfig):
    enabled: bool = False
    timezone: str = "UTC"


# The keys either AI map may carry, named in the schema so the panel knows which
# rows to draw — it generates one per key, and Pydantic on its own would emit a
# `$ref` to the whole enum, `ok` included.
#
# `ok` is left out on purpose. `AiModerationService._action_for` returns `NOTHING`
# for a non-actionable verdict before it consults either map, so an `ok` entry
# cannot change an outcome; on screen it would be a threshold that does nothing
# whatever it is set to.
_VERDICT_KEYS: Final[dict[str, Any]] = {
    "propertyNames": {
        "enum": [label.value for label in AiVerdictLabel if label is not AiVerdictLabel.OK]
    }
}

# A confidence, on the same 0–1 scale `parse_verdict` clamps the model's answer
# to. Spelled on the value type so it reaches `additionalProperties` in the JSON
# Schema, which is where the panel looks for a numeric field's bounds — left
# unbounded, the form accepted `50` for a threshold no verdict could ever clear.
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class AiModerationConfig(ModuleConfig):
    enabled: bool = False
    sample_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    min_text_length: int = Field(default=12, ge=1, le=4_000)
    thresholds: dict[AiVerdictLabel, Confidence] = Field(
        default_factory=lambda: {
            AiVerdictLabel.TOXIC: 0.85,
            AiVerdictLabel.HIDDEN_AD: 0.80,
            AiVerdictLabel.SCAM: 0.75,
        },
        json_schema_extra=_VERDICT_KEYS,
    )
    actions: dict[AiVerdictLabel, ModerationAction] = Field(
        default_factory=lambda: {
            AiVerdictLabel.TOXIC: ModerationAction.ALERT_ADMINS,
            AiVerdictLabel.HIDDEN_AD: ModerationAction.DELETE,
            AiVerdictLabel.SCAM: ModerationAction.DELETE_WARN,
        },
        json_schema_extra=_VERDICT_KEYS,
    )
    alert_chat_id: int | None = None

    @field_validator("thresholds", "actions")
    @classmethod
    def _drop_inert_ok(cls, value: dict[AiVerdictLabel, Any]) -> dict[AiVerdictLabel, Any]:
        """Normalise away an `ok` key rather than keep a setting with no effect."""
        return {
            label: setting for label, setting in value.items() if label is not AiVerdictLabel.OK
        }


class CrossbanConfig(ModuleConfig):
    enabled: bool = False
    autoban_on_join: bool = True
    alert_only: bool = False
    contribute_bans: bool = True


CONFIG_MODELS: dict[str, type[ModuleConfig]] = {
    "moderation": ModerationConfig,
    "entry": EntryConfig,
    "stats": StatsConfig,
    "engagement": EngagementConfig,
    "autopost": AutopostConfig,
    "ai_moderation": AiModerationConfig,
    "crossban": CrossbanConfig,
}

# EntryConfig references InlineButton before its definition; resolve the forward ref.
EntryConfig.model_rebuild()


__all__ = [
    "CONFIG_MODELS",
    "AiModerationConfig",
    "AutopostConfig",
    "ContentFilters",
    "CrossbanConfig",
    "EngagementConfig",
    "EntryConfig",
    "InlineButton",
    "ModerationConfig",
    "ModuleConfig",
    "StatsConfig",
]
