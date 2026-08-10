"""Scheduled posts — the composer and schedule behind the Autoposting section.

Spec §5.6. This is the write side of the module: composing a post needs media,
buttons, a pin flag and a calendar, so the full CRUD lives here rather than in
the chat; `/posts` in the chat is only the read-only view of what this endpoint
wrote.

DECISION: the ARQ job and the row stay in agreement on every write, by hand.
`next_run_at` is recomputed here from the schedule (the same `core.autopost` code
the worker uses) and stored, then `arm`/`disarm` re-point the job queue at that
same moment. If one drifted, the other would either fire a retired post or wait
for the fifteen-minute safety-net sweep, so the pairing is not optional.

DECISION: the queue is touched only after the transaction commits. Arming first
would leave a job pointing at a row that a rolled-back write never created —
the worker would wake up, find nothing, and log a phantom failure.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Path, status

from api.deps import ChatAccess, ChatAccessDep, ConfigsDep, FeaturesDep, UowDep
from api.errors import problem_responses
from core.autopost import arm, disarm, next_run, validate_schedule
from core.configs import ModuleConfigService
from db.models import ScheduledPost
from db.uow import UnitOfWork
from shared.enums import ModuleName, ScheduleKind
from shared.errors import ResourceNotFoundError
from shared.logging import get_logger
from shared.plans import Feature
from shared.schemas.api import OperationResult, PostCreate, PostEntry, PostUpdate
from shared.schemas.module_configs import AutopostConfig
from shared.time_utils import utc_now

logger = get_logger(__name__)

router = APIRouter(
    prefix="/chats/{chat_id}/posts",
    tags=["posts"],
    responses=problem_responses(
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_402_PAYMENT_REQUIRED,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_409_CONFLICT,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
    ),
)

PostIdPath = Annotated[int, Path(ge=1, description="Post id, unique per chat.")]


def _entry(row: ScheduledPost) -> PostEntry:
    return PostEntry.model_validate(row)


async def _load(uow: UnitOfWork, chat_id: int, post_id: int) -> ScheduledPost:
    row = await uow.posts.get(chat_id, post_id)
    if row is None:
        raise ResourceNotFoundError("No such post.", post_id=post_id)
    return row


async def _timezone(access: ChatAccess, configs: ModuleConfigService) -> str:
    """The zone schedules are read in — the module's, falling back to the chat's.

    Same resolution order as `worker.jobs.autopost`; if the two disagreed, a
    "daily at 09:00" post would be stored for one hour and sent at another.
    """
    config = await configs.get_as(access.chat_id, ModuleName.AUTOPOST, AutopostConfig)
    return config.timezone or access.chat.timezone or "UTC"


def _next_fire(kind: ScheduleKind, value: str, *, timezone: str) -> datetime | None:
    """When this schedule fires next, or `None` for a one-shot already past."""
    return next_run(kind, value, timezone=timezone, after=utc_now())


async def _requeue(post_id: int, when: datetime | None, *, enabled: bool) -> None:
    """Point the job queue at `when`, or clear it when nothing is due."""
    if enabled and when is not None:
        await arm(post_id, when)
    else:
        await disarm(post_id)


@router.get(
    "",
    response_model=list[PostEntry],
    operation_id="listPosts",
    summary="Every scheduled post in a chat",
)
async def list_posts(access: ChatAccessDep, uow: UowDep) -> list[PostEntry]:
    """Disabled posts included — the panel renders them with the switch off."""
    rows = await uow.posts.list_for_chat(access.chat_id)
    return [_entry(row) for row in rows]


@router.post(
    "",
    response_model=PostEntry,
    status_code=status.HTTP_201_CREATED,
    operation_id="createPost",
    summary="Schedule a new post",
)
async def create_post(
    payload: PostCreate,
    access: ChatAccessDep,
    uow: UowDep,
    configs: ConfigsDep,
    features: FeaturesDep,
) -> PostEntry:
    await features.require(access.chat_id, Feature.AUTOPOST)
    await features.check_quota(
        access.chat_id, "scheduled_posts", await uow.posts.count(access.chat_id)
    )

    fields: dict[str, Any] = payload.model_dump(mode="json")
    fields["schedule_value"] = validate_schedule(payload.schedule_kind, payload.schedule_value)
    upcoming = _next_fire(
        payload.schedule_kind,
        fields["schedule_value"],
        timezone=await _timezone(access, configs),
    )
    fields["next_run_at"] = upcoming

    row = await uow.posts.create(access.chat_id, **fields)
    await uow.commit()
    await _requeue(row.id, upcoming, enabled=row.enabled)

    logger.info(
        "api.post_created",
        chat_id=access.chat_id,
        post_id=row.id,
        schedule=payload.schedule_kind.value,
        next_run_at=upcoming.isoformat() if upcoming else None,
    )
    return _entry(row)


@router.get(
    "/{post_id}",
    response_model=PostEntry,
    operation_id="getPost",
    summary="One scheduled post",
)
async def get_post(post_id: PostIdPath, access: ChatAccessDep, uow: UowDep) -> PostEntry:
    return _entry(await _load(uow, access.chat_id, post_id))


@router.patch(
    "/{post_id}",
    response_model=PostEntry,
    operation_id="updatePost",
    summary="Change a scheduled post",
)
async def update_post(
    post_id: PostIdPath,
    payload: PostUpdate,
    access: ChatAccessDep,
    uow: UowDep,
    configs: ConfigsDep,
    features: FeaturesDep,
) -> PostEntry:
    """Any write recomputes the next fire, not only one that moved the schedule.

    A one-shot may have come due while the panel was open, and a post being
    re-enabled needs its job back; recomputing unconditionally is cheaper than
    reasoning about which field combinations imply a re-arm.
    """
    await features.require(access.chat_id, Feature.AUTOPOST)
    current = await _load(uow, access.chat_id, post_id)

    fields: dict[str, Any] = payload.model_dump(mode="json", exclude_unset=True)
    kind = payload.schedule_kind or current.schedule_kind
    value = str(fields.get("schedule_value", current.schedule_value))
    if "schedule_value" in fields or payload.schedule_kind is not None:
        value = validate_schedule(kind, value)
        fields["schedule_value"] = value

    enabled = current.enabled if payload.enabled is None else payload.enabled
    upcoming = _next_fire(kind, value, timezone=await _timezone(access, configs))
    fields["next_run_at"] = upcoming if enabled else None

    await uow.posts.update(access.chat_id, post_id, **fields)
    await uow.commit()
    await _requeue(post_id, upcoming, enabled=enabled)

    logger.info(
        "api.post_updated",
        chat_id=access.chat_id,
        post_id=post_id,
        enabled=enabled,
        fields=sorted(fields),
    )
    return _entry(await _load(uow, access.chat_id, post_id))


@router.delete(
    "/{post_id}",
    response_model=OperationResult,
    operation_id="deletePost",
    summary="Delete a scheduled post",
)
async def delete_post(post_id: PostIdPath, access: ChatAccessDep, uow: UowDep) -> OperationResult:
    """Not plan-gated: a downgraded chat must still be able to clear its posts."""
    if not await uow.posts.delete(access.chat_id, post_id):
        raise ResourceNotFoundError("No such post.", post_id=post_id)
    await uow.commit()
    # Order matters the other way round here: the row is gone, so a job that
    # survived would fire against nothing.
    await disarm(post_id)

    logger.info("api.post_deleted", chat_id=access.chat_id, post_id=post_id)
    return OperationResult(ok=True, detail=f"Post {post_id} deleted.")


__all__ = ["router"]
