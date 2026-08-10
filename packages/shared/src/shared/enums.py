"""Shared enumerations used across bot, API and worker."""

from enum import StrEnum


class Plan(StrEnum):
    FREE = "free"
    PRO = "pro"
    BUSINESS = "business"
    WHITE_LABEL = "white_label"


PLAN_ORDER: tuple[Plan, ...] = (Plan.FREE, Plan.PRO, Plan.BUSINESS, Plan.WHITE_LABEL)


def plan_rank(plan: Plan) -> int:
    """Return the ordinal weight of a plan; higher means more capable."""
    return PLAN_ORDER.index(plan)


class ChatType(StrEnum):
    GROUP = "group"
    SUPERGROUP = "supergroup"
    CHANNEL = "channel"


class PunishmentType(StrEnum):
    MUTE = "mute"
    BAN = "ban"
    KICK = "kick"
    WARN = "warn"


class ModerationAction(StrEnum):
    """What to do with a message that tripped a filter."""

    NOTHING = "nothing"
    DELETE = "delete"
    DELETE_WARN = "delete_warn"
    DELETE_MUTE = "delete_mute"
    ALERT_ADMINS = "alert_admins"


class WarnPunishment(StrEnum):
    """Punishment applied once the warn limit is reached."""

    MUTE = "mute"
    BAN = "ban"
    KICK = "kick"


class CaptchaKind(StrEnum):
    BUTTON = "button"
    EMOJI = "emoji"
    MATH = "math"


class AutobanAction(StrEnum):
    """What to do with a joining account that fails the new-account screen.

    Spec §5.2 offers the admin "either a ban or an extra captcha". `CAPTCHA` is
    the default: the screen rests on heuristics — no avatar, no username, an id
    that *looks* new — and none of them is strong enough on its own to justify
    bouncing a real person who simply has not filled in their profile.
    """

    CAPTCHA = "captcha"
    BAN = "ban"


class TriggerMatch(StrEnum):
    EXACT = "exact"
    CONTAINS = "contains"
    REGEX = "regex"


class ScheduleKind(StrEnum):
    ONCE = "once"
    DAILY = "daily"
    CRON = "cron"


class PaymentProvider(StrEnum):
    STARS = "stars"
    CRYPTOBOT = "cryptobot"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"


class AiVerdictLabel(StrEnum):
    OK = "ok"
    TOXIC = "toxic"
    HIDDEN_AD = "hidden_ad"
    SCAM = "scam"


class StatEventType(StrEnum):
    MESSAGE = "message"
    JOIN = "join"
    LEAVE = "leave"
    MODERATION = "moderation"
    CAPTCHA_PASSED = "captcha_passed"
    CAPTCHA_FAILED = "captcha_failed"
    AI_CHECK = "ai_check"


class ModuleName(StrEnum):
    """Registry keys for pluggable bot modules."""

    MODERATION = "moderation"
    ENTRY = "entry"
    STATS = "stats"
    ENGAGEMENT = "engagement"
    AUTOPOST = "autopost"
    AI_MODERATION = "ai_moderation"
    CROSSBAN = "crossban"


# NOTE: outbound queue priority lives in `core.sender.SendPriority` (an IntEnum,
# because the priority queue orders on it). Two enums of the same name would be
# a trap, so there is deliberately no send-priority enum here.


class AdminRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
