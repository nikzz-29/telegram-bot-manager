"""The engagement module: reputation, levels and trigger rules.

Spec §5.6 groups the three because they share one hook — a plain message that
nobody addressed to the bot. A `+` in reply to someone is a reputation grant, the
message itself is experience towards a level, and its text may fire a trigger.

DECISION: one passive handler runs all three in that order and then re-raises
`SkipHandler`. Splitting them into three handlers would mean three passes over
the same message and three chances to accidentally swallow it; running them
together means the common case — a message that is none of the three — costs one
config read and nothing else.

DECISION: reputation, levels and triggers are gated individually inside the
handler, not by the module gate. They are three separate `Feature` keys that
happen to share a module, so a plan that unlocks one must not silently switch on
the others.
"""

from __future__ import annotations

from datetime import timedelta
from html import escape
from typing import Any, Final

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.facts import facts_from, mention
from bot.filters import IsChatAdmin
from bot.replies import answer, send
from core import actions
from core.context import ChatContext, chat_context
from core.reputation import (
    is_thanks,
    level_title,
    next_level_progress,
    reputation,
)
from core.sender import SendPriority, sender
from core.triggers import TriggerDef, triggers, validate_pattern
from db.uow import UnitOfWork
from i18n.runtime import Translator, translator
from shared.enums import ModuleName, TriggerMatch
from shared.errors import InvalidPatternError
from shared.logging import get_logger
from shared.plans import Feature
from shared.schemas.module_configs import EngagementConfig

logger = get_logger(__name__)

# `/addtrigger спасибо | Пожалуйста!` — the separator between the phrase and the
# answer. A pipe cannot appear in a Telegram command name and reads clearly in
# both languages, which `->` and `=` do not.
SEPARATOR: Final = "|"

# A level-up announcement removes itself; a leaderboard does not.
LEVEL_UP_TTL: Final = timedelta(minutes=2)
BOARD_TTL: Final = timedelta(minutes=5)

# How many rules `/triggers` prints before it tells the admin to open the panel.
LIST_LIMIT: Final = 20

_is_admin = IsChatAdmin()


def _buttons(raw: list[dict[str, Any]]) -> InlineKeyboardMarkup | None:
    """Rebuild a trigger's inline keyboard from its stored JSON."""
    rows = [
        [InlineKeyboardButton(text=str(button["text"]), url=str(button["url"]))]
        for button in raw
        if button.get("text") and button.get("url")
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def _match_kind(pattern: str) -> tuple[str, TriggerMatch]:
    """`re:^hi` asks for a regular expression; anything else is a substring.

    DECISION: the prefix exists so the common case stays one line. An admin
    writing `/addtrigger привет | Привет!` should not have to learn a flag, and
    the Mini App exposes all three modes properly anyway.
    """
    if pattern.startswith("re:"):
        return pattern[3:].strip(), TriggerMatch.REGEX
    if pattern.startswith("="):
        return pattern[1:].strip(), TriggerMatch.EXACT
    return pattern, TriggerMatch.CONTAINS


async def _fire_trigger(ctx: ChatContext, message: Message, definition: TriggerDef) -> None:
    """Answer a matched trigger and count the hit."""
    async with UnitOfWork() as uow:
        rule = await uow.triggers.get(ctx.chat_id, definition.id)
        if rule is None or not rule.enabled:
            # The rule went away between the cached match and this read.
            await triggers.invalidate(ctx.chat_id)
            return
        response = rule.response
        buttons = list(rule.buttons)
        delete_trigger = rule.delete_trigger
        await uow.triggers.increment_hits(rule.id)
        await uow.commit()

    if delete_trigger:
        sender.enqueue(
            actions.delete_message(ctx.tg_chat_id, message.message_id),
            chat_id=ctx.tg_chat_id,
            priority=SendPriority.MODERATION,
        )

    await send(
        ctx.tg_chat_id,
        response,
        reply_to=None if delete_trigger else message.message_id,
        priority=SendPriority.REPLY,
        keyboard=_buttons(buttons),
    )
    logger.debug("triggers.fired", chat_id=ctx.chat_id, trigger_id=definition.id)


async def _handle_thanks(ctx: ChatContext, message: Message, config: EngagementConfig) -> None:
    """A `+` in reply to somebody: one reputation point, if the guards allow."""
    reply = message.reply_to_message
    giver = message.from_user
    if reply is None or reply.from_user is None or giver is None:
        return

    result = await reputation.grant(
        chat_id=ctx.chat_id,
        giver_id=giver.id,
        receiver_id=reply.from_user.id,
        receiver_is_bot=reply.from_user.is_bot,
        config=config,
    )
    if not result.granted:
        # Silent by design — see the `core.reputation` module docstring.
        return

    t = translator(ctx.language)
    await send(
        ctx.tg_chat_id,
        t("rep-granted", user=mention(reply.from_user), points=result.points),
        reply_to=message.message_id,
        priority=SendPriority.REPLY,
        ttl=LEVEL_UP_TTL,
    )


async def _award_activity(ctx: ChatContext, message: Message, config: EngagementConfig) -> None:
    """Experience for a message, and a congratulation when it buys a level."""
    author = message.from_user
    if author is None:
        return
    result = await reputation.add_activity(chat_id=ctx.chat_id, tg_user_id=author.id, config=config)
    if result is None or not result.level_up:
        return

    t = translator(ctx.language)
    title = level_title(result.level, config)
    await send(
        ctx.tg_chat_id,
        t(
            "level-up-titled" if title else "level-up",
            user=mention(author),
            level=result.level,
            title=escape(title),
        ),
        priority=SendPriority.REPLY,
        ttl=LEVEL_UP_TTL,
    )


def _standing_lines(
    *,
    who: str,
    points: int,
    experience: int,
    level: int,
    rank: int | None,
    config: EngagementConfig,
    t: Translator,
) -> list[str]:
    title = level_title(level, config)
    lines = [t("rep-standing", user=who, points=points)]
    if config.levels_enabled:
        lines.append(
            t("rep-level-titled", level=level, title=escape(title))
            if title
            else t("rep-level", level=level)
        )
        earned, needed = next_level_progress(experience)
        if needed:
            lines.append(t("rep-progress", earned=earned, needed=needed))
    if rank is not None:
        lines.append(t("rep-rank", place=rank))
    return lines


async def _names_for(tg_user_ids: list[int]) -> dict[int, str]:
    """Display names for a leaderboard, from the profile mirror."""
    if not tg_user_ids:
        return {}
    async with UnitOfWork() as uow:
        users = await uow.users.get_many(tg_user_ids)
    names: dict[int, str] = {}
    for tg_user_id, user in users.items():
        full = " ".join(part for part in (user.first_name, user.last_name or "") if part).strip()
        names[tg_user_id] = full or (f"@{user.username}" if user.username else str(tg_user_id))
    return names


def build_router() -> Router:
    """The engagement router. Gated by `ModuleGateMiddleware` in `bot.modules`."""
    router = Router(name="engagement")

    @router.message(Command("rep"))
    async def rep_command(message: Message, command: CommandObject, ctx: ChatContext) -> None:
        if not ctx.has(Feature.REPUTATION):
            return
        config = await chat_context.config(ctx, ModuleName.ENGAGEMENT, EngagementConfig)
        if not config.reputation_enabled:
            return

        reply = message.reply_to_message
        target = reply.from_user if reply is not None else message.from_user
        if target is None:
            return

        points, experience, level, rank = await reputation.standing(ctx.chat_id, target.id)
        await answer(
            message,
            "\n".join(
                _standing_lines(
                    who=mention(target),
                    points=points,
                    experience=experience,
                    level=level,
                    rank=rank,
                    config=config,
                    t=translator(ctx.language),
                )
            ),
            ttl=BOARD_TTL,
        )

    @router.message(Command("top"))
    async def top_command(message: Message, command: CommandObject, ctx: ChatContext) -> None:
        if not ctx.has(Feature.REPUTATION):
            return
        config = await chat_context.config(ctx, ModuleName.ENGAGEMENT, EngagementConfig)
        if not config.reputation_enabled:
            return

        argument = (command.args or "").strip().lower()
        by_level = argument in {"level", "levels", "уровень", "уровни"}
        field = "experience" if by_level else "points"
        rows = await reputation.leaderboard(ctx.chat_id, limit=10, field=field)

        t = translator(ctx.language)
        if not rows:
            await answer(message, t("rep-top-empty"), ttl=BOARD_TTL)
            return

        names = await _names_for([tg_user_id for tg_user_id, _, _ in rows])
        lines = [t("rep-top-title-level" if by_level else "rep-top-title")]
        for place, (tg_user_id, points, level) in enumerate(rows, start=1):
            label = escape(names.get(tg_user_id, str(tg_user_id)))
            lines.append(
                t(
                    "rep-top-row-level" if by_level else "rep-top-row",
                    place=place,
                    user=label,
                    points=points,
                    level=level,
                )
            )
        await answer(message, "\n".join(lines), ttl=BOARD_TTL)

    @router.message(Command("triggers"), _is_admin)
    async def triggers_command(message: Message, ctx: ChatContext) -> None:
        t = translator(ctx.language)
        async with UnitOfWork() as uow:
            rules = await uow.triggers.list_for_chat(ctx.chat_id)

        if not rules:
            await answer(message, t("trigger-list-empty"))
            return

        lines = [t("trigger-list-title", count=len(rules), limit=ctx.limits.triggers)]
        for rule in rules[:LIST_LIMIT]:
            lines.append(
                t(
                    "trigger-list-row",
                    id=rule.id,
                    pattern=escape(rule.pattern),
                    match=rule.match.value,
                    hits=rule.hits,
                    state=t("state-on" if rule.enabled else "state-off"),
                )
            )
        if len(rules) > LIST_LIMIT:
            lines.append(t("trigger-list-more", count=len(rules) - LIST_LIMIT))
        await answer(message, "\n".join(lines), ttl=BOARD_TTL)

    @router.message(Command("addtrigger"), _is_admin)
    async def add_trigger_command(
        message: Message, command: CommandObject, ctx: ChatContext
    ) -> None:
        t = translator(ctx.language)
        raw = (command.args or "").strip()
        if SEPARATOR not in raw:
            await answer(message, t("trigger-usage", separator=SEPARATOR))
            return

        head, _, response = raw.partition(SEPARATOR)
        pattern, match = _match_kind(head.strip())
        response = response.strip()
        if not response:
            await answer(message, t("trigger-usage", separator=SEPARATOR))
            return

        try:
            pattern = validate_pattern(pattern, match)
        except InvalidPatternError as error:
            await answer(message, t(error.i18n_key))
            return

        limit = ctx.limits.triggers
        async with UnitOfWork() as uow:
            if await uow.triggers.count(ctx.chat_id) >= limit:
                await answer(message, t("limit-triggers", limit=limit))
                logger.info("triggers.limit_reached", chat_id=ctx.chat_id, limit=limit)
                return
            rule = await uow.triggers.create(
                ctx.chat_id,
                pattern=pattern,
                match=match,
                response=response,
            )
            await uow.commit()
            trigger_id = rule.id

        await triggers.invalidate(ctx.chat_id)
        await answer(message, t("trigger-added", id=trigger_id, pattern=escape(pattern)))
        logger.info(
            "triggers.created",
            chat_id=ctx.chat_id,
            trigger_id=trigger_id,
            by=message.from_user.id if message.from_user else None,
        )

    @router.message(Command("deltrigger"), _is_admin)
    async def delete_trigger_command(
        message: Message, command: CommandObject, ctx: ChatContext
    ) -> None:
        t = translator(ctx.language)
        argument = (command.args or "").strip()
        if not argument.isdigit():
            await answer(message, t("trigger-delete-usage"))
            return

        trigger_id = int(argument)
        async with UnitOfWork() as uow:
            removed = await uow.triggers.delete(ctx.chat_id, trigger_id)
            await uow.commit()

        if not removed:
            await answer(message, t("trigger-not-found", id=trigger_id))
            return
        await triggers.invalidate(ctx.chat_id)
        await answer(message, t("trigger-deleted", id=trigger_id))
        logger.info("triggers.deleted", chat_id=ctx.chat_id, trigger_id=trigger_id)

    @router.message(F.chat.type.in_({"group", "supergroup"}))
    async def engage(message: Message, ctx: ChatContext, **_: Any) -> None:
        """Reputation, experience and triggers for one ordinary message.

        Always raises `SkipHandler`: this handler exists for its side effects, and
        the update still belongs to whatever router comes after it.
        """
        author = message.from_user
        if author is None or author.is_bot:
            raise SkipHandler

        facts = facts_from(message)
        if facts.is_service:
            raise SkipHandler

        config = await chat_context.config(ctx, ModuleName.ENGAGEMENT, EngagementConfig)

        if (
            config.reputation_enabled
            and ctx.has(Feature.REPUTATION)
            and is_thanks(facts.text, config)
        ):
            await _handle_thanks(ctx, message, config)

        if config.levels_enabled and ctx.has(Feature.LEVELS):
            await _award_activity(ctx, message, config)

        if config.triggers_enabled and facts.text:
            definition = await triggers.match(ctx.chat_id, facts.text)
            if definition is not None:
                await _fire_trigger(ctx, message, definition)

        raise SkipHandler

    return router


__all__ = ["BOARD_TTL", "LEVEL_UP_TTL", "LIST_LIMIT", "SEPARATOR", "build_router"]
