"""Applying an automatic moderation decision to a Telegram chat.

Content filters, stop-words, anti-flood and (from Stage 6) AI moderation all
reach the same conclusion — "this message must go, and here is what to do about
its author" — so they all end here. One place means the notice wording, the log
entry and the Telegram calls cannot drift between the four rules.

DECISION: the *domain* decision and the *Telegram* effect are deliberately two
steps. `moderation.apply_auto_action` writes the punishment row and schedules its
expiry job; only then does this module tell Telegram. If the write fails there is
no restriction to lift and nothing to reconcile — the message simply stays.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from aiogram.methods import TelegramMethod
from aiogram.types import Message

from bot.facts import display_name, mention
from bot.replies import notify
from core import actions
from core.audit import audit
from core.context import ChatContext
from core.durations import format_duration
from core.moderation import (
    ModerationTarget,
    PunishmentOutcome,
    WarnOutcome,
    moderation,
)
from core.sender import SendPriority, sender
from i18n.runtime import translator
from shared.enums import ModerationAction, PunishmentType, WarnPunishment
from shared.logging import get_logger
from shared.time_utils import utc_now

logger = get_logger(__name__)

Outcome = WarnOutcome | PunishmentOutcome | None

# The bot itself is the moderator behind an automatic action. 0 is the sentinel:
# no Telegram account has that id, so it can never collide with a human.
AUTOMATIC_MODERATOR = 0


def parse_until(value: str) -> datetime | None:
    """Outcomes carry ISO strings so the domain layer stays serializable."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:  # pragma: no cover - defensive
        logger.warning("enforcement.bad_until", value=value)
        return None


def _remaining(until: datetime | None) -> str:
    """`2h30m` left on a restriction, for the notice and the log entry."""
    if until is None:
        return ""
    return format_duration(max(until - utc_now(), timedelta()))


def apply_outcome(ctx: ChatContext, tg_user_id: int, outcome: Outcome) -> tuple[str, str]:
    """Issue the Telegram-side restriction the outcome implies.

    Returns `(punishment, duration)` for the caller's notice — both empty when
    the outcome was a plain delete or a warn below the limit.

    Public because `/warn` reaches the same fork: a manual warn that trips the
    limit must restrict exactly like an automatic one.
    """
    if isinstance(outcome, PunishmentOutcome):
        until = parse_until(outcome.until)
        restriction: TelegramMethod[Any]
        if outcome.type == PunishmentType.MUTE:
            restriction = actions.mute(ctx.tg_chat_id, tg_user_id, until)
        elif outcome.type == PunishmentType.BAN:
            restriction = actions.ban(ctx.tg_chat_id, tg_user_id, until)
        else:
            return outcome.type.value, ""
        sender.enqueue(restriction, chat_id=ctx.tg_chat_id, priority=SendPriority.MODERATION)
        return outcome.type.value, _remaining(until)

    if isinstance(outcome, WarnOutcome) and outcome.limit_reached:
        if outcome.punishment == WarnPunishment.BAN:
            sender.enqueue(
                actions.ban(ctx.tg_chat_id, tg_user_id),
                chat_id=ctx.tg_chat_id,
                priority=SendPriority.MODERATION,
            )
            return WarnPunishment.BAN.value, ""
        if outcome.punishment == WarnPunishment.KICK:
            for method in actions.kick(ctx.tg_chat_id, tg_user_id):
                sender.enqueue(method, chat_id=ctx.tg_chat_id, priority=SendPriority.MODERATION)
            return WarnPunishment.KICK.value, ""
        until = parse_until(outcome.punishment_until)
        sender.enqueue(
            actions.mute(ctx.tg_chat_id, tg_user_id, until),
            chat_id=ctx.tg_chat_id,
            priority=SendPriority.MODERATION,
        )
        return WarnPunishment.MUTE.value, _remaining(until)

    return "", ""


def _notice_lines(
    ctx: ChatContext,
    author_mention: str,
    notice_key: str,
    notice_args: dict[str, Any],
    outcome: Outcome,
    punishment: str,
    duration: str,
) -> list[str]:
    """The rule, then what it cost the author — one line each."""
    t = translator(ctx.language)
    lines = [t(notice_key, user=author_mention, **notice_args)]
    if isinstance(outcome, WarnOutcome):
        lines.append(t("notice-warned", count=outcome.count, limit=outcome.limit))
    if punishment == PunishmentType.MUTE.value:
        lines.append(
            t("notice-muted", duration=duration) if duration else t("notice-muted-forever")
        )
    elif punishment == PunishmentType.BAN.value:
        lines.append(t("notice-banned"))
    return lines


async def enforce(
    message: Message,
    ctx: ChatContext,
    *,
    action: ModerationAction,
    audit_action: str,
    reason: str,
    notice_key: str,
    notice_args: dict[str, Any] | None = None,
    mute_hours: int | None = None,
    mute_duration: timedelta | None = None,
    delete: bool = True,
) -> None:
    """Delete the offending message, punish its author, tell everyone why."""
    author = message.from_user
    if author is None:
        return

    if delete and action != ModerationAction.NOTHING:
        sender.enqueue(
            actions.delete_message(ctx.tg_chat_id, message.message_id),
            chat_id=ctx.tg_chat_id,
            priority=SendPriority.MODERATION,
        )

    target = ModerationTarget(
        chat_id=ctx.chat_id,
        tg_chat_id=ctx.tg_chat_id,
        tg_user_id=author.id,
        moderator_tg_id=AUTOMATIC_MODERATOR,
        display_name=display_name(author),
    )
    outcome = await moderation.apply_auto_action(
        target,
        action,
        reason=reason,
        config=ctx.moderation,
        mute_hours=mute_hours,
        mute_duration=mute_duration,
    )
    punishment, duration = apply_outcome(ctx, author.id, outcome)

    if action != ModerationAction.NOTHING:
        await notify(
            ctx,
            "\n".join(
                _notice_lines(
                    ctx,
                    mention(author),
                    notice_key,
                    notice_args or {},
                    outcome,
                    punishment,
                    duration,
                )
            ),
        )

    await audit.report(
        log_channel_id=ctx.moderation.log_channel_id,
        locale=ctx.language,
        action=audit_action,
        target_name=display_name(author),
        target_id=author.id,
        reason=reason,
        duration=duration,
        note=punishment,
    )
    logger.info(
        "enforcement.applied",
        chat_id=ctx.chat_id,
        user_id=author.id,
        rule=audit_action,
        action=action.value,
        punishment=punishment or None,
    )


__all__ = ["AUTOMATIC_MODERATOR", "apply_outcome", "enforce", "parse_until"]
