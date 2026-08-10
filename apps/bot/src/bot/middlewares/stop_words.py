"""Stop-words and anti-flood — the last two cheap rules before the routers.

Spec §4.3 lists them as one step, and they share a shape: both look at a message
the content filters already let through, and both end in the same enforcement
call.

DECISION: the stop-word check runs first. It is pure CPU against an already
compiled regex, while anti-flood costs a Redis round-trip — and a user whose
message is being deleted for a slur does not also need a flood counter bumped.

DECISION: anti-flood counts every message that reaches this point, including
admins' own, but only *acts* on non-exempt users. The counter is what a later
"chat activity" reading is built from, and skipping it for admins would make the
window lie.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from bot.enforcement import enforce
from bot.facts import facts_from
from core.admins import admins
from core.anti_flood import anti_flood
from core.content_filters import MessageFacts
from core.context import ChatContext
from core.stop_words import matcher_for
from shared.enums import ModerationAction, ModuleName
from shared.logging import get_logger

logger = get_logger(__name__)


class StopWordFloodMiddleware(BaseMiddleware):
    """Deletes messages containing stop-words; mutes users who flood."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        ctx: ChatContext | None = data.get("ctx")
        if not isinstance(event, Message) or ctx is None or event.from_user is None:
            return await handler(event, data)
        if not ctx.module_enabled(ModuleName.MODERATION):
            return await handler(event, data)

        facts: MessageFacts = data.get("facts") or facts_from(event)
        data["facts"] = facts
        if facts.is_service:
            return await handler(event, data)

        config = ctx.moderation
        exempt = config.exempt_admins and await admins.is_admin(ctx.tg_chat_id, event.from_user.id)

        # --- stop-words -------------------------------------------------------
        if not exempt and facts.text:
            matcher = matcher_for(config.stop_words, config.stop_word_presets)
            hit = matcher.find(facts.text)
            if hit is not None:
                await enforce(
                    event,
                    ctx,
                    action=config.stop_word_action or ModerationAction.DELETE,
                    audit_action="stop_word",
                    reason=f"stop_word:{hit}",
                    notice_key="notice-stop-word",
                    mute_hours=config.stop_word_mute_hours,
                )
                return None

        # --- anti-flood -------------------------------------------------------
        verdict = await anti_flood.check(
            ctx.chat_id,
            event.from_user.id,
            config=config,
            content_kind=facts.content_kind,
        )
        if verdict is None or verdict.tripped is False or exempt:
            return await handler(event, data)

        # The window that earned the mute must not earn a second one while the
        # first is still in force.
        await anti_flood.reset(ctx.chat_id, event.from_user.id)
        await enforce(
            event,
            ctx,
            action=ModerationAction.DELETE_MUTE,
            audit_action="anti_flood",
            reason=f"flood:{verdict.kind} {verdict.count}/{verdict.limit}",
            notice_key="notice-flood",
            notice_args={
                "count": verdict.count,
                "seconds": verdict.window_seconds,
            },
            mute_duration=timedelta(minutes=config.anti_flood_mute_minutes),
        )
        return None


__all__ = ["StopWordFloodMiddleware"]
