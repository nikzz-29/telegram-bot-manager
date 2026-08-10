"""Module wiring: every feature router, behind its gate.

Spec §4.2: a module's router is never attached to the dispatcher directly. Each
one is registered here, wrapped in `ModuleGateMiddleware`, so the router only ever
sees an update when the chat has that module switched on and its plan includes it.

Adding a module is two lines: build its router, hand it to `_attach`. Nothing else
in the bot process needs to know it exists.
"""

from __future__ import annotations

from aiogram import Dispatcher, Router

from bot.middlewares.module_gate import ModuleGateMiddleware
from bot.modules import autopost, engagement, entry, moderation, stats
from core.registry import registry
from shared.enums import ModuleName
from shared.logging import get_logger

logger = get_logger(__name__)


def _attach(dispatcher: Dispatcher, module: ModuleName, router: Router) -> None:
    """Gate a module's router and include it in the dispatcher."""
    gate = ModuleGateMiddleware(module)
    for observer in router.observers.values():
        observer.middleware(gate)
    registry.attach_router(module, router)
    dispatcher.include_router(router)
    logger.debug("modules.attached", module=module.value, router=router.name)


def setup(dispatcher: Dispatcher) -> None:
    """Attach every module available in this stage.

    DECISION: order matters, and it runs cheapest-first. Statistics and
    engagement both end in a passive handler that counts the message and steps
    aside (`SkipHandler`), so every module after them still sees the update;
    putting the command-only modules ahead of them means a `/ban` never pays for
    a statistics config read.
    """
    _attach(dispatcher, ModuleName.MODERATION, moderation.build_router())
    _attach(dispatcher, ModuleName.ENTRY, entry.build_router())
    _attach(dispatcher, ModuleName.AUTOPOST, autopost.build_router())
    _attach(dispatcher, ModuleName.STATS, stats.build_router())
    _attach(dispatcher, ModuleName.ENGAGEMENT, engagement.build_router())
    # SLOT: ai_moderation (Stage 6), crossban (Stage 6).


__all__ = ["setup"]
