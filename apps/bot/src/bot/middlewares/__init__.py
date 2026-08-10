"""The middleware chain, in the order spec §4.3 mandates.

    dedup -> logging context -> ChatContext -> throttle -> global ban
          -> captcha gate -> forced subscription -> content filters
          -> stop-words / anti-flood -> AI moderation -> module routers

`setup(dispatcher)` is the single place that order is written down, so a reader
can verify the chain against the spec without opening seven files.

DECISION: dedup and the logging context attach to `dispatcher.update`, everything
after to `dispatcher.message` and its siblings. An update has to be
de-duplicated before any observer sees it, while the content guards only make
sense for a message that carries content.
"""

from __future__ import annotations

from aiogram import Dispatcher

from bot.middlewares.captcha_gate import CaptchaGateMiddleware
from bot.middlewares.chat_context import ChatContextMiddleware
from bot.middlewares.content_filters import ContentFilterMiddleware
from bot.middlewares.dedup import DedupMiddleware
from bot.middlewares.forced_subscription import ForcedSubscriptionMiddleware
from bot.middlewares.global_ban import GlobalBanMiddleware
from bot.middlewares.logging_ctx import LoggingContextMiddleware
from bot.middlewares.module_gate import ModuleGateMiddleware
from bot.middlewares.stop_words import StopWordFloodMiddleware
from bot.middlewares.throttle import ThrottleMiddleware

__all__ = [
    "CaptchaGateMiddleware",
    "ChatContextMiddleware",
    "ContentFilterMiddleware",
    "DedupMiddleware",
    "ForcedSubscriptionMiddleware",
    "GlobalBanMiddleware",
    "LoggingContextMiddleware",
    "ModuleGateMiddleware",
    "StopWordFloodMiddleware",
    "ThrottleMiddleware",
    "setup",
]


def setup(dispatcher: Dispatcher) -> None:
    """Attach every platform middleware, in spec order."""
    # --- per-update: runs for callbacks, joins and messages alike -------------
    dispatcher.update.outer_middleware(DedupMiddleware())
    dispatcher.update.outer_middleware(LoggingContextMiddleware())
    dispatcher.update.outer_middleware(ChatContextMiddleware())

    # --- per-message: needs a chat, an author and content ---------------------
    for observer in (dispatcher.message, dispatcher.edited_message):
        observer.outer_middleware(ThrottleMiddleware())
        observer.outer_middleware(GlobalBanMiddleware())
        observer.outer_middleware(CaptchaGateMiddleware())
        observer.outer_middleware(ForcedSubscriptionMiddleware())
        observer.outer_middleware(ContentFilterMiddleware())
        observer.outer_middleware(StopWordFloodMiddleware())
        # SLOT: AI moderation (Stage 6) — last, because it is the only step that
        # costs a network call, and every cheap rule above may already have
        # deleted the message.

    # Callback queries carry no content to filter, but a globally banned user
    # must not be able to drive inline flows either.
    dispatcher.callback_query.outer_middleware(GlobalBanMiddleware())
