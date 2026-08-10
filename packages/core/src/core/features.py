"""Plan resolution and feature gating.

``await features.has(chat_id, Feature.STATS)`` is the single gate every module
asks before doing paid work. Resolution is cached in Redis and invalidated on
plan change, so the hot path costs one Redis GET.

The plan stored on the row is not automatically the plan in force: an expired
subscription keeps its features until ``grace_until`` passes, then falls back to
Free. That rule lives in `effective_plan` and nowhere else.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from core import cache
from db.models import Chat
from db.uow import UnitOfWork
from shared.enums import Plan, plan_rank
from shared.errors import FeatureLockedError, LimitExceededError
from shared.plans import (
    PLAN_FEATURES,
    Feature,
    PlanLimits,
    limits_for_plan,
    minimum_plan_for,
)
from shared.time_utils import utc_now


def has_feature(plan: Plan, feature: Feature) -> bool:
    """Pure gate: does this plan include this feature?"""
    return feature in PLAN_FEATURES[plan]


def effective_plan(chat: Chat, *, now: datetime | None = None) -> Plan:
    """The plan actually in force for a chat.

    DECISION: grace is checked before expiry so a chat inside its grace window
    keeps working even though `plan_expires_at` is already in the past — that is
    the whole point of the window, and it must not depend on cron having run.
    """
    if chat.plan == Plan.FREE:
        return Plan.FREE
    moment = now or utc_now()
    if chat.plan_expires_at is None:
        return chat.plan
    if chat.plan_expires_at > moment:
        return chat.plan
    if chat.grace_until is not None and chat.grace_until > moment:
        return chat.plan
    return Plan.FREE


def in_grace_period(chat: Chat, *, now: datetime | None = None) -> bool:
    """True when the paid window has lapsed but grace has not."""
    if chat.plan == Plan.FREE or chat.plan_expires_at is None:
        return False
    moment = now or utc_now()
    if chat.plan_expires_at > moment:
        return False
    return chat.grace_until is not None and chat.grace_until > moment


class FeatureService:
    """Cached plan/feature lookups.

    DECISION: the service opens its own short-lived session on a cache miss
    instead of borrowing a caller's session. That keeps it usable as a
    process-wide singleton from bot middlewares, API dependencies and worker
    jobs alike, and cache hits — the overwhelming majority — touch no database
    at all.
    """

    def __init__(self, uow_factory: Callable[[], UnitOfWork] | None = None) -> None:
        self._uow_factory = uow_factory or UnitOfWork

    async def plan(self, chat_id: int) -> Plan:
        cached = await cache.get_value(cache.plan_key(chat_id))
        if isinstance(cached, str):
            return Plan(cached)
        plan = await self._load_plan(chat_id)
        await cache.set_value(
            cache.plan_key(chat_id),
            plan.value,
            ttl=cache.TTL_PLAN,
            tags=(cache.chat_tag(chat_id),),
        )
        return plan

    async def _load_plan(self, chat_id: int) -> Plan:
        async with self._uow_factory() as uow:
            chat = await uow.chats.get_by_id(chat_id)
            if chat is None:
                return Plan.FREE
            return effective_plan(chat)

    async def features(self, chat_id: int) -> frozenset[Feature]:
        cached = await cache.get_value(cache.features_key(chat_id))
        if isinstance(cached, list):
            return frozenset(Feature(item) for item in cached)
        plan = await self.plan(chat_id)
        resolved = PLAN_FEATURES[plan]
        await cache.set_value(
            cache.features_key(chat_id),
            sorted(feature.value for feature in resolved),
            ttl=cache.TTL_FEATURES,
            tags=(cache.chat_tag(chat_id),),
        )
        return resolved

    async def has(self, chat_id: int, feature: Feature) -> bool:
        return feature in await self.features(chat_id)

    async def require(self, chat_id: int, feature: Feature) -> None:
        """Raise `FeatureLockedError` (HTTP 402) when the plan does not cover it."""
        if not await self.has(chat_id, feature):
            raise FeatureLockedError(
                f"Feature '{feature.value}' requires the {minimum_plan_for(feature).value} plan.",
                feature=feature.value,
                required_plan=minimum_plan_for(feature).value,
            )

    async def limits(self, chat_id: int) -> PlanLimits:
        return limits_for_plan(await self.plan(chat_id))

    async def check_quota(self, chat_id: int, resource: str, current: int) -> None:
        """Raise `LimitExceededError` when adding one more would breach the plan quota."""
        limits = await self.limits(chat_id)
        allowed = int(getattr(limits, resource))
        if current >= allowed:
            raise LimitExceededError(
                f"Plan allows {allowed} {resource}; {current} already exist.",
                resource=resource,
                limit=allowed,
                current=current,
            )

    async def at_least(self, chat_id: int, plan: Plan) -> bool:
        return plan_rank(await self.plan(chat_id)) >= plan_rank(plan)

    async def invalidate(self, chat_id: int) -> None:
        await cache.invalidate_chat_plan(chat_id)


features = FeatureService()

__all__ = [
    "Feature",
    "FeatureService",
    "PlanLimits",
    "effective_plan",
    "features",
    "has_feature",
    "in_grace_period",
]
