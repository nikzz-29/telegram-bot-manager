"""structlog configuration: JSON output with contextvars-bound request fields."""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars, unbind_contextvars
from structlog.typing import Processor

_configured = False


def configure_logging(level: str = "INFO", *, json_output: bool = True) -> None:
    """Configure structlog and route stdlib logging through it.

    Idempotent: safe to call from bot, API and worker entrypoints.
    """
    global _configured
    if _configured:
        return

    numeric_level = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )
    # ConsoleRenderer formats tracebacks itself; handing it a pre-rendered string
    # would print the traceback twice. JSONRenderer needs the string.
    final_processors: list[Processor] = [structlog.stdlib.ProcessorFormatter.remove_processors_meta]
    if json_output:
        final_processors.append(structlog.processors.format_exc_info)
    final_processors.append(renderer)

    # DECISION: our own loggers are routed through stdlib rather than straight to
    # stdout. `add_logger_name` reads `logger.name`, which a `PrintLogger` does not
    # have — the pairing raises `AttributeError` on the first line the process logs.
    # Going through stdlib also means our lines and a library's lines are rendered
    # by one formatter, so they cannot drift apart in format.
    structlog.configure(
        processors=[
            # First, so a suppressed DEBUG line costs nothing further downstream.
            structlog.stdlib.filter_by_level,
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            # Foreign records arrive with `logger=None`, so `filter_by_level` (which
            # needs a real stdlib logger) must stay out of this chain.
            foreign_pre_chain=shared_processors,
            processors=final_processors,
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(numeric_level)

    # These libraries are chatty at INFO and add nothing we do not already log.
    for noisy in ("aiogram.event", "aiosqlite", "asyncio", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(max(numeric_level, logging.WARNING))

    _configured = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger


def bind_update_context(
    *,
    update_id: int | None = None,
    chat_id: int | None = None,
    user_id: int | None = None,
    **extra: Any,
) -> None:
    """Bind per-update fields so every downstream log line carries them."""
    fields: dict[str, Any] = {
        key: value
        for key, value in (
            ("update_id", update_id),
            ("chat_id", chat_id),
            ("user_id", user_id),
        )
        if value is not None
    }
    fields.update(extra)
    if fields:
        bind_contextvars(**fields)


def clear_update_context() -> None:
    clear_contextvars()


__all__ = [
    "bind_contextvars",
    "bind_update_context",
    "clear_update_context",
    "configure_logging",
    "get_logger",
    "unbind_contextvars",
]
