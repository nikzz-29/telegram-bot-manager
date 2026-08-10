"""The gate that decides whether a module's router runs at all.

Spec §4.2: module routers are never attached to the dispatcher directly. Each one
is wrapped in this gate, so a router only sees an update when its module is
switched on *and* the chat's plan includes it.

DECISION: an update the gate refuses is dropped, not answered. A chat that turned
statistics off should behave as though the feature does not exist — replying "this
requires Pro" to every `/stats` would turn a settings choice into an advert.

DECISION: a command explicitly typed by an *admin* against a plan-locked module
does get an answer. Silence there reads as a broken bot, and the admin is the one
person who can act on the information.

DECISION: a blocked update returns aiogram's `UNHANDLED` sentinel rather than
`None`. Returning `None` would count as "this router handled it" and stop the
update reaching the *other* modules' routers — which matters the moment a module
registers a catch-all handler, as engagement does for triggers. `UNHANDLED` says
what is actually true: this module did not deal with the event.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.replies import notify
from core.admins import admins
from core.context import ChatContext
from core.registry import SPEC_BY_NAME
from i18n.runtime import translator
from shared.enums import ModuleName
from shared.logging import get_logger

logger = get_logger(__name__)


def _is_command(event: TelegramObject) -> bool:
    text = event.text if isinstance(event, Message) else None
    return text is not None and text.startswith("/")


class ModuleGateMiddleware(BaseMiddleware):
    """Wraps one module's router: runs it only when the module is available."""

    def __init__(self, module: ModuleName) -> None:
        self._module = module
        self._spec = SPEC_BY_NAME[module.value]

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        ctx: ChatContext | None = data.get("ctx")
        if ctx is None:
            # A private chat: modules are chat-scoped, so only the platform-level
            # handlers (/start and the Mini App button) belong here.
            return await handler(event, data)

        locked = not ctx.has(self._spec.feature)
        if locked:
            await self._explain_if_admin(event, ctx)
            return UNHANDLED
        if not ctx.module_enabled(self._module):
            return UNHANDLED
        return await handler(event, data)

    async def _explain_if_admin(self, event: TelegramObject, ctx: ChatContext) -> None:
        """Tell an admin why their command did nothing; stay silent otherwise."""
        if isinstance(event, CallbackQuery):
            t = translator(ctx.language)
            await event.answer(
                t("module-locked", plan=self._spec.required_plan.value), show_alert=True
            )
            return
        if not _is_command(event) or not isinstance(event, Message) or event.from_user is None:
            return
        if not await admins.is_admin(ctx.tg_chat_id, event.from_user.id):
            return

        t = translator(ctx.language)
        await notify(
            ctx,
            t(
                "module-locked-command",
                module=t(self._spec.title_key),
                plan=self._spec.required_plan.value,
            ),
        )
        logger.info(
            "module_gate.locked",
            chat_id=ctx.chat_id,
            module=self._module.value,
            plan=ctx.plan.value,
        )


__all__ = ["ModuleGateMiddleware"]
