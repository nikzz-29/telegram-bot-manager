"""Stop-words and anti-flood — the last two cheap rules before the routers.

Spec §4.3 lists them as one step, and they share a shape: both look at a message
the content filters already let through, and both end in the same enforcement
call.

DECISION: the stop-word check runs first. It is pure CPU against an already
compiled regex, while anti-flood costs a Redis round-trip — and a user whose
message is being deleted for a slur does not also need a flood counter bumped.

DECISION: anti-flood counts every new authored message that reaches this point,
including admins' own, but only *acts* on non-exempt users. Edited messages still
run stop-word checks, but never increment the sliding window: repeatedly editing
one Telegram message is not a message flood.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from bot.enforcement import enforce
from bot.facts import facts_from, is_anonymous_admin
from core import actions
from core.admins import admins
from core.anti_flood import anti_flood
from core.content_filters import MessageFacts
from core.context import ChatContext
from core.sender import SendPriority, sender
from core.stop_words import matcher_for
from shared.enums import ModerationAction, ModuleName
from shared.logging import get_logger
from shared.plans import Feature

logger = get_logger(__name__)


class StopWordFloodMiddleware(BaseMiddleware):
    """Deletes messages containing stop-words; mutes users who flood."""

    def __init__(self, *, count_flood: bool = True) -> None:
        self._count_flood = count_flood

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        ctx: ChatContext | None = data.get("ctx")
        if not isinstance(event, Message) or ctx is None:
            return await handler(event, data)
        if not ctx.module_enabled(ModuleName.MODERATION):
            return await handler(event, data)
        stop_words_available = ctx.has(Feature.STOP_WORDS)
        anti_flood_available = ctx.has(Feature.ANTI_FLOOD)
        if not stop_words_available and not anti_flood_available:
            return await handler(event, data)

        facts: MessageFacts = data.get("facts") or facts_from(event)
        data["facts"] = facts
        if facts.is_service:
            return await handler(event, data)

        config = ctx.moderation
        exempt = False
        if config.exempt_admins:
            exempt = is_anonymous_admin(event)
            if not exempt and event.from_user is not None:
                exempt = await admins.is_admin(ctx.tg_chat_id, event.from_user.id)

        # --- stop-words -------------------------------------------------------
        if stop_words_available and not exempt and facts.text:
            matcher = matcher_for(config.stop_words, config.stop_word_presets)
            hit = matcher.find(facts.text)
            if hit is not None:
                action = config.stop_word_action or ModerationAction.DELETE
                if event.from_user is None:
                    if action != ModerationAction.NOTHING:
                        sender.enqueue(
                            actions.delete_message(ctx.tg_chat_id, event.message_id),
                            chat_id=ctx.tg_chat_id,
                            priority=SendPriority.MODERATION,
                        )
                else:
                    await enforce(
                        event,
                        ctx,
                        action=action,
                        audit_action="stop_word",
                        reason=f"stop_word:{hit}",
                        notice_key="notice-stop-word",
                        mute_hours=config.stop_word_mute_hours,
                    )
                return None

        # --- anti-flood -------------------------------------------------------
        if not anti_flood_available or not self._count_flood or event.from_user is None:
            return await handler(event, data)
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
