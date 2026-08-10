"""Trigger rules — the phrase-to-reply list behind the Engagement section.

Spec §5.6. Composing a trigger needs media, buttons and a match mode, which is
why the full CRUD lives here rather than in the chat commands; `/triggers` in the
chat is only the read-only view of what this endpoint wrote.

DECISION: every write revalidates the pattern through `core.triggers`, not just
the ones that changed it. A `PATCH` that flips `match` from "contains" to "regex"
leaves the stored pattern untouched but changes what it means — validating the
pair, always, is what stops a chat's whole trigger set from failing to compile on
the next message.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Path, status

from api.deps import ChatAccessDep, FeaturesDep, UowDep
from api.errors import problem_responses
from core.triggers import triggers as trigger_service
from core.triggers import validate_pattern
from db.models import TriggerRule
from db.uow import UnitOfWork
from shared.enums import TriggerMatch
from shared.errors import ResourceNotFoundError
from shared.logging import get_logger
from shared.plans import Feature
from shared.schemas.api import OperationResult, TriggerCreate, TriggerEntry, TriggerUpdate

logger = get_logger(__name__)

router = APIRouter(
    prefix="/chats/{chat_id}/triggers",
    tags=["triggers"],
    responses=problem_responses(
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_402_PAYMENT_REQUIRED,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_409_CONFLICT,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
    ),
)

TriggerIdPath = Annotated[int, Path(ge=1, description="Trigger id, unique per chat.")]


def _entry(row: TriggerRule) -> TriggerEntry:
    return TriggerEntry.model_validate(row)


async def _load(uow: UnitOfWork, chat_id: int, trigger_id: int) -> TriggerRule:
    row = await uow.triggers.get(chat_id, trigger_id)
    if row is None:
        raise ResourceNotFoundError("No such trigger.", trigger_id=trigger_id)
    return row


@router.get(
    "",
    response_model=list[TriggerEntry],
    operation_id="listTriggers",
    summary="Every trigger rule in a chat",
)
async def list_triggers(access: ChatAccessDep, uow: UowDep) -> list[TriggerEntry]:
    """Disabled rules included — the panel renders them with the switch off."""
    rows = await uow.triggers.list_for_chat(access.chat_id)
    return [_entry(row) for row in rows]


@router.post(
    "",
    response_model=TriggerEntry,
    status_code=status.HTTP_201_CREATED,
    operation_id="createTrigger",
    summary="Add a trigger rule",
)
async def create_trigger(
    payload: TriggerCreate,
    access: ChatAccessDep,
    uow: UowDep,
    features: FeaturesDep,
) -> TriggerEntry:
    await features.require(access.chat_id, Feature.TRIGGERS)
    await features.check_quota(access.chat_id, "triggers", await uow.triggers.count(access.chat_id))

    fields: dict[str, Any] = payload.model_dump(mode="json")
    fields["pattern"] = validate_pattern(
        payload.pattern, payload.match, case_sensitive=payload.case_sensitive
    )
    row = await uow.triggers.create(access.chat_id, **fields)
    await uow.commit()
    await trigger_service.invalidate(access.chat_id)

    logger.info("api.trigger_created", chat_id=access.chat_id, trigger_id=row.id)
    return _entry(row)


@router.get(
    "/{trigger_id}",
    response_model=TriggerEntry,
    operation_id="getTrigger",
    summary="One trigger rule",
)
async def get_trigger(
    trigger_id: TriggerIdPath, access: ChatAccessDep, uow: UowDep
) -> TriggerEntry:
    return _entry(await _load(uow, access.chat_id, trigger_id))


@router.patch(
    "/{trigger_id}",
    response_model=TriggerEntry,
    operation_id="updateTrigger",
    summary="Change a trigger rule",
)
async def update_trigger(
    trigger_id: TriggerIdPath,
    payload: TriggerUpdate,
    access: ChatAccessDep,
    uow: UowDep,
    features: FeaturesDep,
) -> TriggerEntry:
    await features.require(access.chat_id, Feature.TRIGGERS)
    current = await _load(uow, access.chat_id, trigger_id)

    fields: dict[str, Any] = payload.model_dump(mode="json", exclude_unset=True)
    pattern = str(fields.get("pattern", current.pattern))
    match = TriggerMatch(fields.get("match", current.match))
    case_sensitive = bool(fields.get("case_sensitive", current.case_sensitive))
    fields["pattern"] = validate_pattern(pattern, match, case_sensitive=case_sensitive)

    await uow.triggers.update(access.chat_id, trigger_id, **fields)
    await uow.commit()
    await trigger_service.invalidate(access.chat_id)

    logger.info(
        "api.trigger_updated",
        chat_id=access.chat_id,
        trigger_id=trigger_id,
        fields=sorted(fields),
    )
    return _entry(await _load(uow, access.chat_id, trigger_id))


@router.delete(
    "/{trigger_id}",
    response_model=OperationResult,
    operation_id="deleteTrigger",
    summary="Delete a trigger rule",
)
async def delete_trigger(
    trigger_id: TriggerIdPath, access: ChatAccessDep, uow: UowDep
) -> OperationResult:
    """Not plan-gated: a downgraded chat must still be able to clear its rules."""
    if not await uow.triggers.delete(access.chat_id, trigger_id):
        raise ResourceNotFoundError("No such trigger.", trigger_id=trigger_id)
    await uow.commit()
    await trigger_service.invalidate(access.chat_id)

    logger.info("api.trigger_deleted", chat_id=access.chat_id, trigger_id=trigger_id)
    return OperationResult(ok=True, detail=f"Trigger {trigger_id} deleted.")


__all__ = ["router"]
