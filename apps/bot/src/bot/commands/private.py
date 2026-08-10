"""Private-chat commands: the bot's front door and the whole DM surface.

Everything here runs in a DM, where there is no `ChatContext` — no plan, no
module switches, no moderation config. This is where the person behind the bot
lives: their profile, the chats they administer, what the plans cost, and the
flow that puts one of those chats onto one of those plans.

DECISION: settings are still not editable from chat. Spec §6 puts the whole
control surface in the Mini App; a second, divergent way to change the same
values is how "the button says X but the bot does Y" bugs are born. What lives
here is everything that is *not* a setting — identity, status and buying — which
is exactly the part a user cannot reach from the panel, because the panel is for
operators.

DECISION: no `/language`. The bot already answers in the account's Telegram
language, and a second stored preference would be a setting — the thing this
module deliberately does not own. Per-chat language is a panel setting; the
panel's own UI language follows the same Telegram value.

DECISION: the purchase flow is inline keyboards, not an FSM. Each press carries
its whole state in the callback data (`dm:buy:pro:42:3` is plan, chat and term),
so a user who opens two flows, or comes back to a button an hour later, gets a
correct invoice rather than whatever a stored step said. Telegram caps callback
data at 64 bytes; the longest value this builds is well inside it.
"""

from __future__ import annotations

from typing import Final

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    User,
    WebAppInfo,
)

from bot import access
from bot.replies import send
from core.billing import MAX_MONTHS, billing
from core.sender import SendPriority
from db.models import Chat
from db.uow import UnitOfWork
from i18n.runtime import Translator, normalize_locale, translator
from shared.config import get_settings
from shared.enums import PaymentProvider, Plan
from shared.errors import DomainError
from shared.logging import get_logger
from shared.plans import PLAN_PRICES, PURCHASABLE_PLANS

logger = get_logger(__name__)

# Each prefix is one step of the purchase, and the step's whole state rides in
# the data after it. `dm:` namespaces them away from the captcha and forced-
# subscription callbacks, which are group-side and parse their own formats.
CB_PLANS: Final = "dm:plans"
CB_PROFILE: Final = "dm:profile"
CB_CHATS: Final = "dm:chats"
CB_CHAT: Final = "dm:chat"  # dm:chat:<plan> — which chat is this plan for?
CB_TERM: Final = "dm:term"  # dm:term:<plan>:<chat_id> — for how long?
CB_BUY: Final = "dm:buy"  # dm:buy:<plan>:<chat_id>:<months> — mint the invoice

# The terms offered in chat. The panel offers the same three; `MAX_MONTHS` is
# the ceiling both are checked against at settlement.
TERMS: Final[tuple[int, ...]] = (1, 3, 12)

# How many chats a profile lists before it says "and N more" — a profile has to
# stay one screen tall, and `/chats` is the full list.
PROFILE_CHAT_PREVIEW: Final = 3


# --- shared shaping ---------------------------------------------------------
# Every one of these is called from both a command and the callback that does
# the same thing, so the two can never drift into saying different things.


def _locale(user: User | None) -> str:
    """A DM has no chat language, so the sender's Telegram locale decides."""
    return normalize_locale(user.language_code if user else None)


def _display_name(user: User, t: Translator) -> str:
    """Full name, or `@username`, or the bare id — whichever exists first."""
    full = " ".join(part for part in (user.first_name, user.last_name) if part).strip()
    if full:
        return full
    if user.username:
        return f"@{user.username}"
    return t("dm-profile-anonymous", id=str(user.id))


def _chat_title(chat: Chat, t: Translator) -> str:
    return chat.title or t("dm-chat-untitled")


async def _chats_for(tg_user_id: int) -> list[Chat]:
    async with UnitOfWork() as uow:
        return await uow.chats.list_for_admin(tg_user_id)


def _profile_text(user: User, chats: list[Chat], t: Translator) -> str:
    lines = [
        t("dm-profile-header", name=_display_name(user, t)),
        # DECISION: the id goes in as a string. Fluent formats a bare number for
        # the locale — `111 222 333` in ru, `111,222,333` in en — which is right
        # for a price and wrong for an identifier sitting in a <code> block that
        # exists to be copied and pasted back to support.
        t("dm-profile-id", id=str(user.id)),
        "",
        t("dm-profile-chats", count=len(chats)),
    ]
    lines.extend(f"• {_chat_title(chat, t)}" for chat in chats[:PROFILE_CHAT_PREVIEW])
    if len(chats) > PROFILE_CHAT_PREVIEW:
        lines.append(t("dm-profile-more", count=len(chats) - PROFILE_CHAT_PREVIEW))
    return "\n".join(lines)


def _chats_text(chats: list[Chat], t: Translator) -> str:
    """One line per chat: its title, its plan, and when that plan lapses."""
    if not chats:
        return t("dm-chats-empty")
    lines = [t("dm-chats-header", count=len(chats)), ""]
    for chat in chats:
        plan = t(f"plan-{chat.plan.value}")
        if chat.plan is Plan.FREE or chat.plan_expires_at is None:
            lines.append(t("dm-chats-row-free", chat=_chat_title(chat, t), plan=plan))
        else:
            lines.append(
                t(
                    "dm-chats-row",
                    chat=_chat_title(chat, t),
                    plan=plan,
                    until=chat.plan_expires_at.strftime("%d.%m.%Y"),
                )
            )
    return "\n".join(lines)


def _plans_text(t: Translator) -> str:
    lines = [t("dm-plans-header"), ""]
    for plan in PURCHASABLE_PLANS:
        price = PLAN_PRICES[plan]
        lines.append(
            t("dm-plans-row", plan=t(f"plan-{plan.value}"), stars=price.stars, usd=price.usd)
        )
    lines.extend(("", t("dm-plans-hint", months=MAX_MONTHS)))
    return "\n".join(lines)


# --- keyboards --------------------------------------------------------------


def _panel_keyboard(locale: str) -> InlineKeyboardMarkup | None:
    """The Mini App button, or `None` when no Mini App URL is configured."""
    url = get_settings().webapp_url
    if not url:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=translator(locale)("open-miniapp"), web_app=WebAppInfo(url=url)
                )
            ]
        ]
    )


def _plans_keyboard(t: Translator) -> InlineKeyboardMarkup:
    """One button per purchasable plan, priced at its monthly rate."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(
                        "dm-plans-button",
                        plan=t(f"plan-{plan.value}"),
                        stars=PLAN_PRICES[plan].stars,
                    ),
                    callback_data=f"{CB_CHAT}:{plan.value}",
                )
            ]
            for plan in PURCHASABLE_PLANS
        ]
    )


def _chat_keyboard(plan: Plan, chats: list[Chat], t: Translator) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_chat_title(chat, t),
                    callback_data=f"{CB_TERM}:{plan.value}:{chat.id}",
                )
            ]
            for chat in chats
        ]
    )


def _term_keyboard(plan: Plan, chat_id: int, t: Translator) -> InlineKeyboardMarkup:
    stars = PLAN_PRICES[plan].stars
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("dm-term-button", months=months, stars=stars * months),
                    callback_data=f"{CB_BUY}:{plan.value}:{chat_id}:{months}",
                )
            ]
            for months in TERMS
        ]
    )


def _profile_keyboard(t: Translator) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t("dm-chats-button"), callback_data=CB_CHATS),
                InlineKeyboardButton(text=t("dm-plans-button-short"), callback_data=CB_PLANS),
            ]
        ]
    )


def _chats_keyboard(t: Translator) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t("dm-plans-button-short"), callback_data=CB_PLANS)]
        ]
    )


# --- parsing ----------------------------------------------------------------


def _parse_plan(raw: str) -> Plan | None:
    """A plan name from callback data, or `None` when it is not one we sell."""
    try:
        plan = Plan(raw)
    except ValueError:
        return None
    return plan if plan in PURCHASABLE_PLANS else None


def build_router() -> Router:
    """Commands and inline flows that answer in a private chat only."""
    router = Router(name="private")
    router.message.filter(F.chat.type == "private")
    # Every callback below is answered from a DM the bot itself sent, so the
    # filter is a guard against a button somehow surviving into a group rather
    # than a routing rule.
    router.callback_query.filter(F.message.chat.type == "private")

    # --- entry points ------------------------------------------------------
    @router.message(CommandStart())
    async def start_command(message: Message) -> None:
        locale = _locale(message.from_user)
        await send(
            message.chat.id,
            translator(locale)("start-welcome"),
            priority=SendPriority.REPLY,
            silent=False,
            keyboard=_profile_keyboard(translator(locale)),
        )

    @router.message(Command("help"))
    async def help_command(message: Message) -> None:
        await send(
            message.chat.id,
            translator(_locale(message.from_user))("help-text"),
            priority=SendPriority.REPLY,
            silent=False,
        )

    # --- the operator's panel ----------------------------------------------
    @router.message(Command("admin"))
    async def admin_command(message: Message) -> None:
        """The only route into the Mini App — see `bot.access`.

        DECISION: a refusal answers rather than staying silent. The command is
        published to every private chat, so a user who types it deserves to be
        told the panel is not for them; silence reads as a broken bot, and the
        text says nothing an operator list would not already imply.
        """
        if message.from_user is None:
            return
        locale = _locale(message.from_user)
        t = translator(locale)
        if not access.may_open_panel(message.from_user.id):
            logger.info("panel.access_denied", user_id=message.from_user.id)
            await send(
                message.chat.id, t("admin-forbidden"), priority=SendPriority.REPLY, silent=False
            )
            return
        logger.info("panel.access_granted", user_id=message.from_user.id)
        await send(
            message.chat.id,
            t("admin-welcome"),
            priority=SendPriority.REPLY,
            silent=False,
            keyboard=_panel_keyboard(locale),
        )

    # --- the user's own surface ---------------------------------------------
    @router.message(Command("profile"))
    async def profile_command(message: Message) -> None:
        if message.from_user is None:
            return
        t = translator(_locale(message.from_user))
        chats = await _chats_for(message.from_user.id)
        await send(
            message.chat.id,
            _profile_text(message.from_user, chats, t),
            priority=SendPriority.REPLY,
            silent=False,
            keyboard=_profile_keyboard(t),
        )

    @router.message(Command("chats"))
    async def chats_command(message: Message) -> None:
        if message.from_user is None:
            return
        t = translator(_locale(message.from_user))
        chats = await _chats_for(message.from_user.id)
        await send(
            message.chat.id,
            _chats_text(chats, t),
            priority=SendPriority.REPLY,
            silent=False,
            keyboard=_chats_keyboard(t) if chats else None,
        )

    # `/pay` is the same screen as `/plans` reached from the other direction —
    # one wants to know the price, the other has already decided.
    @router.message(Command("plans", "pay"))
    async def plans_command(message: Message) -> None:
        t = translator(_locale(message.from_user))
        await send(
            message.chat.id,
            _plans_text(t),
            priority=SendPriority.REPLY,
            silent=False,
            keyboard=_plans_keyboard(t),
        )

    # --- the same three screens, reached by button --------------------------
    # Each answers the query first: the toast is how Telegram stops the button's
    # spinner, and it must happen whether or not the work below succeeds.

    @router.callback_query(F.data == CB_PROFILE)
    async def profile_pressed(query: CallbackQuery) -> None:
        await query.answer()
        if query.message is None:
            return
        t = translator(_locale(query.from_user))
        chats = await _chats_for(query.from_user.id)
        await send(
            query.message.chat.id,
            _profile_text(query.from_user, chats, t),
            priority=SendPriority.REPLY,
            keyboard=_profile_keyboard(t),
        )

    @router.callback_query(F.data == CB_CHATS)
    async def chats_pressed(query: CallbackQuery) -> None:
        await query.answer()
        if query.message is None:
            return
        t = translator(_locale(query.from_user))
        chats = await _chats_for(query.from_user.id)
        await send(
            query.message.chat.id,
            _chats_text(chats, t),
            priority=SendPriority.REPLY,
            keyboard=_chats_keyboard(t) if chats else None,
        )

    @router.callback_query(F.data == CB_PLANS)
    async def plans_pressed(query: CallbackQuery) -> None:
        await query.answer()
        if query.message is None:
            return
        t = translator(_locale(query.from_user))
        await send(
            query.message.chat.id,
            _plans_text(t),
            priority=SendPriority.REPLY,
            keyboard=_plans_keyboard(t),
        )

    # --- the purchase, one press per decision -------------------------------
    @router.callback_query(F.data.startswith(f"{CB_CHAT}:"))
    async def chat_step(query: CallbackQuery) -> None:
        """A plan was chosen. Which chat is it for?"""
        await query.answer()
        if query.data is None or query.message is None:
            return
        plan = _parse_plan(query.data.split(":")[-1])
        if plan is None:
            return
        t = translator(_locale(query.from_user))
        chats = await _chats_for(query.from_user.id)
        if not chats:
            # The one dead end in the flow, and it is a real one: a plan is
            # bought *for a chat*, so there is nothing to sell yet.
            await send(query.message.chat.id, t("dm-buy-no-chats"), priority=SendPriority.REPLY)
            return
        await send(
            query.message.chat.id,
            t("dm-buy-choose-chat", plan=t(f"plan-{plan.value}")),
            priority=SendPriority.REPLY,
            keyboard=_chat_keyboard(plan, chats, t),
        )

    @router.callback_query(F.data.startswith(f"{CB_TERM}:"))
    async def term_step(query: CallbackQuery) -> None:
        """A chat was chosen. For how long?"""
        await query.answer()
        if query.data is None or query.message is None:
            return
        parts = query.data.split(":")
        if len(parts) != 4:
            return
        plan = _parse_plan(parts[2])
        t = translator(_locale(query.from_user))
        chat = await _authorized_chat(query.from_user.id, parts[3])
        if plan is None or chat is None:
            await send(query.message.chat.id, t("dm-buy-unknown-chat"), priority=SendPriority.REPLY)
            return
        await send(
            query.message.chat.id,
            t("dm-buy-choose-term", chat=_chat_title(chat, t), plan=t(f"plan-{plan.value}")),
            priority=SendPriority.REPLY,
            keyboard=_term_keyboard(plan, chat.id, t),
        )

    @router.callback_query(F.data.startswith(f"{CB_BUY}:"))
    async def buy_step(query: CallbackQuery) -> None:
        """Every decision is in: mint the invoice."""
        await query.answer()
        if query.data is None or query.message is None:
            return
        parts = query.data.split(":")
        if len(parts) != 5:
            return
        t = translator(_locale(query.from_user))
        plan = _parse_plan(parts[2])
        chat = await _authorized_chat(query.from_user.id, parts[3])
        months = int(parts[4]) if parts[4].isdigit() else 0
        if plan is None or chat is None or months not in TERMS:
            await send(query.message.chat.id, t("dm-buy-unknown-chat"), priority=SendPriority.REPLY)
            return

        try:
            invoice = await billing.create_invoice(
                chat, plan=plan, months=months, provider=PaymentProvider.STARS, t=t
            )
        except DomainError as error:
            # The provider is down or the plan is not for sale. Neither is
            # something the buyer can fix, so they get the generic line and the
            # detail goes to the log.
            logger.warning(
                "billing.dm_invoice_failed",
                chat_id=chat.id,
                plan=plan.value,
                months=months,
                error=str(error),
            )
            await send(
                query.message.chat.id,
                t("error-provider-unavailable"),
                priority=SendPriority.REPLY,
                silent=False,
            )
            return

        logger.info(
            "billing.dm_invoice_opened",
            chat_id=chat.id,
            plan=plan.value,
            months=months,
            user_id=query.from_user.id,
        )
        await send(
            query.message.chat.id,
            t(
                "dm-buy-invoice",
                chat=_chat_title(chat, t),
                plan=t(f"plan-{plan.value}"),
                months=months,
            ),
            priority=SendPriority.REPLY,
            silent=False,
            # DECISION: the link is a button, not text the user has to tap
            # through a preview. `create_invoice_link` returns the same URL the
            # Mini App opens with `WebApp.openInvoice`, and Telegram renders a
            # URL button onto it as its native payment sheet — so the receipt
            # comes back through `payments.confirm_payment` either way.
            keyboard=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=t("dm-buy-pay", stars=invoice.amount),
                            url=invoice.invoice_url,
                        )
                    ]
                ]
            ),
        )

    return router


async def _authorized_chat(tg_user_id: int, raw_chat_id: str) -> Chat | None:
    """The chat named by a callback, but only if this user administers it.

    DECISION: the chat is looked up through `list_for_admin` rather than by id.
    Callback data is client-supplied — a user can replay a button with any id
    they like — and buying a plan for somebody else's chat would be a real, if
    generous, authorization hole.
    """
    # `removeprefix`, not `lstrip("-")`: the latter strips *every* leading dash,
    # so "--1" passed the guard and then blew up in `int()` — an unhandled
    # exception in a callback handler, reachable by anyone who can edit a button.
    if not raw_chat_id.removeprefix("-").isdigit():
        return None
    chat_id = int(raw_chat_id)
    async with UnitOfWork() as uow:
        chats = await uow.chats.list_for_admin(tg_user_id)
    return next((chat for chat in chats if chat.id == chat_id), None)


__all__ = ["TERMS", "build_router"]
