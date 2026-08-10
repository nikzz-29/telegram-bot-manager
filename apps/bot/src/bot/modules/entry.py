"""The entry module: everything that happens when someone joins.

Spec §5.2 — captcha, greeting, new-account autoban, anti-raid. One `chat_member`
handler runs them in that order, because each step can make the next pointless:
a raid lockdown means nobody is greeted, a banned account is never challenged,
and an unsolved captcha holds the greeting back until the member is real.

DECISION: joins are read from the `chat_member` update, not from the
`new_chat_members` service message. Telegram sends the service message only for
some join paths (an invite link join produces no visible one in many setups) and
sends it again on every re-add, whereas `chat_member` fires exactly once per
membership transition and also covers joins via a request approval. It needs the
bot to be an administrator — which it must be to restrict anyone anyway.

DECISION: a member is muted *before* the challenge is sent, and the mute has no
`until_date`. Telegram would otherwise let them post in the gap, and an expiring
restriction would quietly free an account whose captcha job never ran.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.filters import Command, CommandObject
from aiogram.methods import SendMessage, SendPhoto
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    User,
)

from bot.facts import display_name, mention
from bot.filters import IsChatAdmin
from bot.middlewares.forced_subscription import CALLBACK_DATA as SUB_CALLBACK
from bot.middlewares.global_ban import is_globally_banned
from bot.replies import answer, notify, send
from core import actions, jobs
from core.audit import audit
from core.captcha import CaptchaOption, Challenge, captcha
from core.captcha import build as build_challenge
from core.context import ChatContext, chat_context
from core.crossban import crossban
from core.durations import format_duration, parse_duration
from core.entry import RaidVerdict, anti_raid, screen_account
from core.greeting import Html, render_greeting
from core.jobs import JobName, job_id
from core.sender import SendPriority, sender
from core.subscription import subscription
from db.uow import UnitOfWork
from i18n.runtime import Translator, translator
from shared.enums import AutobanAction, ModuleName, StatEventType
from shared.errors import InvalidDurationError
from shared.logging import get_logger
from shared.schemas.module_configs import CrossbanConfig
from shared.time_utils import utc_now

logger = get_logger(__name__)

CALLBACK_PREFIX: Final = "cap"

# A lockdown asked for without a duration.
DEFAULT_LOCKDOWN: Final = timedelta(minutes=15)

# How long a raid alert stays before removing itself. Longer than a routine
# notice: an admin arriving a minute late still needs to see it.
ALERT_TTL: Final = timedelta(minutes=10)

_is_admin = IsChatAdmin()


def _joined(event: ChatMemberUpdated) -> bool:
    """True when this transition is somebody *becoming* a member.

    `restricted` counts only with `is_member` set — a restricted non-member is
    someone banned from posting who is not in the chat at all.
    """
    was = event.old_chat_member.status
    now = event.new_chat_member
    if was not in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}:
        return False
    if now.status == ChatMemberStatus.MEMBER:
        return True
    return now.status == ChatMemberStatus.RESTRICTED and bool(getattr(now, "is_member", False))


def _left(event: ChatMemberUpdated) -> bool:
    """True when a member has gone — used to retire a challenge they abandoned."""
    was = event.old_chat_member.status
    now = event.new_chat_member.status
    return was not in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED} and now in {
        ChatMemberStatus.LEFT,
        ChatMemberStatus.KICKED,
    }


def callback_data(tg_user_id: int, token: str) -> str:
    """`cap:<user id>:<token>` — 64-byte limit, so keep the token short.

    The user id travels with the answer so a bystander pressing someone else's
    button is rejected instead of solving their captcha for them.
    """
    return f"{CALLBACK_PREFIX}:{tg_user_id}:{token}"


def _keyboard(tg_user_id: int, challenge: Challenge, t: Translator) -> InlineKeyboardMarkup:
    """One row for a single button, two per row for the multiple-choice kinds."""

    def label(option: CaptchaOption) -> str:
        return t(option.label) if option.label_is_key else option.label

    buttons = [
        InlineKeyboardButton(
            text=label(option), callback_data=callback_data(tg_user_id, option.token)
        )
        for option in challenge.options
    ]
    if len(buttons) == 1:
        return InlineKeyboardMarkup(inline_keyboard=[buttons])
    rows = [buttons[index : index + 2] for index in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _record(ctx: ChatContext, event_type: StatEventType, tg_user_id: int) -> None:
    """One stat row. Stage 4 reads these; writing them from day one means the
    first chart is not empty on the day statistics ship."""
    async with UnitOfWork() as uow:
        await uow.stats.add_event(chat_id=ctx.chat_id, event_type=event_type, tg_user_id=tg_user_id)


async def _has_photo(bot: Bot, tg_user_id: int) -> bool:
    """Whether the account has an avatar. A *read*, so it goes direct.

    DECISION: fails as "has a photo". The screen exists to catch throwaway
    accounts; a Bot API hiccup must not turn into a ban for someone whose avatar
    we simply could not fetch.
    """
    try:
        photos = await bot.get_user_profile_photos(user_id=tg_user_id, limit=1)
    except Exception as error:  # see the docstring: any failure reads as "has a photo"
        logger.debug("entry.photo_check_failed", user_id=tg_user_id, error=str(error))
        return True
    return photos.total_count > 0


async def _issue_captcha(ctx: ChatContext, user: User, *, reason: str = "") -> None:
    """Mute the newcomer, post the challenge, arm the timeout."""
    t = translator(ctx.language)
    timeout = timedelta(minutes=ctx.entry.captcha_timeout_minutes)
    challenge = build_challenge(ctx.entry.captcha_kind, timeout=timeout)

    sender.enqueue(
        actions.mute(ctx.tg_chat_id, user.id),
        chat_id=ctx.tg_chat_id,
        priority=SendPriority.MODERATION,
    )

    lines = [
        t(
            "captcha-greeting",
            user=mention(user),
            timeout=format_duration(timeout),
        ),
        t(challenge.prompt_key, **challenge.prompt_args),
    ]
    if reason:
        lines.insert(1, t(reason))

    sent = await sender.call(
        SendMessage(
            chat_id=ctx.tg_chat_id,
            text="\n".join(lines),
            reply_markup=_keyboard(user.id, challenge, t),
            disable_notification=True,
        ),
        chat_id=ctx.tg_chat_id,
        priority=SendPriority.SYSTEM,
    )
    if sent is None:
        # The prompt never landed, so nobody can pass a challenge that is not on
        # screen. Undo the mute rather than leave a silent member.
        sender.enqueue(
            actions.unmute(ctx.tg_chat_id, user.id),
            chat_id=ctx.tg_chat_id,
            priority=SendPriority.MODERATION,
        )
        logger.warning("entry.captcha_prompt_failed", chat_id=ctx.chat_id, user_id=user.id)
        return

    await captcha.start(
        chat_id=ctx.chat_id,
        tg_chat_id=ctx.tg_chat_id,
        tg_user_id=user.id,
        challenge=challenge,
        message_id=sent.message_id,
        ttl=timeout,
    )


def _greeting_keyboard(ctx: ChatContext) -> InlineKeyboardMarkup | None:
    if not ctx.entry.greeting_buttons:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=button.text, url=button.url)]
            for button in ctx.entry.greeting_buttons
        ]
    )


async def _greet(ctx: ChatContext, user: User) -> None:
    """Send the chat's welcome, with its media and buttons, and time its removal."""
    if not ctx.entry.greeting_enabled or not ctx.entry.greeting_text.strip():
        return

    text = render_greeting(
        ctx.entry.greeting_text,
        name=Html(mention(user)),
        chat=ctx.title,
        rules_link=ctx.entry.rules_link,
    )
    keyboard = _greeting_keyboard(ctx)
    ttl = (
        timedelta(minutes=ctx.entry.greeting_delete_after_minutes)
        if ctx.entry.greeting_delete_after_minutes
        else None
    )

    if not ctx.entry.greeting_media_file_id:
        await send(
            ctx.tg_chat_id,
            text,
            priority=SendPriority.SYSTEM,
            ttl=ttl,
            keyboard=keyboard,
        )
        return

    # A photo greeting cannot go through `replies.send`, which only builds
    # `SendMessage`; the caption carries the text instead.
    method = SendPhoto(
        chat_id=ctx.tg_chat_id,
        photo=ctx.entry.greeting_media_file_id,
        caption=text,
        reply_markup=keyboard,
        disable_notification=True,
    )
    if ttl is None:
        sender.enqueue(method, chat_id=ctx.tg_chat_id, priority=SendPriority.SYSTEM)
        return
    sent = await sender.call(method, chat_id=ctx.tg_chat_id, priority=SendPriority.SYSTEM)
    if sent is not None:
        await jobs.schedule_in(
            JobName.DELETE_MESSAGE,
            ttl,
            ctx.tg_chat_id,
            sent.message_id,
            _id=job_id(JobName.DELETE_MESSAGE, ctx.tg_chat_id, sent.message_id),
        )


def _hold(ctx: ChatContext, tg_user_id: int, until: datetime) -> None:
    """Restrict a member for the rest of a lockdown, and let Telegram release them.

    DECISION: no punishment row and no lift job. `until_date` makes the hold
    expire server-side, so an arriving raid costs one API call per account and
    nothing else — no rows to clean up, and no moderation history attached to
    people who did nothing but arrive at a bad moment.
    """
    sender.enqueue(
        actions.mute(ctx.tg_chat_id, tg_user_id, until),
        chat_id=ctx.tg_chat_id,
        priority=SendPriority.MODERATION,
    )


async def _announce_raid(ctx: ChatContext, verdict: RaidVerdict) -> None:
    """Tell the chat and the log channel that a lockdown has started.

    DECISION: the alert is posted in the chat rather than DM'd to each admin. A
    DM costs one API call per administrator and silently fails for everyone who
    has not started the bot — and in a raid the people already watching the chat
    are the ones who can act.
    """
    t = translator(ctx.language)
    await send(
        ctx.tg_chat_id,
        t(
            "raid-detected",
            joins=verdict.joins,
            seconds=verdict.window_seconds,
            duration=format_duration(verdict.lockdown_until - utc_now()),
        ),
        priority=SendPriority.MODERATION,
        ttl=ALERT_TTL,
        silent=False,
    )
    await audit.report(
        log_channel_id=ctx.moderation.log_channel_id,
        locale=ctx.language,
        action="raid",
        duration=format_duration(verdict.lockdown_until - utc_now()),
        note=t("raid-log-note", joins=verdict.joins, seconds=verdict.window_seconds),
    )


async def _crossban_join(ctx: ChatContext, user: User) -> None:
    """A blacklisted user just joined: bounce them, or say so and stand down.

    DECISION: `alert_only` exists because the network is fed by other tenants.
    A chat that wants the intelligence without delegating its bans to strangers
    gets the warning and keeps the decision.

    DECISION: the crossban config is read here rather than carried on
    `ChatContext`. It is consulted only when a blacklisted user actually joins —
    rare, and Business-only — and putting it in the context would buy a config
    lookup on every update in every chat to save one on almost none.
    """
    t = translator(ctx.language)
    config = await chat_context.config(ctx, ModuleName.CROSSBAN, CrossbanConfig)
    _, chats = await crossban.status(user.id)
    reason = t("crossban-reason", chats=chats)

    if not config.alert_only:
        sender.enqueue(
            actions.ban(ctx.tg_chat_id, user.id),
            chat_id=ctx.tg_chat_id,
            priority=SendPriority.MODERATION,
        )
        await notify(ctx, t("crossban-banned", user=mention(user), chats=chats))

    logged = await audit.report(
        log_channel_id=ctx.moderation.log_channel_id,
        locale=ctx.language,
        action="crossban_alert" if config.alert_only else "crossban",
        target_name=display_name(user),
        target_id=user.id,
        reason=reason,
    )
    if config.alert_only and not logged:
        # Alert mode with no log channel would otherwise warn nobody, which is
        # the one outcome this mode cannot have. Fall back to the chat.
        await notify(ctx, t("crossban-alert", user=mention(user), chats=chats))
    logger.info(
        "entry.crossban_join",
        chat_id=ctx.chat_id,
        user_id=user.id,
        chats=chats,
        alert_only=config.alert_only,
    )


async def _autoban(ctx: ChatContext, user: User, reasons: tuple[str, ...]) -> None:
    """Bounce a flagged account and say why, once."""
    t = translator(ctx.language)
    sender.enqueue(
        actions.ban(ctx.tg_chat_id, user.id),
        chat_id=ctx.tg_chat_id,
        priority=SendPriority.MODERATION,
    )
    await notify(
        ctx,
        t(
            "entry-autoban",
            user=mention(user),
            reason=", ".join(t(reason) for reason in reasons),
        ),
    )
    await audit.report(
        log_channel_id=ctx.moderation.log_channel_id,
        locale=ctx.language,
        action="autoban",
        target_name=display_name(user),
        target_id=user.id,
        reason=", ".join(t(reason) for reason in reasons),
    )
    logger.info("entry.autobanned", chat_id=ctx.chat_id, user_id=user.id, reasons=list(reasons))


def build_router() -> Router:
    """The entry router. Gated by `ModuleGateMiddleware` in `bot.modules`."""
    router = Router(name="entry")

    @router.chat_member()
    async def membership_changed(
        event: ChatMemberUpdated, bot: Bot, ctx: ChatContext | None
    ) -> None:
        if ctx is None:
            return
        if _left(event):
            # Retire an abandoned challenge so a rejoin starts clean and the
            # pending marker stops holding their next message.
            await captcha.discard(
                chat_id=ctx.chat_id,
                tg_chat_id=ctx.tg_chat_id,
                tg_user_id=event.new_chat_member.user.id,
            )
            return
        if not _joined(event):
            return

        user = event.new_chat_member.user
        if user.is_bot:
            # A bot added by an admin is that admin's decision, not a joiner.
            return

        await _record(ctx, StatEventType.JOIN, user.id)

        # --- cross-ban network -------------------------------------------------
        # First, and before anything that costs a round-trip: a user the network
        # already knows as a scammer should not be greeted, challenged, or
        # counted as raid pressure.
        if ctx.module_enabled(ModuleName.CROSSBAN) and await is_globally_banned(user.id):
            await _crossban_join(ctx, user)
            return

        # --- anti-raid --------------------------------------------------------
        if ctx.entry.anti_raid_enabled:
            if ctx.is_locked_down():
                _hold(ctx, user.id, ctx.lockdown_until or utc_now())
                logger.info("entry.held_by_lockdown", chat_id=ctx.chat_id, user_id=user.id)
                return
            verdict = await anti_raid.record_join(ctx.chat_id, config=ctx.entry)
            if verdict is not None:
                _hold(ctx, user.id, verdict.lockdown_until)
                await anti_raid.begin_lockdown(
                    ctx.chat_id, ctx.tg_chat_id, until=verdict.lockdown_until
                )
                await _announce_raid(ctx, verdict)
                logger.warning(
                    "entry.raid_lockdown",
                    chat_id=ctx.chat_id,
                    joins=verdict.joins,
                    until=verdict.lockdown_until.isoformat(),
                )
                return

        # --- new-account screen ----------------------------------------------
        forced_reason = ""
        if ctx.entry.autoban_new_accounts:
            has_photo = await _has_photo(bot, user.id) if ctx.entry.autoban_require_photo else True
            screening = screen_account(
                tg_user_id=user.id,
                username=user.username,
                has_photo=has_photo,
                is_bot=user.is_bot,
                config=ctx.entry,
            )
            if screening:
                if ctx.entry.autoban_action is AutobanAction.BAN:
                    await _autoban(ctx, user, screening.reasons)
                    return
                forced_reason = screening.reasons[0]

        # --- captcha ----------------------------------------------------------
        if ctx.entry.captcha_enabled or forced_reason:
            await _issue_captcha(ctx, user, reason=forced_reason)
            return

        # --- greeting ---------------------------------------------------------
        await _greet(ctx, user)

    @router.callback_query(F.data.startswith(f"{CALLBACK_PREFIX}:"))
    async def captcha_pressed(query: CallbackQuery, ctx: ChatContext | None) -> None:
        if ctx is None or query.data is None:
            return
        t = translator(ctx.language)
        try:
            _, raw_id, token = query.data.split(":", 2)
            target_id = int(raw_id)
        except ValueError:
            await query.answer()
            return

        presser = query.from_user
        if presser.id != target_id:
            # Somebody else's gate. Say so quietly rather than counting it as a
            # wrong answer against the person being challenged.
            await query.answer(t("captcha-not-yours"), show_alert=True)
            return

        result = await captcha.verify(
            chat_id=ctx.chat_id,
            tg_chat_id=ctx.tg_chat_id,
            tg_user_id=target_id,
            token=token,
        )
        if result.unknown:
            await query.answer(t("captcha-expired"), show_alert=True)
            return

        if result.solved:
            await query.answer(t("captcha-solved"))
            sender.enqueue(
                actions.unmute(ctx.tg_chat_id, target_id),
                chat_id=ctx.tg_chat_id,
                priority=SendPriority.MODERATION,
            )
            if result.message_id is not None:
                sender.enqueue(
                    actions.delete_message(ctx.tg_chat_id, result.message_id),
                    chat_id=ctx.tg_chat_id,
                    priority=SendPriority.SYSTEM,
                )
            await _record(ctx, StatEventType.CAPTCHA_PASSED, target_id)
            await audit.report(
                log_channel_id=ctx.moderation.log_channel_id,
                locale=ctx.language,
                action="captcha_passed",
                target_name=display_name(presser),
                target_id=target_id,
            )
            await _greet(ctx, presser)
            logger.info("entry.captcha_passed", chat_id=ctx.chat_id, user_id=target_id)
            return

        if result.retry:
            await query.answer(t("captcha-wrong", remaining=result.remaining), show_alert=True)
            return

        # Out of attempts. Three wrong presses is an answer, not an absence, so
        # this kicks regardless of `captcha_kick_on_timeout` — which governs the
        # user who never pressed anything at all.
        await query.answer(t("captcha-failed"), show_alert=True)
        for method in actions.kick(ctx.tg_chat_id, target_id):
            sender.enqueue(method, chat_id=ctx.tg_chat_id, priority=SendPriority.MODERATION)
        if result.message_id is not None:
            sender.enqueue(
                actions.delete_message(ctx.tg_chat_id, result.message_id),
                chat_id=ctx.tg_chat_id,
                priority=SendPriority.SYSTEM,
            )
        await jobs.cancel(job_id(JobName.CAPTCHA_TIMEOUT, ctx.tg_chat_id, target_id))
        await _record(ctx, StatEventType.CAPTCHA_FAILED, target_id)
        await audit.report(
            log_channel_id=ctx.moderation.log_channel_id,
            locale=ctx.language,
            action="captcha_failed",
            target_name=display_name(presser),
            target_id=target_id,
            reason=t("captcha-failed-attempts", attempts=result.attempts),
        )
        logger.info("entry.captcha_failed", chat_id=ctx.chat_id, user_id=target_id)

    @router.callback_query(F.data == SUB_CALLBACK)
    async def subscription_checked(query: CallbackQuery, ctx: ChatContext | None) -> None:
        """ "I joined" on the forced-subscription prompt — re-check immediately.

        DECISION: the cached verdict is dropped before the re-check. It is a "no"
        by construction (nobody sees this button otherwise) and it lives for a
        minute, so honouring it would make the button do nothing for the very
        person who just did what it asked.
        """
        if ctx is None:
            return
        t = translator(ctx.language)
        channel_id = subscription.required(ctx.entry)
        if channel_id is None:
            await query.answer(t("forced-sub-open"))
            return

        user = query.from_user
        await subscription.forget(ctx.chat_id, user.id)
        if not await subscription.is_subscribed(ctx.chat_id, user.id, channel_id=channel_id):
            await query.answer(t("forced-sub-still-missing"), show_alert=True)
            return

        await query.answer(t("forced-sub-thanks"))
        if query.message is not None:
            sender.enqueue(
                actions.delete_message(ctx.tg_chat_id, query.message.message_id),
                chat_id=ctx.tg_chat_id,
                priority=SendPriority.SYSTEM,
            )
        logger.info("forced_sub.passed", chat_id=ctx.chat_id, user_id=user.id)

    @router.message(Command("lockdown"), _is_admin)
    async def lockdown_command(message: Message, command: CommandObject, ctx: ChatContext) -> None:
        """`/lockdown [30m|off]` — close the door by hand.

        DECISION: `off` clears the window but does not release the members held
        during it. Their restriction carries its own `until_date`; lifting those
        early is what `/unmute` is for, and doing it wholesale would hand the
        floor back to exactly the accounts the lockdown was called on.
        """
        t = translator(ctx.language)
        argument = (command.args or "").strip().lower()

        if argument in {"off", "0", "stop"}:
            await anti_raid.end_lockdown(ctx.chat_id, ctx.tg_chat_id)
            await answer(message, t("lockdown-off"))
            await audit.report(
                log_channel_id=ctx.moderation.log_channel_id,
                locale=ctx.language,
                action="lockdown_off",
                moderator_name=display_name(message.from_user),
                moderator_id=message.from_user.id if message.from_user else None,
            )
            return

        if argument:
            try:
                duration = parse_duration(argument)
            except InvalidDurationError as error:
                await answer(message, t(error.i18n_key))
                return
        else:
            duration = timedelta(minutes=ctx.entry.anti_raid_lockdown_minutes or 15)

        until = utc_now() + duration
        await anti_raid.begin_lockdown(ctx.chat_id, ctx.tg_chat_id, until=until)
        await answer(message, t("lockdown-on", duration=format_duration(duration)))
        await audit.report(
            log_channel_id=ctx.moderation.log_channel_id,
            locale=ctx.language,
            action="lockdown",
            moderator_name=display_name(message.from_user),
            moderator_id=message.from_user.id if message.from_user else None,
            duration=format_duration(duration),
        )
        logger.info(
            "entry.lockdown_manual",
            chat_id=ctx.chat_id,
            until=until.isoformat(),
            by=message.from_user.id if message.from_user else None,
        )

    return router


__all__ = ["build_router", "callback_data"]
