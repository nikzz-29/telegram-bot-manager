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

from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Final

from aiogram.methods import SendMessage
from fastapi import APIRouter, HTTPException, Query, status

from api.deps import SuperadminDep, UowDep
from api.errors import problem_responses
from core.cache import invalidate_chat_plan
from core.crossban import crossban
from core.cryptobot import cryptobot
from core.plan_settings import install_plan_override_rows
from core.platform_settings import CRYPTOBOT_TESTNET_KEY
from core.sender import SendPriority, sender
from shared.config import get_settings
from shared.enums import PaymentProvider, PaymentStatus, Plan
from shared.errors import ResourceNotFoundError
from shared.logging import get_logger
from shared.plans import PLAN_FEATURES, PLAN_PRICES, Feature, PlanPrice
from shared.schemas.api import (
    BroadcastRequest,
    GlobalBanCreate,
    GlobalBanEntry,
    OperationResult,
    PlatformCryptoBotSettings,
    PlatformCryptoBotUpdate,
    PlatformDashboard,
    PlatformPayment,
    PlatformPaymentPage,
    PlatformPlanOverride,
    PlatformPlanOverrideResponse,
    PlatformPlanRow,
    PlatformSeriesPoint,
    PlatformSettings,
    PlatformStats,
    PlatformSubscriptionGrant,
    PlatformTotals,
    PlatformUser,
    PlatformUserChat,
    PlatformUserDetail,
    PlatformUserPage,
)
from shared.time_utils import utc_now

logger = get_logger(__name__)

DASHBOARD_PERIODS: Final = frozenset({1, 7, 30, 90, 365})

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


def _window(days: int) -> tuple[date, date]:
    today = utc_now().date()
    return today - timedelta(days=days - 1), today


@router.get(
    "/dashboard",
    response_model=PlatformDashboard,
    operation_id="getPlatformDashboard",
    summary="Platform dashboard with a selectable reporting window",
)
async def platform_dashboard(
    _: SuperadminDep,
    uow: UowDep,
    days: int = Query(default=30, ge=1, le=365),
) -> PlatformDashboard:
    if days not in DASHBOARD_PERIODS:
        raise HTTPException(status_code=422, detail="Supported periods: 1, 7, 30, 90, 365 days.")
    start, end = _window(days)
    totals = await uow.platform.totals(start=start, end=end)
    series = await uow.platform.daily_series(start=start, end=end)
    plans = await uow.platform.plan_mix(start=start, end=end)
    settings = get_settings()
    return PlatformDashboard(
        days=days,
        start=start,
        end=end,
        totals=PlatformTotals.model_validate(totals),
        series=[PlatformSeriesPoint.model_validate(point) for point in series],
        plan_mix=[PlatformPlanRow.model_validate(row) for row in plans],
        cryptobot_configured=cryptobot.configured,
        cryptobot_testnet=cryptobot.testnet,
        ai_moderation_available=settings.ai_moderation_available,
    )


@router.get(
    "/users",
    response_model=PlatformUserPage,
    operation_id="listPlatformUsers",
    summary="Search and paginate all known Telegram users",
)
async def platform_users(
    _: SuperadminDep,
    uow: UowDep,
    search: str = "",
    banned_only: bool = False,
    admins_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PlatformUserPage:
    rows, total = await uow.platform.user_page(
        search=search,
        banned_only=banned_only,
        admins_only=admins_only,
        limit=limit,
        offset=offset,
    )
    return PlatformUserPage(
        items=[PlatformUser.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/users/{tg_user_id}",
    response_model=PlatformUserDetail,
    operation_id="getPlatformUser",
    summary="Get a user and the chats they administer",
)
async def platform_user(
    tg_user_id: int, _principal: SuperadminDep, uow: UowDep
) -> PlatformUserDetail:
    rows, _total = await uow.platform.user_page(tg_user_id=tg_user_id, limit=1, offset=0)
    if not rows:
        raise ResourceNotFoundError("Telegram user is not known.")
    chats = await uow.platform.user_chats(tg_user_id)
    return PlatformUserDetail(
        user=PlatformUser.model_validate(rows[0]),
        chats=[
            PlatformUserChat(
                id=chat.id,
                tg_chat_id=chat.tg_chat_id,
                title=chat.title,
                plan=chat.plan,
                plan_expires_at=chat.plan_expires_at,
                is_active=chat.is_active,
                owner_tg_id=chat.owner_tg_id,
                members_count=chat.members_count,
            )
            for chat in chats
        ],
    )


@router.post(
    "/users/{tg_user_id}/subscription",
    response_model=OperationResult,
    operation_id="grantPlatformSubscription",
    summary="Grant a subscription to one of a user's chats",
)
async def grant_subscription(
    tg_user_id: int,
    payload: PlatformSubscriptionGrant,
    principal: SuperadminDep,
    uow: UowDep,
) -> OperationResult:
    chats = await uow.platform.user_chats(tg_user_id)
    chat = next((item for item in chats if item.id == payload.chat_id), None)
    if chat is None:
        raise ResourceNotFoundError("This chat is not administered by the user.")
    now = utc_now()
    expires = None
    if payload.plan != Plan.FREE:
        base = (
            chat.plan_expires_at
            if chat.plan == payload.plan
            and chat.plan_expires_at is not None
            and chat.plan_expires_at > now
            else now
        )
        expires = base + timedelta(days=30 * payload.months)
    await uow.chats.set_plan(chat.id, payload.plan, expires_at=expires, grace_until=None)
    await uow.commit()
    await invalidate_chat_plan(chat.id)
    logger.info(
        "platform.subscription_granted",
        operator_id=principal.tg_user_id,
        target_user_id=tg_user_id,
        chat_id=chat.id,
        plan=payload.plan.value,
        months=payload.months,
    )
    return OperationResult(ok=True, detail=expires.isoformat() if expires is not None else "")


@router.get(
    "/payments",
    response_model=PlatformPaymentPage,
    operation_id="listPlatformPayments",
    summary="List platform payments for support and reconciliation",
)
async def platform_payments(
    _: SuperadminDep,
    uow: UowDep,
    payment_status: Annotated[PaymentStatus | None, Query(alias="status")] = None,
    provider: PaymentProvider | None = None,
    tg_user_id: Annotated[int | None, Query(ge=1)] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PlatformPaymentPage:
    rows, total = await uow.platform.payment_page(
        status=payment_status,
        provider=provider,
        tg_user_id=tg_user_id,
        limit=limit,
        offset=offset,
    )
    return PlatformPaymentPage(
        items=[
            PlatformPayment(
                id=row.payment.id,
                chat_id=row.payment.chat_id,
                tg_chat_id=row.tg_chat_id,
                chat_title=row.chat_title,
                provider=row.payment.provider,
                provider_payment_id=row.payment.provider_payment_id,
                amount=row.payment.amount,
                currency=row.payment.currency,
                status=row.payment.status,
                plan=row.payment.plan,
                months=row.payment.months,
                payer_tg_id=row.payment.payer_tg_id,
                created_at=row.payment.created_at,
                period_start=row.payment.period_start,
                period_end=row.payment.period_end,
                refunded_at=row.payment.refunded_at,
                refund_reason=row.payment.refund_reason,
            )
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/settings",
    response_model=PlatformSettings,
    operation_id="getPlatformSettings",
    summary="Read deployment capabilities and operator settings",
)
async def platform_settings(_: SuperadminDep) -> PlatformSettings:
    settings = get_settings()
    providers: list[PaymentProvider] = [PaymentProvider.STARS]
    if cryptobot.configured:
        providers.append(PaymentProvider.CRYPTOBOT)
    return PlatformSettings(
        environment=settings.app_env,
        cryptobot=PlatformCryptoBotSettings(
            configured=cryptobot.configured,
            testnet=cryptobot.testnet,
            network=cryptobot.network,
        ),
        ai_moderation_available=settings.ai_moderation_available,
        payment_providers=providers,
        global_ban_chat_threshold=settings.global_ban_chat_threshold,
    )


@router.patch(
    "/settings/cryptobot",
    response_model=PlatformSettings,
    operation_id="updateCryptoBotSettings",
    summary="Switch the configured CryptoBot client between mainnet and testnet",
)
async def update_cryptobot_settings(
    payload: PlatformCryptoBotUpdate, principal: SuperadminDep, uow: UowDep
) -> PlatformSettings:
    if not cryptobot.configured:
        raise HTTPException(status_code=503, detail="CryptoBot token is not configured.")
    settings = get_settings()
    if settings.is_production and payload.testnet:
        raise HTTPException(status_code=409, detail="CryptoBot testnet is locked in production.")
    await uow.platform_settings.set(
        CRYPTOBOT_TESTNET_KEY,
        {"enabled": payload.testnet},
        updated_by=principal.tg_user_id,
    )
    await uow.commit()
    settings.cryptobot_testnet = payload.testnet
    await cryptobot.close()
    logger.warning(
        "platform.cryptobot_network_changed",
        operator_id=principal.tg_user_id,
        testnet=payload.testnet,
    )
    return await platform_settings(principal)


def _plan_override_response(plan: Plan, row: object | None) -> PlatformPlanOverrideResponse:
    price = PLAN_PRICES.get(plan, PlanPrice(stars=0, usd=""))
    return PlatformPlanOverrideResponse(
        plan=plan,
        stars=getattr(row, "stars", None),
        usd=getattr(row, "usd", None),
        features=getattr(row, "features", None),
        note=getattr(row, "note", ""),
        updated_by=getattr(row, "updated_by", None),
        updated_at=getattr(row, "updated_at", None),
        effective_stars=price.stars,
        effective_usd=price.usd,
        effective_features=sorted(feature.value for feature in PLAN_FEATURES[plan]),
    )


@router.get(
    "/plans",
    response_model=list[PlatformPlanOverrideResponse],
    operation_id="listPlatformPlans",
    summary="Read effective plan prices, features and operator overrides",
)
async def list_platform_plans(_: SuperadminDep, uow: UowDep) -> list[PlatformPlanOverrideResponse]:
    rows = {row.plan: row for row in await uow.plan_overrides.list_all()}
    return [_plan_override_response(plan, rows.get(plan)) for plan in Plan]


@router.put(
    "/plans/{plan}",
    response_model=PlatformPlanOverrideResponse,
    operation_id="updatePlatformPlan",
    summary="Override a plan's price and feature set",
)
async def update_platform_plan(
    plan: Plan,
    payload: PlatformPlanOverride,
    principal: SuperadminDep,
    uow: UowDep,
) -> PlatformPlanOverrideResponse:
    try:
        features = (
            None if payload.features is None else [Feature(value) for value in payload.features]
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=f"Unknown feature: {error}") from error
    row = await uow.plan_overrides.save(
        plan,
        stars=payload.stars,
        usd=payload.usd,
        features=payload.features,
        updated_by=principal.tg_user_id,
        note=payload.note,
    )
    if payload.stars is not None or payload.usd is not None:
        current = PLAN_PRICES.get(plan, PlanPrice(stars=0, usd=""))
        PLAN_PRICES[plan] = PlanPrice(
            stars=payload.stars if payload.stars is not None else current.stars,
            usd=payload.usd if payload.usd is not None else current.usd,
        )
    if features is not None:
        PLAN_FEATURES[plan] = frozenset(features)
    await uow.commit()
    install_plan_override_rows(await uow.plan_overrides.list_all())
    return _plan_override_response(plan, row)


@router.delete(
    "/plans/{plan}",
    response_model=PlatformPlanOverrideResponse,
    operation_id="resetPlatformPlan",
    summary="Reset one plan to the values shipped with the application",
)
async def reset_platform_plan(
    plan: Plan, principal: SuperadminDep, uow: UowDep
) -> PlatformPlanOverrideResponse:
    await uow.plan_overrides.delete(plan)
    await uow.commit()
    install_plan_override_rows(await uow.plan_overrides.list_all())
    logger.info(
        "platform.plan_reset",
        operator_id=principal.tg_user_id,
        plan=plan.value,
    )
    return _plan_override_response(plan, None)


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
    if payload.tg_user_id == principal.tg_user_id:
        raise HTTPException(status_code=409, detail="A superadmin cannot ban their own account.")
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
