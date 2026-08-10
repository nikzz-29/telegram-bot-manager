"""Chat statistics — the read side of the Statistics tab.

Spec §5.5. The worker aggregates raw events into daily rollups; this router is a
thin projection of those tables. The bot's `/stats` chat command renders the same
`core.stats.overview` into a message; the Mini App gets the object it is built
from.

DECISION: the requested window is clamped to the plan's retention, exactly like
`bot.modules.stats` does for `/stats`. A Business chat asking for 365 days of a
Pro-level 90-day retention would otherwise get a sparse chart and a total that
stops early with no explanation, which reads as a bug rather than a billing
boundary. The response states the window that was actually served.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, status

from api.deps import ChatAccessDep, FeaturesDep, UowDep
from api.errors import problem_responses
from core.stats import MAX_PERIOD_DAYS, stats
from db.uow import UnitOfWork
from shared.logging import get_logger
from shared.plans import Feature
from shared.schemas.api import StatsOverview

logger = get_logger(__name__)

router = APIRouter(
    prefix="/chats/{chat_id}/stats",
    tags=["stats"],
    responses=problem_responses(
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_402_PAYMENT_REQUIRED,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
    ),
)


@router.get(
    "",
    response_model=StatsOverview,
    operation_id="getChatStats",
    summary="Activity totals, series and top users for a chat",
)
async def get_chat_stats(
    access: ChatAccessDep,
    features: FeaturesDep,
    uow: UowDep,
    days: int = Query(default=7, ge=1, le=MAX_PERIOD_DAYS, description="Window length in days"),
) -> StatsOverview:
    await features.require(access.chat_id, Feature.STATS)

    retention = (await features.limits(access.chat_id)).stats_retention_days
    if retention:
        days = min(days, retention)

    overview = await stats.overview(access.chat_id, days=days)
    await _name_top_users(overview, uow)
    logger.info(
        "api.stats_served",
        chat_id=access.chat_id,
        days=days,
        messages=overview.total_messages,
    )
    return overview


async def _name_top_users(overview: StatsOverview, uow: UnitOfWork) -> None:
    """Fill in the names behind the ids the rollups store.

    `core.stats` returns bare user ids because the bot renders a mention from
    what it already has in the update. The panel has no such context, and a
    leaderboard of `id448271` is not a leaderboard — so the profile cache is
    joined here, in one query, rather than one lookup per row.
    """
    if not overview.top_users:
        return
    profiles = await uow.users.get_many([entry.tg_user_id for entry in overview.top_users])
    for entry in overview.top_users:
        profile = profiles.get(entry.tg_user_id)
        if profile is not None:
            entry.username = profile.username
            entry.display_name = profile.display_name


__all__ = ["router"]
