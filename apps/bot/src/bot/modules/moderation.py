"""The moderation module: the commands a human moderator types.

Spec §5.1. Every command works two ways — as a reply, or with `@username`/id as
the first argument (see `bot.targets`). Every one writes a row, mirrors itself to
the log channel, and reaches Telegram through `MessageSender`.

DECISION: the handlers are thin on purpose. They parse arguments, call one
service method, and render one reply. The domain rules — what a warn limit does,
whether a punishment already exists, when the expiry job fires — live in
`core.moderation` and are tested without aiogram anywhere in sight.

DECISION: the command message is deleted once the action succeeds. The bot's own
report says what happened; keeping `/ban @spammer` above it only preserves the
target's username for anyone scrolling back.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.enforcement import AUTOMATIC_MODERATOR, apply_outcome, parse_until
from bot.facts import display_name
from bot.filters import InGroup, IsChatAdmin
from bot.replies import answer, notify
from bot.targets import ResolvedTarget, resolve, split_argument
from core import actions, jobs
from core.audit import audit
from core.context import ChatContext
from core.durations import format_duration, parse_duration, split_duration
from core.jobs import JobName, job_id
from core.moderation import moderation
from core.sender import SendPriority, sender
from i18n.runtime import translator
from shared.enums import PunishmentType
from shared.errors import DomainError, InvalidDurationError
from shared.logging import get_logger

logger = get_logger(__name__)

# A mute with no duration given. Long enough to stop a spam run, short enough
# that forgetting to lift it is not an accidental permanent silence.
DEFAULT_MUTE: Final = timedelta(hours=1)

# How long a `/warns` answer stays before removing itself. Non-admins can run it,
# so in a busy chat it is the one command that could become clutter.
WARNS_TTL: Final = timedelta(minutes=1)

_is_admin = IsChatAdmin()


def _drop_command(ctx: ChatContext, message: Message) -> None:
    sender.enqueue(
        actions.delete_message(ctx.tg_chat_id, message.message_id),
        chat_id=ctx.tg_chat_id,
        priority=SendPriority.MODERATION,
    )


def _moderator_id(message: Message) -> int:
    """The acting moderator; the automatic sentinel for an anonymous admin."""
    return message.from_user.id if message.from_user is not None else AUTOMATIC_MODERATOR


async def _resolve_or_explain(
    message: Message, command: CommandObject, bot: Bot, ctx: ChatContext
) -> tuple[ResolvedTarget, str] | None:
    """Resolve the command's target, or answer with why it could not be."""
    reference, rest = split_argument(command.args)
    try:
        target = await resolve(message, reference, bot_id=bot.id)
    except DomainError as error:
        await answer(message, translator(ctx.language)(error.i18n_key))
        return None
    return target, rest


async def _report(
    ctx: ChatContext,
    message: Message,
    *,
    action: str,
    target: ResolvedTarget | None = None,
    reason: str = "",
    duration: str = "",
    note: str = "",
) -> None:
    """Log-channel entry for a human action: who did what to whom, and why."""
    moderator = message.from_user
    await audit.report(
        log_channel_id=ctx.moderation.log_channel_id,
        locale=ctx.language,
        action=action,
        target_name=target.name if target else "",
        target_id=target.tg_user_id if target else None,
        moderator_name=display_name(moderator) if moderator else "",
        moderator_id=moderator.id if moderator else None,
        reason=reason,
        duration=duration,
        note=note,
    )


def build_router() -> Router:
    """The moderation router. Gated by `ModuleGateMiddleware` in `bot.modules`."""
    router = Router(name="moderation")
    router.message.filter(InGroup())

    # --- warns ---------------------------------------------------------------

    @router.message(Command("warn"), _is_admin)
    async def warn_command(
        message: Message, command: CommandObject, bot: Bot, ctx: ChatContext
    ) -> None:
        resolved = await _resolve_or_explain(message, command, bot, ctx)
        if resolved is None:
            return
        target, reason = resolved
        t = translator(ctx.language)

        outcome = await moderation.warn(
            target.to_domain(ctx, _moderator_id(message)),
            reason=reason,
            config=ctx.moderation,
        )
        lines = [t("warn-issued", user=target.name, count=outcome.count, limit=outcome.limit)]
        punishment, duration = apply_outcome(ctx, target.tg_user_id, outcome)
        if punishment == PunishmentType.BAN.value:
            lines.append(t("warn-punishment-ban"))
        elif punishment == PunishmentType.MUTE.value:
            lines.append(
                t("warn-punishment-mute", duration=duration)
                if duration
                else t("warn-punishment-mute-forever")
            )
        await answer(message, "\n".join(lines))
        await _report(ctx, message, action="warn", target=target, reason=reason, duration=duration)
        _drop_command(ctx, message)

    @router.message(Command("unwarn"), _is_admin)
    async def unwarn_command(
        message: Message, command: CommandObject, bot: Bot, ctx: ChatContext
    ) -> None:
        resolved = await _resolve_or_explain(message, command, bot, ctx)
        if resolved is None:
            return
        target, _ = resolved
        remaining = await moderation.unwarn(target.to_domain(ctx, _moderator_id(message)))
        await answer(
            message,
            translator(ctx.language)("unwarn-done", user=target.name, count=remaining),
        )
        await _report(ctx, message, action="unwarn", target=target)
        _drop_command(ctx, message)

    @router.message(Command("warns"))
    async def warns_command(
        message: Message, command: CommandObject, bot: Bot, ctx: ChatContext
    ) -> None:
        """Anyone may read their own count; only admins may read someone else's."""
        author = message.from_user
        if author is None:
            return
        t = translator(ctx.language)
        reference, _ = split_argument(command.args)
        about_other = bool(reference) or message.reply_to_message is not None

        if not about_other:
            count = await moderation.warn_count(ctx.chat_id, author.id)
            await answer(
                message,
                t("warns-own", count=count, limit=ctx.moderation.warn_limit),
                ttl=WARNS_TTL,
            )
            return

        if not await _is_admin(message, ctx=ctx):
            await answer(message, t("moderation-forbidden"), ttl=WARNS_TTL)
            return
        resolved = await _resolve_or_explain(message, command, bot, ctx)
        if resolved is None:
            return
        target, _ = resolved
        count = await moderation.warn_count(ctx.chat_id, target.tg_user_id)
        await answer(
            message,
            t("warns-other", user=target.name, count=count, limit=ctx.moderation.warn_limit),
        )

    # --- restrictions --------------------------------------------------------

    @router.message(Command("mute"), _is_admin)
    async def mute_command(
        message: Message, command: CommandObject, bot: Bot, ctx: ChatContext
    ) -> None:
        resolved = await _resolve_or_explain(message, command, bot, ctx)
        if resolved is None:
            return
        target, rest = resolved
        duration, reason = split_duration(rest)
        duration = duration or DEFAULT_MUTE

        outcome = await moderation.mute(
            target.to_domain(ctx, _moderator_id(message)), duration=duration, reason=reason
        )
        sender.enqueue(
            actions.mute(ctx.tg_chat_id, target.tg_user_id, parse_until(outcome.until)),
            chat_id=ctx.tg_chat_id,
            priority=SendPriority.MODERATION,
        )
        pretty = format_duration(duration)
        await answer(
            message,
            translator(ctx.language)("mute-success", user=target.name, duration=pretty),
        )
        await _report(ctx, message, action="mute", target=target, reason=reason, duration=pretty)
        _drop_command(ctx, message)

    @router.message(Command("unmute"), _is_admin)
    async def unmute_command(
        message: Message, command: CommandObject, bot: Bot, ctx: ChatContext
    ) -> None:
        resolved = await _resolve_or_explain(message, command, bot, ctx)
        if resolved is None:
            return
        target, _ = resolved
        await moderation.lift(target.to_domain(ctx, _moderator_id(message)), PunishmentType.MUTE)
        sender.enqueue(
            actions.unmute(ctx.tg_chat_id, target.tg_user_id),
            chat_id=ctx.tg_chat_id,
            priority=SendPriority.MODERATION,
        )
        await answer(message, translator(ctx.language)("unmute-success", user=target.name))
        await _report(ctx, message, action="unmute", target=target)
        _drop_command(ctx, message)

    @router.message(Command("ban"), _is_admin)
    async def ban_command(
        message: Message, command: CommandObject, bot: Bot, ctx: ChatContext
    ) -> None:
        resolved = await _resolve_or_explain(message, command, bot, ctx)
        if resolved is None:
            return
        target, rest = resolved
        duration, reason = split_duration(rest)
        t = translator(ctx.language)

        outcome = await moderation.ban(
            target.to_domain(ctx, _moderator_id(message)), duration=duration, reason=reason
        )
        sender.enqueue(
            actions.ban(ctx.tg_chat_id, target.tg_user_id, parse_until(outcome.until)),
            chat_id=ctx.tg_chat_id,
            priority=SendPriority.MODERATION,
        )
        pretty = format_duration(duration) if duration else ""
        await answer(
            message,
            t("ban-success", user=target.name, duration=pretty)
            if pretty
            else t("ban-success-forever", user=target.name),
        )
        await _report(ctx, message, action="ban", target=target, reason=reason, duration=pretty)
        _drop_command(ctx, message)

    @router.message(Command("unban"), _is_admin)
    async def unban_command(
        message: Message, command: CommandObject, bot: Bot, ctx: ChatContext
    ) -> None:
        resolved = await _resolve_or_explain(message, command, bot, ctx)
        if resolved is None:
            return
        target, _ = resolved
        await moderation.lift(target.to_domain(ctx, _moderator_id(message)), PunishmentType.BAN)
        sender.enqueue(
            actions.unban(ctx.tg_chat_id, target.tg_user_id),
            chat_id=ctx.tg_chat_id,
            priority=SendPriority.MODERATION,
        )
        await answer(message, translator(ctx.language)("unban-success", user=target.name))
        await _report(ctx, message, action="unban", target=target)
        _drop_command(ctx, message)

    @router.message(Command("kick"), _is_admin)
    async def kick_command(
        message: Message, command: CommandObject, bot: Bot, ctx: ChatContext
    ) -> None:
        resolved = await _resolve_or_explain(message, command, bot, ctx)
        if resolved is None:
            return
        target, reason = resolved
        await moderation.kick(target.to_domain(ctx, _moderator_id(message)), reason=reason)
        # A kick is a ban immediately followed by an unban; both go through the
        # sender so the pair keeps its order behind the rate limiter.
        for method in actions.kick(ctx.tg_chat_id, target.tg_user_id):
            sender.enqueue(method, chat_id=ctx.tg_chat_id, priority=SendPriority.MODERATION)
        await answer(message, translator(ctx.language)("kick-success", user=target.name))
        await _report(ctx, message, action="kick", target=target, reason=reason)
        _drop_command(ctx, message)

    # --- message and chat level ---------------------------------------------

    @router.message(Command("del"), _is_admin)
    async def delete_command(message: Message, ctx: ChatContext) -> None:
        reply = message.reply_to_message
        if reply is None:
            await answer(message, translator(ctx.language)("moderation-reply-required"))
            return
        sender.enqueue(
            actions.delete_message(ctx.tg_chat_id, reply.message_id),
            chat_id=ctx.tg_chat_id,
            priority=SendPriority.MODERATION,
        )
        _drop_command(ctx, message)
        if reply.from_user is None:
            return
        target = ResolvedTarget(tg_user_id=reply.from_user.id, name=display_name(reply.from_user))
        # The deleted text goes into the log entry: once the message is gone this
        # is the only remaining record of what was removed.
        await _report(
            ctx,
            message,
            action="delete",
            target=target,
            note=(reply.text or reply.caption or "")[:200],
        )

    @router.message(Command("ro"), _is_admin)
    async def read_only_command(message: Message, command: CommandObject, ctx: ChatContext) -> None:
        """`/ro on` closes the chat, `/ro off` opens it, `/ro 30m` does both."""
        t = translator(ctx.language)
        argument = (command.args or "").strip().lower()

        if argument in {"off", "0", "false"}:
            sender.enqueue(
                actions.set_read_only(ctx.tg_chat_id, enabled=False),
                chat_id=ctx.tg_chat_id,
                priority=SendPriority.MODERATION,
            )
            await jobs.cancel(job_id(JobName.END_READ_ONLY, ctx.tg_chat_id))
            await notify(ctx, t("read-only-off"), ephemeral=False)
            await _report(ctx, message, action="read_only", note="off")
            _drop_command(ctx, message)
            return

        duration: timedelta | None = None
        if argument and argument not in {"on", "1", "true"}:
            try:
                duration = parse_duration(argument)
            except InvalidDurationError:
                await answer(message, t("read-only-usage"))
                return

        sender.enqueue(
            actions.set_read_only(ctx.tg_chat_id, enabled=True),
            chat_id=ctx.tg_chat_id,
            priority=SendPriority.MODERATION,
        )
        if duration is None:
            await notify(ctx, t("read-only-on"), ephemeral=False)
        else:
            await jobs.schedule_in(
                JobName.END_READ_ONLY,
                duration,
                ctx.tg_chat_id,
                _id=job_id(JobName.END_READ_ONLY, ctx.tg_chat_id),
            )
            await notify(
                ctx, t("read-only-on-timed", duration=format_duration(duration)), ephemeral=False
            )
        await _report(
            ctx,
            message,
            action="read_only",
            note=format_duration(duration) if duration else "on",
        )
        _drop_command(ctx, message)

    return router


__all__ = ["DEFAULT_MUTE", "WARNS_TTL", "build_router"]
