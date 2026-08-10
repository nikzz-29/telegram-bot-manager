"""The operator panel: platform totals, the blacklist, and broadcasts.

Spec §5.9. Everything here hangs off `SuperadminDep`, so the whole router is
unreachable without an account on `SUPERADMIN_IDS` — there is no per-chat access
check anywhere below, because none of these endpoints is about one chat.

DECISION: the blacklist endpoints go through `core.crossban`, not the repository.
The service is what invalidates the gate's cache on promotion, and a panel ban
that took five minutes to take effect would be a support ticket every time. The
router's only job is authorization and shape.

DECISION: a broadcast is queued, never sent inline. It fans out to every chat on
the selected plans, and doing that inside a request would hold the connection
open for minutes and lose the remainder to any timeout. `MessageSender` already
owns the rate limit, so the endpoint returns as soon as the work is handed over.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Final

from aiogram.methods import SendMessage
from fastapi import APIRouter, status

from api.deps import SuperadminDep, UowDep
from api.errors import problem_responses
from core.crossban import crossban
from core.sender import SendPriority, sender
from shared.enums import Plan
from shared.errors import ResourceNotFoundError
from shared.logging import get_logger
from shared.schemas.api import (
    BroadcastRequest,
    GlobalBanCreate,
    GlobalBanEntry,
    OperationResult,
    PlatformStats,
)
from shared.time_utils import utc_now

logger = get_logger(__name__)

# The dashboard quotes a rolling window rather than all-time: "revenue" that only
# ever goes up says nothing about whether the platform is growing.
REVENUE_WINDOW: Final = timedelta(days=30)

# Currencies `payments.revenue_since` groups by, mapped onto the two totals the
# dashboard shows. Anything else is summed into the fiat column.
STARS_CURRENCY: Final = "XTR"

router = APIRouter(
    prefix="/platform",
    tags=["platform"],
    responses=problem_responses(
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
    ),
)


@router.get(
    "/stats",
    response_model=PlatformStats,
    operation_id="getPlatformStats",
    summary="Platform-wide totals for the operator dashboard",
)
async def platform_stats(_: SuperadminDep, uow: UowDep) -> PlatformStats:
    revenue = await uow.payments.revenue_since(utc_now() - REVENUE_WINDOW)
    fiat = sum(
        (amount for currency, amount in revenue.items() if currency != STARS_CURRENCY),
        Decimal(0),
    )
    return PlatformStats(
        total_chats=await uow.chats.count(),
        active_chats=await uow.chats.count(active_only=True),
        chats_by_plan=await uow.chats.count_by_plan(),
        revenue_stars=int(revenue.get(STARS_CURRENCY, Decimal(0))),
        revenue_usd=fiat,
        global_bans=await uow.global_bans.count_active(),
    )


@router.get(
    "/bans",
    response_model=list[GlobalBanEntry],
    operation_id="listGlobalBans",
    summary="The cross-ban blacklist",
)
async def list_bans(
    _: SuperadminDep, uow: UowDep, active_only: bool = True, limit: int = 200
) -> list[GlobalBanEntry]:
    entries = await uow.global_bans.list_all(active_only=active_only, limit=limit)
    return [GlobalBanEntry.model_validate(entry) for entry in entries]


@router.post(
    "/bans",
    response_model=GlobalBanEntry,
    status_code=status.HTTP_201_CREATED,
    operation_id="createGlobalBan",
    summary="Blacklist a user platform-wide",
)
async def create_ban(
    payload: GlobalBanCreate, principal: SuperadminDep, uow: UowDep
) -> GlobalBanEntry:
    """Promote immediately — an operator pressing this button *is* the decision."""
    await crossban.promote(
        tg_user_id=payload.tg_user_id,
        reason=payload.reason,
        banned_by=principal.tg_user_id,
    )
    logger.info(
        "platform.ban_created",
        tg_user_id=payload.tg_user_id,
        operator_id=principal.tg_user_id,
    )
    entry = await uow.global_bans.get(payload.tg_user_id)
    if entry is None:
        # Only reachable if something purged the row between the write and this
        # read. Rare, but it is a real outcome and not an invariant to assert on.
        raise ResourceNotFoundError("The global ban was removed before it could be read back.")
    return GlobalBanEntry.model_validate(entry)


@router.delete(
    "/bans/{tg_user_id}",
    response_model=OperationResult,
    operation_id="revokeGlobalBan",
    summary="Lift a global ban on appeal",
)
async def revoke_ban(tg_user_id: int, principal: SuperadminDep) -> OperationResult:
    revoked = await crossban.revoke(tg_user_id)
    logger.info(
        "platform.ban_revoked",
        tg_user_id=tg_user_id,
        operator_id=principal.tg_user_id,
        found=revoked,
    )
    return OperationResult(ok=revoked, detail="" if revoked else "not_listed")


@router.post(
    "/broadcast",
    response_model=OperationResult,
    operation_id="sendBroadcast",
    summary="Announce something to every chat on the selected plans",
)
async def broadcast(
    payload: BroadcastRequest, principal: SuperadminDep, uow: UowDep
) -> OperationResult:
    plans = payload.plans or list(Plan)
    chats = await uow.chats.list_by_plans(plans)
    for chat in chats:
        # BROADCAST is the sender's lowest band: an announcement must never
        # delay a ban that is racing a spam run.
        sender.enqueue(
            SendMessage(chat_id=chat.tg_chat_id, text=payload.text),
            chat_id=chat.tg_chat_id,
            priority=SendPriority.BROADCAST,
        )
    logger.info(
        "platform.broadcast",
        operator_id=principal.tg_user_id,
        chats=len(chats),
        plans=[plan.value for plan in plans],
    )
    return OperationResult(ok=True, detail=str(len(chats)))


__all__ = ["router"]
