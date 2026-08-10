"""AI moderation — the last guard before the routers, and the only paid one.

Spec §4.3 puts it last for a reason: every cheap rule above has already had its
say, and a message that was deleted for a stop-word never becomes a billed API
call. Spec §5.5 is the behaviour.

DECISION: the middleware asks the service and then hands off to `enforce`, the
same function stop-words and content filters use. An AI-flagged message is
deleted, warned and logged through the identical path as a rule-flagged one, so
the audit trail and the log channel do not need to know which guard fired.

DECISION: `ALERT_ADMINS` does not touch the message. It is the setting a chat
uses while it is still deciding whether to trust the classifier, and a mode that
quietly deleted things would defeat the purpose of having it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from bot.enforcement import enforce
from bot.facts import display_name, facts_from
from core.admins import admins
from core.ai_moderation import AiDecision, ai_moderation
from core.ai_provider import ModerationContext
from core.audit import audit
from core.content_filters import MessageFacts
from core.context import ChatContext, chat_context
from shared.enums import ModerationAction, ModuleName
from shared.logging import get_logger
from shared.plans import limits_for_plan
from shared.schemas.module_configs import AiModerationConfig

logger = get_logger(__name__)

# Which label maps to which notice the chat sees when a message is removed.
NOTICE_KEYS: dict[str, str] = {
    "toxic": "notice-ai-toxic",
    "hidden_ad": "notice-ai-hidden-ad",
    "scam": "notice-ai-scam",
}


async def _alert(
    ctx: ChatContext,
    message: Message,
    decision: AiDecision,
    *,
    config: AiModerationConfig,
) -> None:
    """Tell the admins and leave the message alone.

    Routed through the audit channel rather than the chat: an alert the whole
    group can read is an accusation, and this mode exists precisely for chats
    that do not yet trust the classifier enough to act on it.
    """
    author = message.from_user
    await audit.report(
        log_channel_id=config.alert_chat_id or ctx.moderation.log_channel_id,
        locale=ctx.language,
        action="ai_alert",
        target_name=display_name(author) if author else "",
        target_id=author.id if author else None,
        reason=f"{decision.verdict.label.value} {decision.verdict.confidence:.2f}",
        note=decision.verdict.reason,
    )


class AiModerationMiddleware(BaseMiddleware):
    """Classifies message text and enforces the chat's per-label action."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        ctx: ChatContext | None = data.get("ctx")
        if not isinstance(event, Message) or ctx is None or event.from_user is None:
            return await handler(event, data)
        if not ctx.module_enabled(ModuleName.AI_MODERATION):
            return await handler(event, data)

        facts: MessageFacts = data.get("facts") or facts_from(event)
        data["facts"] = facts
        if facts.is_service or not facts.text:
            return await handler(event, data)

        config = await chat_context.config(ctx, ModuleName.AI_MODERATION, AiModerationConfig)
        # Admins are exempt on the same grounds as everywhere else, and checking
        # them would spend budget on the people who configured the thing.
        if await admins.is_admin(ctx.tg_chat_id, event.from_user.id):
            return await handler(event, data)

        moderation_ctx = ModerationContext(
            chat_id=ctx.chat_id,
            chat_title=ctx.title,
            language=ctx.language,
            tg_user_id=event.from_user.id,
        )
        decision = await ai_moderation.inspect(
            facts.text,
            ctx=moderation_ctx,
            config=config,
            plan_limit=limits_for_plan(ctx.plan).ai_checks_per_day,
        )
        if not decision.checked:
            return await handler(event, data)

        await ai_moderation.record(decision, ctx=moderation_ctx)
        if not decision.should_act:
            return await handler(event, data)

        logger.info(
            "ai_moderation.flagged",
            chat_id=ctx.chat_id,
            user_id=event.from_user.id,
            label=decision.verdict.label.value,
            confidence=round(decision.verdict.confidence, 3),
            action=decision.action.value,
            cached=decision.cached,
        )

        if decision.action is ModerationAction.ALERT_ADMINS:
            # Report and step aside: the message stays, the admins get told.
            await _alert(ctx, event, decision, config=config)
            return await handler(event, data)

        await enforce(
            event,
            ctx,
            action=decision.action,
            audit_action="ai_moderation",
            reason=f"ai:{decision.verdict.label.value} {decision.verdict.confidence:.2f}",
            notice_key=NOTICE_KEYS.get(decision.verdict.label.value, "notice-ai-scam"),
        )
        return None


__all__ = ["AiModerationMiddleware"]
