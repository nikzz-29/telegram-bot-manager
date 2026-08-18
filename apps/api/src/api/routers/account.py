"""User-facing profile and cross-chat dashboard endpoints."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Literal, TypedDict, cast

from fastapi import APIRouter, Query, status
from pydantic import BeforeValidator

from api.chat_scope import accessible_chats
from api.deps import AdminsDep, PrincipalDep, UowDep
from api.errors import problem_responses
from api.security import Principal
from core.features import effective_plan
from db.models import Chat, TgUser
from shared.enums import AdminRole, Plan, PunishmentType
from shared.errors import ChatNotFoundError
from shared.logging import get_logger
from shared.plans import PLAN_FEATURES, Feature
from shared.schemas.api import (
    ChatSummary,
    DashboardModeration,
    DashboardTotals,
    ModerationBreakdownEntry,
    StatPoint,
    TopUser,
    UserDashboard,
    UserProfile,
)
from shared.time_utils import utc_now

logger = get_logger(__name__)


def _parse_stats_window(value: object) -> object:
    """Coerce HTTP query strings before validating the allowed integer values."""
    if isinstance(value, str):
        return int(value)
    return value


StatsWindow = Annotated[Literal[1, 7, 30, 90], BeforeValidator(_parse_stats_window)]


class ActivityRow(TypedDict):
    date: date
    messages: int
    active_users: int
    joins: int
    leaves: int
    moderation_actions: int


class ModerationAggregate(TypedDict):
    total: int
    mine: int
    automated: int
    moderators: int
    breakdown: list[tuple[str, int]]


router = APIRouter(
    prefix="/me",
    tags=["account"],
    responses=problem_responses(
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
    ),
)


def _display_name(principal: Principal, profile: TgUser | None) -> str:
    if profile is not None:
        return profile.display_name
    full_name = " ".join(
        part for part in (principal.first_name, principal.last_name or "") if part
    ).strip()
    if full_name:
        return full_name
    return f"@{principal.username}" if principal.username else f"id{principal.tg_user_id}"


def _chat_summary(chat: Chat, tg_user_id: int) -> ChatSummary:
    return ChatSummary(
        id=chat.id,
        tg_chat_id=chat.tg_chat_id,
        title=chat.title,
        type=chat.type,
        plan=effective_plan(chat),
        plan_expires_at=chat.plan_expires_at,
        is_active=chat.is_active,
        role=AdminRole.OWNER if chat.owner_tg_id == tg_user_id else AdminRole.ADMIN,
        members_count=chat.members_count,
    )


@router.get(
    "/profile",
    response_model=UserProfile,
    operation_id="getUserProfile",
    summary="The caller's profile and managed-chat footprint",
)
async def get_user_profile(principal: PrincipalDep, uow: UowDep, admins: AdminsDep) -> UserProfile:
    profile = await uow.users.get(principal.tg_user_id)
    chats = await accessible_chats(principal, uow, admins)
    owned = sum(chat.owner_tg_id == principal.tg_user_id for chat in chats)
    user = principal.to_schema()
    if profile is not None:
        user = user.model_copy(update={"has_photo": profile.has_photo or user.has_photo})
    return UserProfile(
        user=user,
        display_name=_display_name(principal, profile),
        first_seen_at=profile.created_at if profile is not None else None,
        chats_total=len(chats),
        chats_owned=owned,
        chats_admin=len(chats) - owned,
        paid_chats=sum(effective_plan(chat) is not Plan.FREE for chat in chats),
        total_members=sum(chat.members_count or 0 for chat in chats),
    )


def _series(rows: list[ActivityRow], *, start: date, end: date) -> list[StatPoint]:
    by_day = {row["date"]: row for row in rows}
    points: list[StatPoint] = []
    day = start
    while day <= end:
        row = by_day.get(day)
        points.append(
            StatPoint(
                date=day,
                messages=row["messages"] if row is not None else 0,
                active_users=row["active_users"] if row is not None else 0,
                joins=row["joins"] if row is not None else 0,
                leaves=row["leaves"] if row is not None else 0,
                moderation_actions=row["moderation_actions"] if row is not None else 0,
            )
        )
        day += timedelta(days=1)
    return points


def _totals(rows: list[ActivityRow]) -> DashboardTotals:
    joins = sum(row["joins"] for row in rows)
    leaves = sum(row["leaves"] for row in rows)
    return DashboardTotals(
        messages=sum(row["messages"] for row in rows),
        active_users=max((row["active_users"] for row in rows), default=0),
        joins=joins,
        leaves=leaves,
        net_growth=joins - leaves,
        moderation_actions=sum(row["moderation_actions"] for row in rows),
    )


def _start_of_day(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


def _delta(current: int, previous: int) -> float | None:
    if previous == 0:
        return 0.0 if current == 0 else None
    return round(((current - previous) / previous) * 100, 1)


@router.get(
    "/dashboard",
    response_model=UserDashboard,
    operation_id="getUserDashboard",
    summary="Activity and moderation across the caller's chats",
)
async def get_user_dashboard(
    principal: PrincipalDep,
    uow: UowDep,
    admins: AdminsDep,
    days: Annotated[StatsWindow, Query(description="Dashboard period")] = 7,
    chat_id: Annotated[int | None, Query(ge=1, description="Optional managed chat filter")] = None,
) -> UserDashboard:
    chats = await accessible_chats(principal, uow, admins)
    selected = next((chat for chat in chats if chat.id == chat_id), None)
    if chat_id is not None and selected is None:
        raise ChatNotFoundError("Chat is not connected.", chat_id=chat_id)
    scoped = [selected] if selected is not None else chats

    scoped_ids = [chat.id for chat in scoped]
    analytics_ids = [
        chat.id for chat in scoped if Feature.STATS in PLAN_FEATURES[effective_plan(chat)]
    ]
    analytics_chat_count = len(analytics_ids)

    today = utc_now().date()
    current_start = today - timedelta(days=days - 1)
    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=days - 1)
    activity_rows = cast(
        list[ActivityRow],
        await uow.stats.daily_range_many(
            chat_ids=analytics_ids,
            start=previous_start,
            end=today,
        ),
    )
    current_rows = [row for row in activity_rows if row["date"] >= current_start]
    previous_rows = [row for row in activity_rows if row["date"] <= previous_end]
    current = _totals(current_rows)
    previous = _totals(previous_rows)
    series = _series(current_rows, start=current_start, end=today) if analytics_ids else []

    current_start_at = _start_of_day(current_start)
    current_moderation = cast(
        ModerationAggregate,
        await uow.moderation_logs.dashboard_many(
            scoped_ids,
            since=current_start_at,
            viewer_tg_id=principal.tg_user_id,
        ),
    )
    previous_moderation = cast(
        ModerationAggregate,
        await uow.moderation_logs.dashboard_many(
            scoped_ids,
            since=_start_of_day(previous_start),
            until=current_start_at,
            viewer_tg_id=principal.tg_user_id,
            breakdown_limit=0,
        ),
    )
    current.moderation_actions = current_moderation["total"]
    previous.moderation_actions = previous_moderation["total"]

    warns = await uow.warns.count_issued_many(scoped_ids, current_start_at)
    punishment_counts = await uow.punishments.count_issued_by_type_many(
        scoped_ids, current_start_at
    )
    restrictions = punishment_counts.get(PunishmentType.MUTE.value, 0) + punishment_counts.get(
        PunishmentType.BAN.value, 0
    )
    moderation = DashboardModeration(
        total=current_moderation["total"],
        warns=warns,
        restrictions=restrictions,
        mine=current_moderation["mine"],
        automated=current_moderation["automated"],
        moderators=current_moderation["moderators"],
        breakdown=[
            ModerationBreakdownEntry(action=action, count=count)
            for action, count in current_moderation["breakdown"]
        ],
    )

    leaders = await uow.stats.top_users_many(
        chat_ids=analytics_ids,
        start=current_start,
        end=today,
        limit=10,
    )
    profiles = await uow.users.get_many([tg_user_id for tg_user_id, _ in leaders])
    top_users = [
        TopUser(
            tg_user_id=tg_user_id,
            messages=messages,
            username=profiles[tg_user_id].username if tg_user_id in profiles else None,
            display_name=profiles[tg_user_id].display_name if tg_user_id in profiles else None,
        )
        for tg_user_id, messages in leaders
    ]

    delta_fields = (
        "messages",
        "active_users",
        "joins",
        "leaves",
        "net_growth",
        "moderation_actions",
    )
    deltas = {
        field: _delta(int(getattr(current, field)), int(getattr(previous, field)))
        for field in delta_fields
    }
    logger.info(
        "api.user_dashboard_served",
        user_id=principal.tg_user_id,
        days=days,
        chat_id=chat_id,
        chats=len(scoped),
    )
    return UserDashboard(
        period_days=days,
        selected_chat_id=chat_id,
        scoped_chat_count=len(chats),
        analytics_chat_count=analytics_chat_count,
        analytics_available=bool(analytics_ids),
        totals=current,
        previous=previous,
        deltas_percent=deltas,
        series=series,
        moderation=moderation,
        top_users=top_users,
        chats=[_chat_summary(chat, principal.tg_user_id) for chat in chats],
    )


__all__ = ["router"]
