"""Reputation and levels — the leaderboard behind the Engagement section.

Spec §5.6. Points are earned in the chat (a thanks keyword, a `+` reply) and
levels follow from activity; nothing here awards them. This router is the read
side the panel draws, plus the one write an admin genuinely needs: correcting a
score that was farmed.

DECISION: the leaderboard is served from the same `top` query the `/top` command
uses, but with the profile cache joined in. The bot renders a mention from the
update it already has; the panel has no such context, and a table of bare user
ids is not a leaderboard.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from api.deps import ChatAccessDep, FeaturesDep, UowDep
from api.errors import problem_responses
from db.uow import UnitOfWork
from shared.errors import ResourceNotFoundError
from shared.logging import get_logger
from shared.plans import Feature
from shared.schemas.api import ReputationAdjust, ReputationEntry

logger = get_logger(__name__)

router = APIRouter(
    prefix="/chats/{chat_id}/reputation",
    tags=["reputation"],
    responses=problem_responses(
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_402_PAYMENT_REQUIRED,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
    ),
)

UserIdPath = Annotated[int, Path(description="Telegram user id.")]

# What `field` may order by — the repository maps anything else onto `points`
# silently, and a typo answering with the wrong board is worse than a 422.
ORDER_FIELDS = ("points", "experience", "weekly_points", "monthly_points")
OrderBy = Annotated[str, Query(pattern="^(points|experience|weekly_points|monthly_points)$")]


async def _entries(uow: UnitOfWork, rows: list[tuple[int, int, int]]) -> list[ReputationEntry]:
    """Attach cached profiles to `(tg_user_id, points, level)` rows, in one query."""
    profiles = await uow.users.get_many([tg_user_id for tg_user_id, _, _ in rows])
    entries = []
    for tg_user_id, points, level in rows:
        profile = profiles.get(tg_user_id)
        entries.append(
            ReputationEntry(
                tg_user_id=tg_user_id,
                points=points,
                level=level,
                username=profile.username if profile else None,
                display_name=profile.display_name if profile else None,
            )
        )
    return entries


@router.get(
    "",
    response_model=list[ReputationEntry],
    operation_id="listReputation",
    summary="Reputation leaderboard for a chat",
)
async def list_reputation(
    access: ChatAccessDep,
    features: FeaturesDep,
    uow: UowDep,
    limit: int = Query(default=25, ge=1, le=100),
    order_by: OrderBy = "points",
) -> list[ReputationEntry]:
    await features.require(access.chat_id, Feature.REPUTATION)
    rows = await uow.reputation.top(access.chat_id, limit=limit, field=order_by)
    return await _entries(uow, [(row.tg_user_id, row.points, row.level) for row in rows])


@router.get(
    "/{tg_user_id}",
    response_model=ReputationEntry,
    operation_id="getReputation",
    summary="One member's reputation and level",
)
async def get_reputation(
    tg_user_id: UserIdPath,
    access: ChatAccessDep,
    features: FeaturesDep,
    uow: UowDep,
) -> ReputationEntry:
    await features.require(access.chat_id, Feature.REPUTATION)
    row = await uow.reputation.get(access.chat_id, tg_user_id)
    if row is None:
        raise ResourceNotFoundError("This member has no reputation yet.", tg_user_id=tg_user_id)
    entries = await _entries(uow, [(row.tg_user_id, row.points, row.level)])
    return entries[0]


@router.post(
    "/{tg_user_id}/adjust",
    response_model=ReputationEntry,
    operation_id="adjustReputation",
    summary="Add to or subtract from a member's reputation",
)
async def adjust_reputation(
    tg_user_id: UserIdPath,
    payload: ReputationAdjust,
    access: ChatAccessDep,
    features: FeaturesDep,
    uow: UowDep,
) -> ReputationEntry:
    """A relative delta, not an absolute score.

    DECISION: the panel sends `+5`/`-5` rather than the new total. Two admins
    correcting the same farmed score at once would otherwise overwrite each
    other; a delta applied by the database composes, whichever order it lands in.
    """
    await features.require(access.chat_id, Feature.REPUTATION)
    row = await uow.reputation.add_points(
        chat_id=access.chat_id, tg_user_id=tg_user_id, delta=payload.delta
    )
    await uow.commit()

    logger.info(
        "api.reputation_adjusted",
        chat_id=access.chat_id,
        tg_user_id=tg_user_id,
        delta=payload.delta,
        points=row.points,
        by=access.principal.tg_user_id,
    )
    entries = await _entries(uow, [(row.tg_user_id, row.points, row.level)])
    return entries[0]


__all__ = ["ORDER_FIELDS", "router"]
