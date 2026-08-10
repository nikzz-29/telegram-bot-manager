"""Logging configuration tests.

These exist because a misconfigured processor chain does not fail at import: it
fails on the first line the process tries to log, which is `bot.started`. A
`PrintLoggerFactory` paired with `add_logger_name` did exactly that — the name
processor reads `logger.name`, which a `PrintLogger` does not have.
"""

from __future__ import annotations

from collections.abc import Iterator
import json
import logging
from typing import Any

import pytest
import structlog

import shared.logging as shared_logging
from shared.logging import bind_update_context, clear_update_context, configure_logging, get_logger


@pytest.fixture(autouse=True)
def _reset_logging() -> Iterator[None]:
    """`configure_logging` is deliberately idempotent, so each test re-arms it."""
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    shared_logging._configured = False
    yield
    clear_update_context()
    structlog.reset_defaults()
    root.handlers, root.level = saved_handlers, saved_level
    shared_logging._configured = False


@pytest.mark.parametrize("json_output", [True, False])
def test_logging_survives_the_first_line(
    json_output: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging("INFO", json_output=json_output)
    get_logger("test.first").info("bot.started", username="probe", bot_id=1)

    out = capsys.readouterr().out
    assert "bot.started" in out
    assert "test.first" in out


def test_json_mode_emits_one_object_per_line_with_context(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO", json_output=True)
    bind_update_context(update_id=7, chat_id=-1001, user_id=42)
    get_logger("test.json").warning("entry.lockdown_started", until="2026-01-01T00:00:00Z")

    line = capsys.readouterr().out.strip().splitlines()[-1]
    payload: dict[str, Any] = json.loads(line)
    assert payload["event"] == "entry.lockdown_started"
    assert payload["level"] == "warning"
    assert payload["logger"] == "test.json"
    # The contextvars bound per update have to ride along on every line.
    assert (payload["chat_id"], payload["user_id"], payload["update_id"]) == (-1001, 42, 7)
    assert payload["timestamp"].endswith("Z")


def test_level_filtering_drops_quieter_lines(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("WARNING", json_output=True)
    log = get_logger("test.level")
    log.info("should_be_dropped")
    log.warning("should_survive")

    out = capsys.readouterr().out
    assert "should_survive" in out
    assert "should_dropped" not in out
    assert "should_be_dropped" not in out


def test_exception_is_rendered_once(capsys: pytest.CaptureFixture[str]) -> None:
    """Console mode renders tracebacks itself; JSON mode needs the string form."""
    configure_logging("INFO", json_output=True)
    try:
        raise ValueError("boom")
    except ValueError:
        get_logger("test.exc").exception("exploded")

    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["event"] == "exploded"
    assert "ValueError: boom" in payload["exception"]
    assert payload["exception"].count("ValueError: boom") == 1


def test_library_records_share_our_format(capsys: pytest.CaptureFixture[str]) -> None:
    """A third-party record must come out as JSON too, not as bare text."""
    configure_logging("INFO", json_output=True)
    logging.getLogger("aiogram.dispatcher").error("something in the library")

    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["event"] == "something in the library"
    assert payload["logger"] == "aiogram.dispatcher"
    assert payload["level"] == "error"


def test_noisy_libraries_are_capped_at_warning() -> None:
    configure_logging("DEBUG", json_output=True)
    assert logging.getLogger("httpx").level >= logging.WARNING
    assert logging.getLogger("asyncio").level >= logging.WARNING
