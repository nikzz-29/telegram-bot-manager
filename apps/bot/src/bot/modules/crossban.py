"""Operator commands for the cross-ban network: /gban, /ungban, /gbstatus.

Spec §5.6. These are the manual half of the network — the automatic half lives in
`core.crossban`, which promotes a user once enough independent chats have banned
them for scam.

DECISION: this router is attached to the dispatcher *directly*, not through
`ModuleGateMiddleware`. Every other module is gated on the chat having it enabled
and the plan including it, but a platform operator has to be able to blacklist a
scammer from wherever they happen to find them — including a Free chat whose owner
never heard of the network. The gate here is the operator list, not the plan.

DECISION: `/gban` promotes immediately (`force=True`) rather than filing one more
report toward the threshold. An operator typing the command *is* the decision; the
threshold exists to infer one from chats that never talk to each other.
"""

from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.replies import answer
from bot.targets import ResolvedTarget, resolve, split_argument
from core.audit import audit
from core.context import ChatContext
from core.crossban import crossban
from i18n.runtime import translator
from shared.config import get_settings
from shared.errors import DomainError
from shared.logging import get_logger

logger = get_logger(__name__)


def is_operator(tg_user_id: int) -> bool:
    """Whether this account is on the platform's superadmin list."""
    return tg_user_id in get_settings().superadmin_id_list


async def _target_or_explain(
    message: Message, command: CommandObject, bot: Bot, ctx: ChatContext
) -> tuple[ResolvedTarget, str] | None:
    """Same resolution as the moderation commands: reply, @username or id."""
    reference, rest = split_argument(command.args)
    try:
        target = await resolve(message, reference, bot_id=bot.id)
    except DomainError as error:
        await answer(message, translator(ctx.language)(error.i18n_key))
        return None
    return target, rest


def build_router() -> Router:
    """The operator router. Attached ungated — see the module docstring."""
    router = Router(name="crossban")

    @router.message(Command("gban"))
    async def gban_command(
        message: Message, command: CommandObject, bot: Bot, ctx: ChatContext
    ) -> None:
        t = translator(ctx.language)
        if message.from_user is None or not is_operator(message.from_user.id):
            await answer(message, t("gban-forbidden"))
            return

        resolved = await _target_or_explain(message, command, bot, ctx)
        if resolved is None:
            return
        target, reason = resolved
        if not reason:
            # The reason is the record. A blacklist entry nobody can justify
            # later is one nobody can review on appeal either.
            await answer(message, t("gban-reason-required"))
            return

        listed, _ = await crossban.status(target.tg_user_id)
        if listed:
            await answer(message, t("gban-already", user=target.name))
            return

        await crossban.report(
            chat_id=ctx.chat_id,
            tg_user_id=target.tg_user_id,
            reason=reason,
            reported_by=message.from_user.id,
            force=True,
        )
        await answer(message, t("gban-done", user=target.name, reason=reason))
        await audit.report(
            log_channel_id=ctx.moderation.log_channel_id,
            locale=ctx.language,
            action="global_ban",
            target_name=target.name,
            target_id=target.tg_user_id,
            moderator_id=message.from_user.id,
            reason=reason,
        )
        logger.info(
            "crossban.gban",
            chat_id=ctx.chat_id,
            target_id=target.tg_user_id,
            operator_id=message.from_user.id,
        )

    @router.message(Command("ungban"))
    async def ungban_command(
        message: Message, command: CommandObject, bot: Bot, ctx: ChatContext
    ) -> None:
        t = translator(ctx.language)
        if message.from_user is None or not is_operator(message.from_user.id):
            await answer(message, t("gban-forbidden"))
            return

        resolved = await _target_or_explain(message, command, bot, ctx)
        if resolved is None:
            return
        target, _ = resolved

        if not await crossban.revoke(target.tg_user_id):
            await answer(message, t("gban-ungban-missing"))
            return

        await answer(message, t("gban-ungban-done", user=target.name))
        await audit.report(
            log_channel_id=ctx.moderation.log_channel_id,
            locale=ctx.language,
            action="global_unban",
            target_name=target.name,
            target_id=target.tg_user_id,
            moderator_id=message.from_user.id,
        )
        logger.info(
            "crossban.ungban",
            chat_id=ctx.chat_id,
            target_id=target.tg_user_id,
            operator_id=message.from_user.id,
        )

    @router.message(Command("gbstatus"))
    async def gbstatus_command(
        message: Message, command: CommandObject, bot: Bot, ctx: ChatContext
    ) -> None:
        t = translator(ctx.language)
        if message.from_user is None or not is_operator(message.from_user.id):
            await answer(message, t("gban-forbidden"))
            return

        resolved = await _target_or_explain(message, command, bot, ctx)
        if resolved is None:
            return
        target, _ = resolved

        listed, chats = await crossban.status(target.tg_user_id)
        key = "gban-status-listed" if listed else "gban-status-clean"
        await answer(message, t(key, user=target.name, chats=chats))

    return router


__all__ = ["build_router", "is_operator"]
