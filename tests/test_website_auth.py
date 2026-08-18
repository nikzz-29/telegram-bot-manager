"""Security-focused tests for one-time standalone website login."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from urllib.parse import urlsplit

from aiogram.types import User
import pytest

from api.routers.auth import authenticate_website
from api.security import decode_token
from bot.commands import private
from core.website_auth import WEBSITE_SCOPE, token_digest, website_login_url
from db.models import TgUser
from db.uow import UnitOfWork
from i18n.runtime import translator
from shared.config import Settings
from shared.schemas.api import WebsiteLoginRequest

TOKEN = "a" * 43
NOW = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


def test_login_url_keeps_credential_in_fragment() -> None:
    url = website_login_url("https://example.test/account/?next=home", TOKEN)
    assert url == f"https://example.test/account/?next=home#token={TOKEN}"
    assert urlsplit(url).fragment == f"token={TOKEN}"


def test_invalid_website_url_is_rejected() -> None:
    assert website_login_url("", TOKEN) is None
    assert website_login_url("javascript:alert(1)", TOKEN) is None
    assert website_login_url("example.test/account", TOKEN) is None


class FakeWebsiteTokens:
    def __init__(self, token: str, *, user_id: int, expires_at: datetime, scope: str) -> None:
        self.token_hash = token_digest(token)
        self.user_id = user_id
        self.expires_at = expires_at
        self.scope = scope
        self.consumed = False
        self.calls: list[tuple[str, str]] = []

    async def consume(self, *, token_hash: str, scope: str, now: datetime) -> int | None:
        self.calls.append((token_hash, scope))
        if (
            self.consumed
            or token_hash != self.token_hash
            or scope != self.scope
            or self.expires_at <= now
        ):
            return None
        self.consumed = True
        return self.user_id


class FakeUsers:
    def __init__(self, profile: TgUser | None) -> None:
        self.profile = profile

    async def get(self, user_id: int) -> TgUser | None:
        return self.profile if self.profile and self.profile.tg_user_id == user_id else None


def _settings() -> Settings:
    return Settings(
        bot_token="bot-token",
        jwt_secret="x" * 40,
        superadmin_ids="123",
        _env_file=None,
    )


class CapturingIssueRepo:
    def __init__(self) -> None:
        self.kwargs: dict[str, object] = {}

    async def issue(self, **kwargs: object) -> None:
        self.kwargs = kwargs


class CapturingUserRepo:
    async def upsert(self, **_: object) -> None:
        return None


class CapturingUow:
    def __init__(self) -> None:
        self.website_tokens = CapturingIssueRepo()
        self.users = CapturingUserRepo()

    async def __aenter__(self) -> CapturingUow:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


@pytest.mark.asyncio
async def test_bot_persists_only_digest_and_puts_raw_token_in_fragment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uow = CapturingUow()
    settings = _settings().model_copy(update={"website_url": "https://example.test/account"})
    monkeypatch.setattr(private, "UnitOfWork", lambda: uow)
    monkeypatch.setattr(private, "get_settings", lambda: settings)
    monkeypatch.setattr(private, "generate_token", lambda: TOKEN)

    screen = await private._website_screen(
        User(id=123, is_bot=False, first_name="Ada", language_code="ru"),
        translator("ru"),
    )
    button_url = screen.keyboard.inline_keyboard[0][0].url if screen.keyboard else None
    copy_button = screen.keyboard.inline_keyboard[1][0].copy_text if screen.keyboard else None

    assert button_url == f"https://example.test/account#token={TOKEN}"
    assert copy_button is not None and copy_button.text == TOKEN
    assert f"<code>{TOKEN}</code>" in screen.text
    assert uow.website_tokens.kwargs["token_hash"] == token_digest(TOKEN)
    assert uow.website_tokens.kwargs["scope"] == WEBSITE_SCOPE
    assert TOKEN not in str(uow.website_tokens.kwargs)


def test_private_router_accepts_key_alias_for_website_login() -> None:
    router = private.build_router()
    command_sets = {
        command
        for observer in router.message.handlers
        for filter_object in observer.filters
        for command in getattr(getattr(filter_object, "callback", None), "commands", ())
        if isinstance(command, str)
    }

    assert {"website", "site", "key"} <= command_sets


@pytest.mark.asyncio
async def test_website_exchange_is_single_use_and_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    tokens = FakeWebsiteTokens(
        TOKEN, user_id=123, expires_at=NOW + timedelta(minutes=5), scope=WEBSITE_SCOPE
    )
    uow = SimpleNamespace(
        website_tokens=tokens,
        users=FakeUsers(TgUser(tg_user_id=123, first_name="Ada", language_code="ru")),
    )
    settings = _settings()
    monkeypatch.setattr("api.routers.auth.datetime", SimpleNamespace(now=lambda _: NOW))
    monkeypatch.setattr("api.security.get_settings", lambda: settings)

    response = await authenticate_website(
        WebsiteLoginRequest(token=TOKEN), settings, cast(UnitOfWork, uow)
    )
    principal = decode_token(response.access_token)
    assert principal.tg_user_id == 123
    assert tokens.calls == [(token_digest(TOKEN), WEBSITE_SCOPE)]
    assert tokens.consumed


@pytest.mark.asyncio
async def test_expired_or_replayed_website_token_is_rejected() -> None:
    from shared.errors import InvalidSessionError

    expired = FakeWebsiteTokens(
        TOKEN, user_id=123, expires_at=NOW - timedelta(seconds=1), scope=WEBSITE_SCOPE
    )
    uow = SimpleNamespace(website_tokens=expired, users=FakeUsers(None))
    with pytest.raises(InvalidSessionError):
        await authenticate_website(
            WebsiteLoginRequest(token=TOKEN), _settings(), cast(UnitOfWork, uow)
        )

    replayed = FakeWebsiteTokens(
        TOKEN, user_id=123, expires_at=NOW + timedelta(minutes=5), scope=WEBSITE_SCOPE
    )
    replayed.consumed = True
    uow.website_tokens = replayed
    with pytest.raises(InvalidSessionError):
        await authenticate_website(
            WebsiteLoginRequest(token=TOKEN), _settings(), cast(UnitOfWork, uow)
        )


@pytest.mark.asyncio
async def test_wrong_scope_is_rejected() -> None:
    from shared.errors import InvalidSessionError

    tokens = FakeWebsiteTokens(
        TOKEN, user_id=123, expires_at=NOW + timedelta(minutes=5), scope="other"
    )
    uow = SimpleNamespace(website_tokens=tokens, users=FakeUsers(None))
    with pytest.raises(InvalidSessionError):
        await authenticate_website(
            WebsiteLoginRequest(token=TOKEN), _settings(), cast(UnitOfWork, uow)
        )
