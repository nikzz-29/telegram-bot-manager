"""Resolving "who is this command about?".

Spec §5.1: every moderation command works two ways — as a reply to the target's
message, or with `@username` as the first argument. This module is the one place
that logic lives, so `/ban`, `/mute`, `/warn` and the rest cannot disagree about
what a target is or which targets are off-limits.

DECISION: `@username` resolves against our own `tg_users` mirror, not the Bot API.
Telegram has no "look up a user by username" method for bots at all — the mirror
(populated by the ChatContext middleware on every message) is the only way, and it
means the bot can only act on someone it has seen speak. A reply always works.

DECISION: a numeric id is accepted too. It is what the log channel prints, so an
admin reading the log can act on an entry by copying the id out of it.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Final

from aiogram.types import Message, User

from bot.facts import display_name
from core.context import ChatContext
from core.moderation import ModerationTarget
from db.uow import UnitOfWork
from shared.errors import SelfActionError, TargetNotFoundError

_USERNAME = re.compile(r"^@?([A-Za-z][A-Za-z0-9_]{4,31})$")
_NUMERIC = re.compile(r"^\d{5,15}$")

# Telegram's own "anonymous group admin" account. It authors messages sent by
# admins with anonymity on, and it must never be a moderation target.
GROUP_ANONYMOUS_BOT_ID: Final = 1_087_968_824


@dataclass(frozen=True, slots=True)
class ResolvedTarget:
    """A moderation target plus the display information the reply needs."""

    tg_user_id: int
    name: str
    message_id: int | None = None
    user: User | None = None

    def to_domain(self, ctx: ChatContext, moderator_tg_id: int) -> ModerationTarget:
        return ModerationTarget(
            chat_id=ctx.chat_id,
            tg_chat_id=ctx.tg_chat_id,
            tg_user_id=self.tg_user_id,
            moderator_tg_id=moderator_tg_id,
            display_name=self.name,
        )


async def _by_reference(reference: str) -> ResolvedTarget | None:
    """Resolve `@username` or a numeric id against the user mirror."""
    if _NUMERIC.fullmatch(reference):
        tg_user_id = int(reference)
        async with UnitOfWork() as uow:
            user = await uow.users.get(tg_user_id)
        name = ""
        if user is not None:
            name = " ".join(
                part for part in (user.first_name, user.last_name or "") if part
            ).strip()
        return ResolvedTarget(tg_user_id=tg_user_id, name=name or str(tg_user_id))

    match = _USERNAME.fullmatch(reference)
    if match is None:
        return None
    async with UnitOfWork() as uow:
        user = await uow.users.find_by_username(match.group(1))
    if user is None:
        return None
    name = " ".join(part for part in (user.first_name, user.last_name or "") if part).strip()
    return ResolvedTarget(tg_user_id=user.tg_user_id, name=name or f"@{user.username}")


async def resolve(message: Message, argument: str | None, *, bot_id: int) -> ResolvedTarget:
    """Find the target of a moderation command, or explain why there is none.

    Raises `TargetNotFoundError` when neither a reply nor a usable reference is
    present, and `SelfActionError` when the target is the moderator, the bot, or
    an anonymous admin.
    """
    target: ResolvedTarget | None = None

    reply = message.reply_to_message
    if reply is not None and reply.from_user is not None:
        target = ResolvedTarget(
            tg_user_id=reply.from_user.id,
            name=display_name(reply.from_user),
            message_id=reply.message_id,
            user=reply.from_user,
        )
    elif argument:
        target = await _by_reference(argument.split()[0])

    if target is None:
        raise TargetNotFoundError()

    if target.tg_user_id == bot_id:
        raise SelfActionError("The bot cannot moderate itself.")
    if target.tg_user_id == GROUP_ANONYMOUS_BOT_ID:
        raise SelfActionError("Anonymous admins cannot be moderated.")
    if message.from_user is not None and target.tg_user_id == message.from_user.id:
        raise SelfActionError("Moderators cannot moderate themselves.")
    return target


def split_argument(command_args: str | None) -> tuple[str | None, str]:
    """Split `@user spamming` into its reference and the free-text reason."""
    if not command_args:
        return None, ""
    parts = command_args.strip().split(maxsplit=1)
    if not parts:
        return None, ""
    head = parts[0]
    rest = parts[1] if len(parts) > 1 else ""
    if _USERNAME.fullmatch(head) or _NUMERIC.fullmatch(head):
        return head, rest.strip()
    return None, command_args.strip()


__all__ = [
    "GROUP_ANONYMOUS_BOT_ID",
    "ResolvedTarget",
    "resolve",
    "split_argument",
]
