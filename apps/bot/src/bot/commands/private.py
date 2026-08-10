"""Private-chat commands: the bot's front door.

Everything here runs in a DM, where there is no `ChatContext` — no plan, no
module switches, no moderation config. The purpose is to explain what the bot is
and hand the user into the Mini App, which is where every setting actually lives.

DECISION: settings are not editable from chat. Spec §6 puts the whole control
surface in the Mini App; a second, divergent way to change the same values is how
"the button says X but the bot does Y" bugs are born.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from bot.replies import send
from core.sender import SendPriority
from i18n.runtime import normalize_locale, translator
from shared.config import get_settings
from shared.logging import get_logger

logger = get_logger(__name__)


def _locale(message: Message) -> str:
    """A DM has no chat language, so the sender's Telegram locale decides."""
    return normalize_locale(message.from_user.language_code if message.from_user else None)


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


def build_router() -> Router:
    """Commands that answer in a private chat only."""
    router = Router(name="private")
    router.message.filter(F.chat.type == "private")

    @router.message(CommandStart())
    async def start_command(message: Message) -> None:
        locale = _locale(message)
        await send(
            message.chat.id,
            translator(locale)("start-welcome"),
            priority=SendPriority.REPLY,
            silent=False,
            keyboard=_panel_keyboard(locale),
        )

    @router.message(Command("help"))
    async def help_command(message: Message) -> None:
        await send(
            message.chat.id,
            translator(_locale(message))("help-text"),
            priority=SendPriority.REPLY,
            silent=False,
        )

    return router


__all__ = ["build_router"]
