"""Plan matrix, per-plan quotas and pricing.

Single source of truth for feature gating; the API exposes it to the Mini App
so the paywall UI never hard-codes plan rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from shared.enums import Plan


class Feature(StrEnum):
    """Gate keys checked via `features.has(chat_id, Feature.X)`."""

    MODERATION = "moderation"
    CAPTCHA = "captcha"
    GREETING = "greeting"
    STOP_WORDS = "stop_words"
    ANTI_FLOOD = "anti_flood"
    LOG_CHANNEL = "log_channel"
    ANTI_RAID = "anti_raid"

    STATS = "stats"
    TRIGGERS = "triggers"
    AUTOPOST = "autopost"
    REPUTATION = "reputation"
    LEVELS = "levels"
    FORCED_SUBSCRIPTION = "forced_subscription"

    AI_MODERATION = "ai_moderation"
    CROSSBAN = "crossban"
    CHAT_NETWORKS = "chat_networks"
    PRIORITY_SUPPORT = "priority_support"

    WHITE_LABEL = "white_label"


FREE_FEATURES: frozenset[Feature] = frozenset(
    {
        Feature.MODERATION,
        Feature.CAPTCHA,
        Feature.GREETING,
        Feature.STOP_WORDS,
        Feature.ANTI_FLOOD,
        Feature.LOG_CHANNEL,
        Feature.ANTI_RAID,
    }
)

PRO_FEATURES: frozenset[Feature] = FREE_FEATURES | frozenset(
    {
        Feature.STATS,
        Feature.TRIGGERS,
        Feature.AUTOPOST,
        Feature.REPUTATION,
        Feature.LEVELS,
        Feature.FORCED_SUBSCRIPTION,
    }
)

BUSINESS_FEATURES: frozenset[Feature] = PRO_FEATURES | frozenset(
    {
        Feature.AI_MODERATION,
        Feature.CROSSBAN,
        Feature.CHAT_NETWORKS,
        Feature.PRIORITY_SUPPORT,
    }
)

WHITE_LABEL_FEATURES: frozenset[Feature] = BUSINESS_FEATURES | frozenset({Feature.WHITE_LABEL})

PLAN_FEATURES: dict[Plan, frozenset[Feature]] = {
    Plan.FREE: FREE_FEATURES,
    Plan.PRO: PRO_FEATURES,
    Plan.BUSINESS: BUSINESS_FEATURES,
    Plan.WHITE_LABEL: WHITE_LABEL_FEATURES,
}


@dataclass(frozen=True, slots=True)
class PlanLimits:
    """Hard quotas enforced before a resource is created."""

    triggers: int
    scheduled_posts: int
    stop_words: int
    ai_checks_per_day: int
    stats_retention_days: int


PLAN_LIMITS: dict[Plan, PlanLimits] = {
    Plan.FREE: PlanLimits(
        triggers=0,
        scheduled_posts=0,
        stop_words=100,
        ai_checks_per_day=0,
        stats_retention_days=0,
    ),
    Plan.PRO: PlanLimits(
        triggers=50,
        scheduled_posts=20,
        stop_words=1_000,
        ai_checks_per_day=0,
        stats_retention_days=90,
    ),
    Plan.BUSINESS: PlanLimits(
        triggers=500,
        scheduled_posts=200,
        stop_words=10_000,
        ai_checks_per_day=20_000,
        stats_retention_days=365,
    ),
    Plan.WHITE_LABEL: PlanLimits(
        triggers=5_000,
        scheduled_posts=2_000,
        stop_words=100_000,
        ai_checks_per_day=200_000,
        stats_retention_days=730,
    ),
}


@dataclass(frozen=True, slots=True)
class PlanPrice:
    """Monthly price per plan. Stars are integer XTR; crypto is USD."""

    stars: int
    usd: str


PLAN_PRICES: dict[Plan, PlanPrice] = {
    Plan.PRO: PlanPrice(stars=299, usd="4.99"),
    Plan.BUSINESS: PlanPrice(stars=999, usd="14.99"),
    Plan.WHITE_LABEL: PlanPrice(stars=4_999, usd="79.00"),
}

PURCHASABLE_PLANS: tuple[Plan, ...] = (Plan.PRO, Plan.BUSINESS, Plan.WHITE_LABEL)

# Stop-word presets shipped with the product; chats opt in by key.
STOP_WORD_PRESETS: dict[str, tuple[str, ...]] = {
    "profanity_ru": (
        "бля",
        "сука",
        "хуй",
        "пизд",
        "ебан",
        "еба",
        "мудак",
        "гандон",
        "пидор",
        "долбоеб",
    ),
    "profanity_en": (
        "fuck",
        "shit",
        "bitch",
        "asshole",
        "bastard",
        "cunt",
        "dickhead",
        "motherfucker",
    ),
    "crypto_scam": (
        "airdrop",
        "seed phrase",
        "сид фраза",
        "приватный ключ",
        "private key",
        "gift nft",
        "double your",
        "удвоим ваш",
        "инвестиции под",
        "гарантированный доход",
        "pump signal",
        "insider pump",
    ),
    "casino": (
        "casino",
        "казино",
        "ставки",
        "букмекер",
        "1xbet",
        "betting",
        "free spins",
        "фриспины",
        "промокод на депозит",
    ),
}

DEFAULT_WARN_LIMIT = 3
DEFAULT_WARN_LIFETIME_DAYS = 30
DEFAULT_MUTE_HOURS = 12
DEFAULT_CAPTCHA_TIMEOUT_MINUTES = 5
GRACE_PERIOD_DAYS = 3
SUBSCRIPTION_PERIOD_DAYS = 30


def features_for_plan(plan: Plan) -> frozenset[Feature]:
    return PLAN_FEATURES[plan]


def limits_for_plan(plan: Plan) -> PlanLimits:
    return PLAN_LIMITS[plan]


def minimum_plan_for(feature: Feature) -> Plan:
    """Cheapest plan that unlocks a feature — used to render upgrade prompts."""
    for plan in (Plan.FREE, Plan.PRO, Plan.BUSINESS, Plan.WHITE_LABEL):
        if feature in PLAN_FEATURES[plan]:
            return plan
    return Plan.WHITE_LABEL
