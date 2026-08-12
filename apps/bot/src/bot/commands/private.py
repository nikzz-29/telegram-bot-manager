"""Private-chat commands: the bot's front door and the whole DM surface.

Everything here runs in a DM, where there is no `ChatContext` — no plan, no
module switches, no moderation config. This is where the person behind the bot
lives: their profile, the chats they administer, what those chats did this week,
what the plans cost, the flow that puts one of those chats onto one of those
plans, and the manual for all of it.

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
data at 64 bytes; the longest value this builds is well inside it. Every other
screen here works the same way, which is why there is no FSM anywhere in this
module — the statistics window and the manual page are in the data too.

DECISION: a button edits the message it lives on; only a command sends a new
one. A DM that grows by a screen per tap is unreadable inside a minute, and
Telegram offers no way to collapse it afterwards. Private chats skip the 20/min
per-group bucket in `core.sender`, so an edit per tap costs nothing but the
global rate.

DECISION: every screen offers a way out — its parent, the root menu, or both.
A screen whose only exit is scrolling back through the conversation is a dead
end, and the conversation is exactly what editing in place stopped keeping.

DECISION: the Mini App has one entrance and it is unlisted. `PANEL_COMMAND`
names it, `bot.__main__.PRIVATE_COMMANDS` deliberately does not, and no screen
below links to it: the panel is an operator surface, and every DM here belongs
to someone who is not an operator.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
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
from bot.guide import PAGES, GuidePage, neighbours, page_for, position, render
from bot.replies import edit, send
from core.billing import MAX_MONTHS, billing
from core.dm_stats import DEFAULT_PERIOD, PERIODS, StatsPeriod, dm_stats, period_for
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

# One prefix per screen, and the screen's whole state rides in the data after it.
# `dm:` namespaces them away from the captcha and forced-subscription callbacks,
# which are group-side and parse their own formats. The short ones are short
# because the payload has 64 bytes for everything, prefix included.
CB_HOME: Final = "dm:home"
CB_PROFILE: Final = "dm:profile"
CB_CHATS: Final = "dm:chats"
CB_PLANS: Final = "dm:plans"
CB_GUIDE: Final = "dm:guide"
CB_PAGE: Final = "dm:g"  # dm:g:<slug> — one page of the manual
CB_DIGEST: Final = "dm:st"  # dm:st:<period> — every chat at once
CB_REPORT: Final = "dm:sc"  # dm:sc:<chat_id>:<period> — one chat
CB_CHAT: Final = "dm:chat"  # dm:chat:<plan> — which chat is this plan for?
CB_TERM: Final = "dm:term"  # dm:term:<plan>:<chat_id> — for how long?
CB_BUY: Final = "dm:buy"  # dm:buy:<plan>:<chat_id>:<months> — mint the invoice

# The terms offered in chat. The panel offers the same three; `MAX_MONTHS` is
# the ceiling both are checked against at settlement.
TERMS: Final[tuple[int, ...]] = (1, 3, 12)

# How many chats a profile lists before it says "and N more" — a profile has to
# stay one screen tall, and `/chats` is the full list.
PROFILE_CHAT_PREVIEW: Final = 3

# The manual page shown to someone whose chat list is empty: that screen's only
# real question is "how do I get a chat in here", and the answer is a page.
SETUP_PAGE: Final = "setup"


@dataclass(frozen=True, slots=True)
class Screen:
    """One DM screen: what it says, and what it offers next.

    Commands send a screen and buttons redraw one, so both paths build the same
    object and the two can never drift into offering different keyboards for the
    same words.
    """

    text: str
    keyboard: InlineKeyboardMarkup | None = None


# One keyboard, as rows of buttons, before it is wrapped in a markup object.
Rows = list[list[InlineKeyboardButton]]


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
    """The title as a button label — raw, because a label is not parsed as HTML."""
    return chat.title or t("dm-chat-untitled")


def _title_text(chat: Chat, t: Translator) -> str:
    """The same title on its way into a message body, where `<` is a tag.

    Parse mode is HTML for every send this bot makes, and a chat named `<b>` would
    otherwise make Telegram reject the whole message — which `core.sender` drops
    with nothing but a log line, so the screen simply never arrives.
    """
    return escape(_chat_title(chat, t))


async def _chats_for(tg_user_id: int) -> list[Chat]:
    async with UnitOfWork() as uow:
        return await uow.chats.list_for_admin(tg_user_id)


def _profile_text(user: User, chats: list[Chat], t: Translator) -> str:
    lines = [
        # The display name is escaped for the same reason a chat title is: it is
        # whatever the account owner typed, and it lands inside a <b> tag.
        t("dm-profile-header", name=escape(_display_name(user, t))),
        # DECISION: the id goes in as a string. Fluent formats a bare number for
        # the locale — `111 222 333` in ru, `111,222,333` in en — which is right
        # for a price and wrong for an identifier sitting in a <code> block that
        # exists to be copied and pasted back to support.
        t("dm-profile-id", id=str(user.id)),
        "",
        t("dm-profile-chats", count=len(chats)),
    ]
    lines.extend(f"• {_title_text(chat, t)}" for chat in chats[:PROFILE_CHAT_PREVIEW])
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
            lines.append(t("dm-chats-row-free", chat=_title_text(chat, t), plan=plan))
        else:
            lines.append(
                t(
                    "dm-chats-row",
                    chat=_title_text(chat, t),
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


# --- navigation -------------------------------------------------------------
# DECISION: the exit row is built in one place. A dozen screens each spelling out
# their own way back is how one of them ends up without any.


def _button(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def _nav(t: Translator, *, back: str | None = None) -> list[InlineKeyboardButton]:
    """The last row of every screen except the root menu.

    `back` names the parent when there is one worth returning to; the root is
    always offered, because a user three taps deep should not have to work out
    which of the buttons is the way out.
    """
    row: list[InlineKeyboardButton] = []
    if back is not None:
        row.append(_button(t("dm-back-button"), back))
    row.append(_button(t("dm-home-button"), CB_HOME))
    return row


def _in_pairs(buttons: list[InlineKeyboardButton]) -> Rows:
    """Two buttons per row — a column of twelve is a screen nobody reads."""
    return [buttons[index : index + 2] for index in range(0, len(buttons), 2)]


# --- keyboards --------------------------------------------------------------
# Each of these builds the *options* one screen offers. The exit row is added by
# the screen itself, so a list of plans stays a list of plans and the tests can
# read a keyboard's callback data as one shape.


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


def _plan_options(t: Translator) -> Rows:
    """One button per purchasable plan, priced at its monthly rate."""
    return [
        [
            _button(
                t("dm-plans-button", plan=t(f"plan-{plan.value}"), stars=PLAN_PRICES[plan].stars),
                f"{CB_CHAT}:{plan.value}",
            )
        ]
        for plan in PURCHASABLE_PLANS
    ]


def _chat_options(plan: Plan, chats: list[Chat], t: Translator) -> Rows:
    return [[_button(_chat_title(chat, t), f"{CB_TERM}:{plan.value}:{chat.id}")] for chat in chats]


def _term_options(plan: Plan, chat_id: int, t: Translator) -> Rows:
    stars = PLAN_PRICES[plan].stars
    return [
        [
            _button(
                t("dm-term-button", months=months, stars=stars * months),
                f"{CB_BUY}:{plan.value}:{chat_id}:{months}",
            )
        ]
        for months in TERMS
    ]


def _period_options(t: Translator, prefix: str, current: StatsPeriod) -> Rows:
    """The window switcher, with the window already on screen marked.

    Every window renders the same shape of report, so without the mark a tap that
    changed the numbers slightly looks like a bot that ignored it.
    """
    return _in_pairs(
        [
            _button(
                t("dm-stats-period-current", period=period.label(t))
                if period is current
                else period.label(t),
                f"{prefix}:{period.slug}",
            )
            for period in PERIODS
        ]
    )


# --- screens ----------------------------------------------------------------
# The sections of the DM, in the order the root menu lists them. Every one of
# these is called from both a command and the callback that does the same thing,
# so the two can never drift into saying different things.


def _menu_screen(t: Translator) -> Screen:
    """The root: five sections, and nothing that is not one of them."""
    return Screen(
        t("dm-menu"),
        InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    _button(t("dm-profile-button"), CB_PROFILE),
                    _button(t("dm-chats-button"), CB_CHATS),
                ],
                [
                    _button(t("dm-stats-button"), f"{CB_DIGEST}:{DEFAULT_PERIOD.slug}"),
                    _button(t("dm-plans-button-short"), CB_PLANS),
                ],
                [_button(t("dm-guide-button"), CB_GUIDE)],
            ]
        ),
    )


def _start_screen(t: Translator) -> Screen:
    """`/start`: the welcome, over the root menu's own keyboard."""
    return Screen(t("start-welcome"), _menu_screen(t).keyboard)


def _help_screen(t: Translator) -> Screen:
    """`/help`: the short version, with the long one one tap away."""
    return Screen(
        t("help-text"),
        InlineKeyboardMarkup(inline_keyboard=[[_button(t("dm-guide-button"), CB_GUIDE)], _nav(t)]),
    )


def _notice_screen(text: str, t: Translator) -> Screen:
    """Something went wrong, said in place — with the menu still reachable."""
    return Screen(text, InlineKeyboardMarkup(inline_keyboard=[_nav(t)]))


def _profile_screen(user: User, chats: list[Chat], t: Translator) -> Screen:
    return Screen(
        _profile_text(user, chats, t),
        InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    _button(t("dm-chats-button"), CB_CHATS),
                    _button(t("dm-plans-button-short"), CB_PLANS),
                ],
                _nav(t),
            ]
        ),
    )


def _chats_screen(chats: list[Chat], t: Translator) -> Screen:
    """The chat list, where every row is also the way into that chat's report."""
    rows: Rows = [
        [
            _button(
                t("dm-chat-report-button", chat=_chat_title(chat, t)),
                f"{CB_REPORT}:{chat.id}:{DEFAULT_PERIOD.slug}",
            )
        ]
        for chat in chats
    ]
    if chats:
        rows.append([_button(t("dm-plans-button-short"), CB_PLANS)])
    else:
        # An empty list asks exactly one question, and a manual page answers it.
        rows.append([_button(t("dm-chats-setup-button"), f"{CB_PAGE}:{SETUP_PAGE}")])
    rows.append(_nav(t))
    return Screen(_chats_text(chats, t), InlineKeyboardMarkup(inline_keyboard=rows))


def _plans_screen(t: Translator) -> Screen:
    return Screen(
        _plans_text(t), InlineKeyboardMarkup(inline_keyboard=[*_plan_options(t), _nav(t)])
    )


def _choose_chat_screen(plan: Plan, chats: list[Chat], t: Translator) -> Screen:
    return Screen(
        t("dm-buy-choose-chat", plan=t(f"plan-{plan.value}")),
        InlineKeyboardMarkup(
            inline_keyboard=[*_chat_options(plan, chats, t), _nav(t, back=CB_PLANS)]
        ),
    )


def _choose_term_screen(plan: Plan, chat: Chat, t: Translator) -> Screen:
    return Screen(
        t("dm-buy-choose-term", chat=_title_text(chat, t), plan=t(f"plan-{plan.value}")),
        InlineKeyboardMarkup(
            inline_keyboard=[
                *_term_options(plan, chat.id, t),
                # Back is the chat picker for this plan, not the plan list: the
                # buyer has already decided what they are buying.
                _nav(t, back=f"{CB_CHAT}:{plan.value}"),
            ]
        ),
    )


def _invoice_screen(
    plan: Plan, chat: Chat, months: int, *, amount: str, url: str | None, t: Translator
) -> Screen:
    """The invoice, with the payment sheet behind a button.

    DECISION: the link is a button, not text the user has to tap through a
    preview. `create_invoice_link` returns the same URL the Mini App opens with
    `WebApp.openInvoice`, and Telegram renders a URL button onto it as its native
    payment sheet — so the receipt comes back through `payments.confirm_payment`
    either way. A provider that answered without a URL gets no button rather than
    a dead one; the way back is still there.
    """
    rows: Rows = []
    if url:
        rows.append([InlineKeyboardButton(text=t("dm-buy-pay", stars=amount), url=url)])
    rows.append(_nav(t, back=f"{CB_TERM}:{plan.value}:{chat.id}"))
    return Screen(
        t(
            "dm-buy-invoice",
            chat=_title_text(chat, t),
            plan=t(f"plan-{plan.value}"),
            months=months,
        ),
        InlineKeyboardMarkup(inline_keyboard=rows),
    )


async def _digest_screen(
    chats: list[Chat], period: StatsPeriod, viewer_tg_id: int, t: Translator
) -> Screen:
    """Every chat this person administers, in one window.

    The titles go in raw: `core.dm_stats` escapes what it renders, and escaping
    here would put `&amp;` in front of the reader.
    """
    text = await dm_stats.overall_report(
        chats=[(chat.id, _chat_title(chat, t)) for chat in chats],
        period=period,
        viewer_tg_id=viewer_tg_id,
        t=t,
    )
    rows = _period_options(t, CB_DIGEST, period)
    if chats:
        # The digest says what happened; the chat list is where one chat's own
        # report lives, so that is the only place this screen leads onward.
        rows.append([_button(t("dm-chats-button"), CB_CHATS)])
    rows.append(_nav(t))
    return Screen(text, InlineKeyboardMarkup(inline_keyboard=rows))


async def _report_screen(
    chat: Chat, period: StatsPeriod, viewer_tg_id: int, t: Translator
) -> Screen:
    """One chat over one window, reached from the chat list."""
    text = await dm_stats.chat_report(
        chat_id=chat.id,
        title=_chat_title(chat, t),
        period=period,
        viewer_tg_id=viewer_tg_id,
        t=t,
    )
    rows = _period_options(t, f"{CB_REPORT}:{chat.id}", period)
    rows.append(_nav(t, back=CB_CHATS))
    return Screen(text, InlineKeyboardMarkup(inline_keyboard=rows))


def _guide_index_screen(t: Translator) -> Screen:
    """The manual's table of contents: one button per page, in reading order."""
    rows = _in_pairs([_button(page.button(t), f"{CB_PAGE}:{page.slug}") for page in PAGES])
    rows.append(_nav(t))
    return Screen(
        "\n\n".join((t("guide-index-title"), t("guide-index-hint"))),
        InlineKeyboardMarkup(inline_keyboard=rows),
    )


def _guide_page_screen(page: GuidePage, t: Translator) -> Screen:
    """One page, with the pages either side of it and where it sits in the whole.

    The footer is what makes the manual finite: a page that only offers ‹ and ›
    gives no idea whether there are two more or twenty.
    """
    nth, total = position(page)
    previous, following = neighbours(page)
    steps: list[InlineKeyboardButton] = []
    if previous is not None:
        steps.append(_button(t("guide-nav-prev"), f"{CB_PAGE}:{previous.slug}"))
    if following is not None:
        steps.append(_button(t("guide-nav-next"), f"{CB_PAGE}:{following.slug}"))
    rows: Rows = [steps] if steps else []
    rows.append([_button(t("dm-guide-contents-button"), CB_GUIDE), *_nav(t)])
    return Screen(
        "\n\n".join((render(page, t), t("guide-footer", nth=nth, total=total))),
        InlineKeyboardMarkup(inline_keyboard=rows),
    )


# --- parsing ----------------------------------------------------------------


def _parse_plan(raw: str) -> Plan | None:
    """A plan name from callback data, or `None` when it is not one we sell."""
    try:
        plan = Plan(raw)
    except ValueError:
        return None
    return plan if plan in PURCHASABLE_PLANS else None


# --- delivery ---------------------------------------------------------------


async def _reply(message: Message, screen: Screen) -> None:
    """A command's answer: a new message, announced like one."""
    await send(
        message.chat.id,
        screen.text,
        priority=SendPriority.REPLY,
        silent=False,
        keyboard=screen.keyboard,
    )


async def _redraw(query: CallbackQuery, screen: Screen) -> None:
    """A button's answer: the message the button lives on, replaced.

    See `bot.replies.edit` on why nothing is awaited here and why the two ways an
    edit fails are both non-events.
    """
    if query.message is None:
        return
    await edit(
        query.message.chat.id,
        query.message.message_id,
        screen.text,
        keyboard=screen.keyboard,
    )


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
        await _reply(message, _start_screen(translator(_locale(message.from_user))))

    @router.message(Command("help"))
    async def help_command(message: Message) -> None:
        await _reply(message, _help_screen(translator(_locale(message.from_user))))

    # --- the operator's console --------------------------------------------
    @router.message(Command(get_settings().panel_command_name))
    async def console_command(message: Message) -> None:
        """The only entrance to the Mini App, for the ids in `SUPERADMIN_IDS`.

        DECISION: everybody else gets nothing at all — not a refusal, not an
        error. A "this is not for you" reply confirms the command exists, and the
        name is the only thing keeping ordinary members from finding a door to
        rattle: it is published in no menu, `bot.__main__` leaves it out of
        `setMyCommands` on purpose, and no screen above links to it. The id check
        is the boundary; the silence is what keeps the boundary from advertising
        itself, and a curious member cannot tell it apart from a typo.

        The name comes from `PANEL_COMMAND` at router build time, which is also
        when `setMyCommands` runs — a name changed in `.env` mid-process would
        leave the two disagreeing either way.
        """
        if message.from_user is None:
            return
        if not access.may_open_panel(message.from_user.id):
            logger.info("panel.access_denied", user_id=message.from_user.id)
            return
        locale = _locale(message.from_user)
        logger.info("panel.access_granted", user_id=message.from_user.id)
        await send(
            message.chat.id,
            translator(locale)("admin-welcome"),
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
        await _reply(message, _profile_screen(message.from_user, chats, t))

    @router.message(Command("chats"))
    async def chats_command(message: Message) -> None:
        if message.from_user is None:
            return
        t = translator(_locale(message.from_user))
        await _reply(message, _chats_screen(await _chats_for(message.from_user.id), t))

    # `/pay` is the same screen as `/plans` reached from the other direction —
    # one wants to know the price, the other has already decided.
    @router.message(Command("plans", "pay"))
    async def plans_command(message: Message) -> None:
        await _reply(message, _plans_screen(translator(_locale(message.from_user))))

    # --- the same screens, reached by button ---------------------------------
    # Each answers the query first: the toast is how Telegram stops the button's
    # spinner, and it must happen whether or not the work below succeeds. Then it
    # redraws the message it was pressed on, so the DM stays one screen deep.

    @router.callback_query(F.data == CB_HOME)
    async def home_pressed(query: CallbackQuery) -> None:
        await query.answer()
        await _redraw(query, _menu_screen(translator(_locale(query.from_user))))

    @router.callback_query(F.data == CB_PROFILE)
    async def profile_pressed(query: CallbackQuery) -> None:
        await query.answer()
        t = translator(_locale(query.from_user))
        chats = await _chats_for(query.from_user.id)
        await _redraw(query, _profile_screen(query.from_user, chats, t))

    @router.callback_query(F.data == CB_CHATS)
    async def chats_pressed(query: CallbackQuery) -> None:
        await query.answer()
        t = translator(_locale(query.from_user))
        await _redraw(query, _chats_screen(await _chats_for(query.from_user.id), t))

    @router.callback_query(F.data == CB_PLANS)
    async def plans_pressed(query: CallbackQuery) -> None:
        await query.answer()
        await _redraw(query, _plans_screen(translator(_locale(query.from_user))))

    # --- the manual ----------------------------------------------------------
    @router.callback_query(F.data == CB_GUIDE)
    async def guide_pressed(query: CallbackQuery) -> None:
        await query.answer()
        await _redraw(query, _guide_index_screen(translator(_locale(query.from_user))))

    @router.callback_query(F.data.startswith(f"{CB_PAGE}:"))
    async def page_pressed(query: CallbackQuery) -> None:
        await query.answer()
        if query.data is None:
            return
        page = page_for(query.data.split(":")[-1])
        if page is None:
            # A slug this build does not have: the manual was renumbered under a
            # message somebody kept. Leaving the page they are on is kinder than
            # replacing it with an error.
            return
        await _redraw(query, _guide_page_screen(page, translator(_locale(query.from_user))))

    # --- statistics ----------------------------------------------------------
    @router.callback_query(F.data.startswith(f"{CB_DIGEST}:"))
    async def digest_pressed(query: CallbackQuery) -> None:
        """Every chat this person administers, over the window they picked."""
        await query.answer()
        if query.data is None:
            return
        period = period_for(query.data.split(":")[-1])
        if period is None:
            return
        t = translator(_locale(query.from_user))
        chats = await _chats_for(query.from_user.id)
        await _redraw(query, await _digest_screen(chats, period, query.from_user.id, t))

    @router.callback_query(F.data.startswith(f"{CB_REPORT}:"))
    async def report_pressed(query: CallbackQuery) -> None:
        """One chat's own report — authorized again, like every other chat id."""
        await query.answer()
        if query.data is None:
            return
        parts = query.data.split(":")
        if len(parts) != 4:
            return
        period = period_for(parts[3])
        if period is None:
            return
        t = translator(_locale(query.from_user))
        chat = await _authorized_chat(query.from_user.id, parts[2])
        if chat is None:
            await _redraw(query, _notice_screen(t("dm-chat-unavailable"), t))
            return
        await _redraw(query, await _report_screen(chat, period, query.from_user.id, t))

    # --- the purchase, one press per decision -------------------------------
    @router.callback_query(F.data.startswith(f"{CB_CHAT}:"))
    async def chat_step(query: CallbackQuery) -> None:
        """A plan was chosen. Which chat is it for?"""
        await query.answer()
        if query.data is None:
            return
        plan = _parse_plan(query.data.split(":")[-1])
        if plan is None:
            return
        t = translator(_locale(query.from_user))
        chats = await _chats_for(query.from_user.id)
        if not chats:
            # A plan is bought *for a chat*, so there is nothing to sell yet —
            # but the screen still says so with a way onwards.
            await _redraw(query, _notice_screen(t("dm-buy-no-chats"), t))
            return
        await _redraw(query, _choose_chat_screen(plan, chats, t))

    @router.callback_query(F.data.startswith(f"{CB_TERM}:"))
    async def term_step(query: CallbackQuery) -> None:
        """A chat was chosen. For how long?"""
        await query.answer()
        if query.data is None:
            return
        parts = query.data.split(":")
        if len(parts) != 4:
            return
        plan = _parse_plan(parts[2])
        t = translator(_locale(query.from_user))
        chat = await _authorized_chat(query.from_user.id, parts[3])
        if plan is None or chat is None:
            await _redraw(query, _notice_screen(t("dm-chat-unavailable"), t))
            return
        await _redraw(query, _choose_term_screen(plan, chat, t))

    @router.callback_query(F.data.startswith(f"{CB_BUY}:"))
    async def buy_step(query: CallbackQuery) -> None:
        """Every decision is in: mint the invoice."""
        await query.answer()
        if query.data is None:
            return
        parts = query.data.split(":")
        if len(parts) != 5:
            return
        t = translator(_locale(query.from_user))
        plan = _parse_plan(parts[2])
        chat = await _authorized_chat(query.from_user.id, parts[3])
        months = int(parts[4]) if parts[4].isdigit() else 0
        if plan is None or chat is None or months not in TERMS:
            await _redraw(query, _notice_screen(t("dm-chat-unavailable"), t))
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
            await _redraw(query, _notice_screen(t("error-provider-unavailable"), t))
            return

        logger.info(
            "billing.dm_invoice_opened",
            chat_id=chat.id,
            plan=plan.value,
            months=months,
            user_id=query.from_user.id,
        )
        await _redraw(
            query,
            _invoice_screen(
                plan, chat, months, amount=invoice.amount, url=invoice.invoice_url, t=t
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
