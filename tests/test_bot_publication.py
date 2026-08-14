"""Bot-level Telegram setup that is easy to break without a real API call."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from aiogram.exceptions import TelegramAPIError
from aiogram.methods import SetMyCommands
from aiogram.types import MenuButtonCommands, MenuButtonWebApp
import pytest

from bot import __main__ as bot_main
from bot.filters import InGroup
from bot.modules import crossban, engagement
from i18n.runtime import translator
from shared.config import Settings


class FakeBot:
    def __init__(self, *, fail_first_command_call: bool = False) -> None:
        self.command_calls: list[tuple[list[Any], Any]] = []
        self.menu_buttons: list[Any] = []
        self.fail_first_command_call = fail_first_command_call

    async def set_my_commands(self, commands: list[Any], *, scope: Any) -> None:
        self.command_calls.append((commands, scope))
        if self.fail_first_command_call and len(self.command_calls) == 1:
            raise TelegramAPIError(SetMyCommands(commands=[]), "group menu failed")

    async def set_chat_menu_button(self, *, menu_button: Any) -> None:
        self.menu_buttons.append(menu_button)


@pytest.mark.asyncio
async def test_https_webapp_is_the_global_chat_menu_button(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(webapp_url="https://app.example.com", _env_file=None)
    monkeypatch.setattr(bot_main, "get_settings", lambda: settings)
    bot = FakeBot()

    await bot_main._publish_commands(bot)  # type: ignore[arg-type]

    assert len(bot.command_calls) == 2
    button = bot.menu_buttons[0]
    assert isinstance(button, MenuButtonWebApp)
    assert button.web_app.url == "https://app.example.com"
    assert button.text == translator("ru")("open-miniapp")


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["", "http://localhost:5173", "not-a-url"])
async def test_invalid_or_local_webapp_url_keeps_the_command_menu(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setattr(
        bot_main,
        "get_settings",
        lambda: Settings(webapp_url=url, _env_file=None),
    )
    bot = FakeBot()

    await bot_main._publish_commands(bot)  # type: ignore[arg-type]

    assert isinstance(bot.menu_buttons[0], MenuButtonCommands)


@pytest.mark.asyncio
async def test_one_failed_command_scope_does_not_skip_the_other_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(webapp_url="https://app.example.com", _env_file=None)
    monkeypatch.setattr(bot_main, "get_settings", lambda: settings)
    bot = FakeBot(fail_first_command_call=True)

    await bot_main._publish_commands(bot)  # type: ignore[arg-type]

    assert len(bot.command_calls) == 2
    assert len(bot.menu_buttons) == 1


@pytest.mark.parametrize("module", [engagement, crossban])
def test_group_command_routers_reject_private_updates_at_the_root(module: Any) -> None:
    router = module.build_router()
    filters = [item.callback for item in router.message._handler.filters]
    assert any(isinstance(callback, InGroup) for callback in filters)


@pytest.mark.asyncio
async def test_in_group_filter_rejects_a_dm_without_chat_context() -> None:
    assert not await InGroup()(SimpleNamespace(), ctx=None)  # type: ignore[arg-type]
