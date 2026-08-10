"""The autoposting module: scheduled posts, listed and controlled from the chat.

Spec §5.6 — recurring or one-shot posts in the chat's timezone, optionally
pinned, optionally replacing the previous copy. Composing a post is a Mini App
job (it needs media, buttons and a calendar); this module is the in-chat view of
what is scheduled and the switch that pauses it.

DECISION: `/posts` prints the next fire time recomputed from the schedule rather
than the stored `next_run_at`. The two agree in the normal case, and when they do
not — a chat timezone changed, a worker was down over a boundary — the recomputed
value is the one that describes what will actually happen next.
"""

from __future__ import annotations

from datetime import timedelta
from html import escape
from typing import Final

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.filters import IsChatAdmin
from bot.replies import answer
from core.autopost import arm, describe, disarm, next_run
from core.context import ChatContext, chat_context
from db.models import ScheduledPost
from db.uow import UnitOfWork
from i18n.runtime import Translator, translator
from shared.enums import ModuleName
from shared.logging import get_logger
from shared.schemas.module_configs import AutopostConfig
from shared.time_utils import utc_now

logger = get_logger(__name__)

LIST_TTL: Final = timedelta(minutes=5)

# How many posts `/posts` prints before deferring to the panel.
LIST_LIMIT: Final = 15

_is_admin = IsChatAdmin()


def _when(post: ScheduledPost, *, timezone: str, t: Translator) -> str:
    """ "in 3h20m" for the next fire, or a dash when it will not fire again."""
    if not post.enabled:
        return t("post-paused")
    upcoming = next_run(post.schedule_kind, post.schedule_value, timezone=timezone)
    if upcoming is None:
        return t("post-expired")
    return upcoming.strftime("%Y-%m-%d %H:%M UTC")


def format_post(post: ScheduledPost, *, timezone: str, t: Translator) -> str:
    """One line per post: id, title, schedule, next fire."""
    title = post.title.strip() or post.content.strip().splitlines()[0][:48]
    return t(
        "post-list-row",
        id=post.id,
        title=escape(title),
        schedule=escape(describe(post.schedule_kind, post.schedule_value)),
        next=_when(post, timezone=timezone, t=t),
    )


def build_router() -> Router:
    """The autopost router. Gated by `ModuleGateMiddleware` in `bot.modules`."""
    router = Router(name="autopost")

    @router.message(Command("posts"), _is_admin)
    async def posts_command(message: Message, ctx: ChatContext) -> None:
        t = translator(ctx.language)
        config = await chat_context.config(ctx, ModuleName.AUTOPOST, AutopostConfig)
        timezone = config.timezone or ctx.timezone

        async with UnitOfWork() as uow:
            posts = await uow.posts.list_for_chat(ctx.chat_id)

        if not posts:
            await answer(message, t("post-list-empty"), ttl=LIST_TTL)
            return

        lines = [t("post-list-title", count=len(posts), limit=ctx.limits.scheduled_posts)]
        lines.extend(format_post(post, timezone=timezone, t=t) for post in posts[:LIST_LIMIT])
        if len(posts) > LIST_LIMIT:
            lines.append(t("post-list-more", count=len(posts) - LIST_LIMIT))
        if not config.enabled:
            lines.append(t("post-module-paused"))
        await answer(message, "\n".join(lines), ttl=LIST_TTL)

    @router.message(Command("postpause"), _is_admin)
    async def pause_command(message: Message, command: CommandObject, ctx: ChatContext) -> None:
        """`/postpause <id>` — stop one post without deleting what it says."""
        await _toggle(message, command, ctx, enabled=False)

    @router.message(Command("postresume"), _is_admin)
    async def resume_command(message: Message, command: CommandObject, ctx: ChatContext) -> None:
        """`/postresume <id>` — put a paused post back on its schedule."""
        await _toggle(message, command, ctx, enabled=True)

    return router


async def _toggle(
    message: Message, command: CommandObject, ctx: ChatContext, *, enabled: bool
) -> None:
    """Flip one post's `enabled` flag and re-arm (or clear) its next fire time."""
    t = translator(ctx.language)
    argument = (command.args or "").strip()
    if not argument.isdigit():
        await answer(message, t("post-toggle-usage"))
        return

    post_id = int(argument)
    config = await chat_context.config(ctx, ModuleName.AUTOPOST, AutopostConfig)
    timezone = config.timezone or ctx.timezone

    async with UnitOfWork() as uow:
        post = await uow.posts.get(ctx.chat_id, post_id)
        if post is None:
            await answer(message, t("post-not-found", id=post_id))
            return
        upcoming = (
            next_run(post.schedule_kind, post.schedule_value, timezone=timezone, after=utc_now())
            if enabled
            else None
        )
        await uow.posts.update(ctx.chat_id, post_id, enabled=enabled, next_run_at=upcoming)
        await uow.commit()

    # The row and the queue have to agree: a paused post whose job is still armed
    # would fire once more, and a resumed post with no job would wait for the
    # fifteen-minute sweep instead of its own time.
    if enabled:
        await arm(post_id, upcoming)
    else:
        await disarm(post_id)

    await answer(
        message,
        t("post-resumed", id=post_id) if enabled else t("post-paused-ok", id=post_id),
    )
    logger.info(
        "autopost.toggled",
        chat_id=ctx.chat_id,
        post_id=post_id,
        enabled=enabled,
        by=message.from_user.id if message.from_user else None,
    )


__all__ = ["LIST_LIMIT", "LIST_TTL", "build_router", "format_post"]
