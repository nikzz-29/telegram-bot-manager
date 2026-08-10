"""How the bot process receives updates and how it shuts down.

Spec §32: long polling in development, webhook in production. These are the two
things that break silently — a webhook left registered makes `getUpdates` answer
409 forever, and a session closed too early makes the shutdown drain open a
second one and post moderation actions from a connection nobody is awaiting.

DECISION: `Bot` and `Dispatcher` are faked rather than constructed. A real `Bot`
validates its token against a regex and a real `start_polling` would reach the
network; what is under test is the sequencing around them.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from bot import runner
from shared.config import Settings

WEBHOOK_BASE = "https://bot.example.com"


class FakeSession:
    """Tracks whether anything closed the bot's session behind the drain's back."""

    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeBot:
    """Records the webhook calls the runners make."""

    def __init__(self) -> None:
        self.deleted: list[bool] = []
        self.set_webhook_calls: list[dict[str, Any]] = []
        self.session = FakeSession()

    async def delete_webhook(self, drop_pending_updates: bool = False) -> bool:
        self.deleted.append(drop_pending_updates)
        return True

    async def set_webhook(self, url: str, **kwargs: Any) -> bool:
        self.set_webhook_calls.append({"url": url, **kwargs})
        return True


class FakeDispatcher:
    """Records `start_polling`'s keyword arguments and returns immediately."""

    def __init__(self) -> None:
        self.polling_kwargs: dict[str, Any] | None = None
        # aiogram's `setup_application` reads this when wiring startup/shutdown,
        # then calls the two emitters from the aiohttp app's own lifecycle.
        self.workflow_data: dict[str, Any] = {}
        self.emitted: list[str] = []

    async def start_polling(self, bot: Any, **kwargs: Any) -> None:
        self.polling_kwargs = kwargs

    async def emit_startup(self, **kwargs: Any) -> None:
        self.emitted.append("startup")

    async def emit_shutdown(self, **kwargs: Any) -> None:
        self.emitted.append("shutdown")


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """A settings object the runner reads instead of the process environment."""
    value = Settings(
        app_env="development",
        use_webhook=False,
        webhook_base_url=WEBHOOK_BASE,
        webhook_secret="s3cret",
        _env_file=None,
    )
    monkeypatch.setattr(runner, "get_settings", lambda: value)
    return value


# --- polling ------------------------------------------------------------------


async def test_polling_clears_a_webhook_left_behind(settings: Settings) -> None:
    """`getUpdates` answers 409 while a webhook is registered.

    Flipping USE_WEBHOOK back to false — a rollback, or a developer pointing a
    local bot at a token production used — has to clear the registration first,
    or the process starts cleanly and then receives nothing at all.
    """
    bot, dispatcher = FakeBot(), FakeDispatcher()
    await runner.run_polling(bot, dispatcher, allowed_updates=["message"])  # type: ignore[arg-type]
    assert bot.deleted == [True]


async def test_polling_leaves_the_session_open_for_the_drain(settings: Settings) -> None:
    """aiogram closes the bot session itself unless told not to.

    `__main__` drains the outbound queue *after* the runner returns, so a session
    closed here would be reopened mid-drain — the sends would go out on a
    connection the shutdown path is not waiting on.
    """
    bot, dispatcher = FakeBot(), FakeDispatcher()
    await runner.run_polling(bot, dispatcher, allowed_updates=["message"])  # type: ignore[arg-type]
    assert dispatcher.polling_kwargs is not None
    assert dispatcher.polling_kwargs["close_bot_session"] is False


async def test_polling_forwards_the_explicit_update_types(settings: Settings) -> None:
    """`edited_message` is in the list only because the caller put it there."""
    bot, dispatcher = FakeBot(), FakeDispatcher()
    updates = ["edited_message", "message"]
    await runner.run_polling(bot, dispatcher, allowed_updates=updates)  # type: ignore[arg-type]
    assert dispatcher.polling_kwargs is not None
    assert dispatcher.polling_kwargs["allowed_updates"] == updates


# --- webhook ------------------------------------------------------------------


async def test_webhook_registers_the_url_with_its_secret(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Telegram sends the secret back in a header; without one, anyone can post."""
    bot, dispatcher = FakeBot(), FakeDispatcher()
    settings.use_webhook = True
    monkeypatch.setattr(runner, "_until_signalled", _immediately)

    await runner.run_webhook(bot, dispatcher, allowed_updates=["message"])  # type: ignore[arg-type]

    assert len(bot.set_webhook_calls) == 1
    call = bot.set_webhook_calls[0]
    assert call["url"] == f"{WEBHOOK_BASE}/telegram/webhook"
    assert call["secret_token"] == "s3cret"
    assert call["allowed_updates"] == ["message"]


async def test_webhook_survives_a_restart_without_being_deleted(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Telegram queues and redelivers while the endpoint is down.

    Deleting the registration on shutdown would open a gap on every deploy, and a
    crash-looping process would leave the bot unreachable with no sign of why.
    """
    bot, dispatcher = FakeBot(), FakeDispatcher()
    settings.use_webhook = True
    monkeypatch.setattr(runner, "_until_signalled", _immediately)

    await runner.run_webhook(bot, dispatcher, allowed_updates=["message"])  # type: ignore[arg-type]
    assert bot.deleted == []


async def test_webhook_leaves_the_session_open_for_the_drain(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """aiogram's `register()` installs a shutdown hook that closes the session.

    The route is therefore added directly. Same reasoning as polling's
    `close_bot_session=False`: the drain in `__main__` runs after this returns and
    must not have to reopen the connection it is sending on.
    """
    bot, dispatcher = FakeBot(), FakeDispatcher()
    settings.use_webhook = True
    monkeypatch.setattr(runner, "_until_signalled", _immediately)

    await runner.run_webhook(bot, dispatcher, allowed_updates=["message"])  # type: ignore[arg-type]
    assert not bot.session.closed


async def test_webhook_returns_when_signalled(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The runner returns rather than being killed, so `__main__` can drain."""
    bot, dispatcher = FakeBot(), FakeDispatcher()
    settings.use_webhook = True
    released = asyncio.Event()

    async def wait_for_release() -> None:
        await released.wait()

    monkeypatch.setattr(runner, "_until_signalled", wait_for_release)
    task = asyncio.create_task(
        runner.run_webhook(bot, dispatcher, allowed_updates=["message"])  # type: ignore[arg-type]
    )
    await asyncio.sleep(0)  # let the server bind
    assert not task.done()

    released.set()
    await asyncio.wait_for(task, timeout=5)


# --- the choice ---------------------------------------------------------------


async def test_run_updates_picks_polling_by_default(settings: Settings) -> None:
    bot, dispatcher = FakeBot(), FakeDispatcher()
    await runner.run_updates(bot, dispatcher, allowed_updates=["message"])  # type: ignore[arg-type]
    assert dispatcher.polling_kwargs is not None, "USE_WEBHOOK is off, so it must poll"


async def test_run_updates_picks_the_webhook_when_asked(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot, dispatcher = FakeBot(), FakeDispatcher()
    settings.use_webhook = True
    monkeypatch.setattr(runner, "_until_signalled", _immediately)

    await runner.run_updates(bot, dispatcher, allowed_updates=["message"])  # type: ignore[arg-type]
    assert dispatcher.polling_kwargs is None
    assert len(bot.set_webhook_calls) == 1


async def _immediately() -> None:
    """Stand-in for the signal wait: returns at once so the runner shuts down."""
    return None
