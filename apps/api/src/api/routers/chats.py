"""Chat list, chat detail and chat-level settings.

DECISION: the list comes from the mirrored `admin_users` table, not from
`getChatAdministrators` per chat. An admin of twenty chats would otherwise cost
twenty Bot API calls to draw one screen. The mirror can be stale in the
permissive direction — it may still list a chat the user was just demoted in —
so every per-chat route re-checks with `getChatMember` before doing anything.
That makes a stale mirror a cosmetic problem, never an authorization one.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, status

from api.deps import (
    AdminsDep,
    ChatAccessDep,
    ConfigsDep,
    FeaturesDep,
    PrincipalDep,
    UowDep,
)
from api.errors import problem_responses
from core import cache
from core.features import effective_plan, in_grace_period
from core.registry import registry
from db.models import Chat
from shared.enums import AdminRole
from shared.errors import InvalidTimezoneError
from shared.logging import get_logger
from shared.schemas.api import ChatDetail, ChatSummary, ChatUpdate, OperationResult

logger = get_logger(__name__)

router = APIRouter(
    prefix="/chats",
    tags=["chats"],
    responses=problem_responses(
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
    ),
)


def _role(chat: Chat, tg_user_id: int) -> AdminRole:
    return AdminRole.OWNER if chat.owner_tg_id == tg_user_id else AdminRole.ADMIN


def _summary(chat: Chat, tg_user_id: int) -> ChatSummary:
    return ChatSummary(
        id=chat.id,
        tg_chat_id=chat.tg_chat_id,
        title=chat.title,
        type=chat.type,
        # The stored plan is not the plan in force: an expired subscription still
        # runs on Pro until grace ends. The panel must show what actually applies.
        plan=effective_plan(chat),
        plan_expires_at=chat.plan_expires_at,
        is_active=chat.is_active,
        role=_role(chat, tg_user_id),
        members_count=chat.members_count,
    )


@router.get(
    "",
    response_model=list[ChatSummary],
    operation_id="listChats",
    summary="Chats where the caller is an administrator",
)
async def list_chats(principal: PrincipalDep, uow: UowDep) -> list[ChatSummary]:
    chats = await uow.chats.list_for_admin(principal.tg_user_id)
    return [_summary(chat, principal.tg_user_id) for chat in chats]


@router.get(
    "/{chat_id}",
    response_model=ChatDetail,
    operation_id="getChat",
    summary="One chat with its module state and unlocked features",
)
async def get_chat(access: ChatAccessDep, configs: ConfigsDep, features: FeaturesDep) -> ChatDetail:
    chat = access.chat
    enabled = await configs.enabled_modules(chat.id)
    unlocked = await features.features(chat.id)
    summary = _summary(chat, access.principal.tg_user_id)
    return ChatDetail(
        **summary.model_dump(),
        owner_tg_id=chat.owner_tg_id,
        language=chat.language,
        timezone=chat.timezone,
        modules={spec.name.value: spec.name.value in enabled for spec in registry},
        features=sorted(feature.value for feature in unlocked),
        created_at=chat.created_at,
    )


@router.patch(
    "/{chat_id}",
    response_model=ChatDetail,
    operation_id="updateChat",
    summary="Update chat-level settings (language, timezone)",
)
async def update_chat(
    payload: ChatUpdate,
    access: ChatAccessDep,
    uow: UowDep,
    configs: ConfigsDep,
    features: FeaturesDep,
) -> ChatDetail:
    fields = payload.model_dump(exclude_unset=True, exclude_none=True)
    if timezone := fields.get("timezone"):
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            # Schedules are computed in this timezone; an unknown name would fail
            # later, inside a cron job, where nobody is watching.
            raise InvalidTimezoneError("Unknown timezone.", timezone=timezone) from exc

    if fields:
        await uow.chats.update_fields(access.chat_id, **fields)
        await uow.commit()
        # Spec §5.7: a setting applies instantly — the bot re-reads through the
        # cache, so the write is only finished once the chat's entries are gone.
        await cache.invalidate_chat(access.chat_id)
        logger.info("api.chat_updated", chat_id=access.chat_id, fields=sorted(fields))
        for key, value in fields.items():
            setattr(access.chat, key, value)

    return await get_chat(access, configs, features)


@router.post(
    "/{chat_id}/admins/sync",
    response_model=OperationResult,
    status_code=status.HTTP_200_OK,
    operation_id="syncChatAdmins",
    summary="Re-read the chat's administrator list from Telegram",
)
async def sync_admins(access: ChatAccessDep, admins: AdminsDep) -> OperationResult:
    """Refresh the mirror the chat list is drawn from, and drop cached verdicts.

    Telegram sends no update on a promotion, so this is how a newly promoted
    admin makes the chat appear in their panel without waiting for the bot to
    happen to sync it.
    """
    count = await admins.sync_to_db(access.chat_id, access.tg_chat_id)
    return OperationResult(ok=True, detail=f"{count} administrators synchronized.")


@router.get(
    "/{chat_id}/plan",
    response_model=ChatSummary,
    operation_id="getChatPlan",
    summary="The plan actually in force for a chat",
)
async def get_chat_plan(access: ChatAccessDep) -> ChatSummary:
    summary = _summary(access.chat, access.principal.tg_user_id)
    if in_grace_period(access.chat):
        logger.info("api.chat_in_grace", chat_id=access.chat_id)
    return summary


__all__ = ["router"]
