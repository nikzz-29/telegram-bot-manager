"""Focused coverage for group-message middleware edge cases."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from aiogram import Dispatcher
from aiogram.types import Chat, Message, MessageEntity, TelegramObject, User
import pytest

from bot.middlewares import setup
from bot.middlewares.ai_moderation import AiModerationMiddleware
from bot.middlewares.captcha_gate import CaptchaGateMiddleware
from bot.middlewares.content_filters import ContentFilterMiddleware
from bot.middlewares.stop_words import StopWordFloodMiddleware
from core.admins import admins
from core.ai_moderation import AiDecision
from core.ai_provider import Verdict
from core.anti_flood import anti_flood
from core.captcha import captcha
from core.context import ChatContext, chat_context
from core.sender import sender
from shared.enums import AiVerdictLabel, ModerationAction, ModuleName, Plan
from shared.plans import FREE_FEATURES, Feature
from shared.schemas.module_configs import (
    AiModerationConfig,
    ContentFilters,
    EntryConfig,
    ModerationConfig,
)

TG_CHAT_ID = -100_123
CHAT_ID = 7
USER_ID = 42


def _ctx(
    *,
    modules: frozenset[str] = frozenset({ModuleName.MODERATION.value}),
    features: frozenset[Feature] = FREE_FEATURES,
    moderation: ModerationConfig | None = None,
    entry: EntryConfig | None = None,
) -> ChatContext:
    return ChatContext(
        chat_id=CHAT_ID,
        tg_chat_id=TG_CHAT_ID,
        title="Test",
        plan=Plan.FREE,
        features=features,
        enabled_modules=modules,
        moderation=moderation or ModerationConfig(),
        entry=entry or EntryConfig(),
    )


def _message(
    *,
    text: str | None = None,
    from_user: User | None = None,
    sender_chat: Chat | None = None,
    **fields: Any,
) -> Message:
    return Message(
        message_id=99,
        date=datetime.now(UTC),
        chat=Chat(id=TG_CHAT_ID, type="supergroup", title="Test"),
        from_user=from_user,
        sender_chat=sender_chat,
        text=text,
        **fields,
    )


def _user() -> User:
    return User(id=USER_ID, is_bot=False, first_name="Ada")


def _handler(
    calls: list[TelegramObject],
) -> Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]:
    async def handler(event: TelegramObject, _data: dict[str, Any]) -> str:
        calls.append(event)
        return "handled"

    return handler


async def test_senderless_service_message_can_be_deleted(monkeypatch: pytest.MonkeyPatch) -> None:
    queued: list[Any] = []
    calls: list[TelegramObject] = []
    monkeypatch.setattr(sender, "enqueue", lambda method, **_kwargs: queued.append(method))
    event = _message(new_chat_title="Renamed")
    ctx = _ctx(moderation=ModerationConfig(delete_service_messages=True))

    result = await ContentFilterMiddleware()(_handler(calls), event, {"ctx": ctx})

    assert result is None
    assert calls == []
    assert len(queued) == 1
    assert queued[0].chat_id == TG_CHAT_ID
    assert queued[0].message_id == event.message_id


async def test_senderless_filtered_message_is_deleted(monkeypatch: pytest.MonkeyPatch) -> None:
    queued: list[Any] = []
    monkeypatch.setattr(sender, "enqueue", lambda method, **_kwargs: queued.append(method))
    event = _message(
        text="https://example.com",
        sender_chat=Chat(id=-100_999, type="channel", title="Channel"),
        entities=[MessageEntity(type="url", offset=0, length=19)],
    )
    ctx = _ctx(
        moderation=ModerationConfig(
            filters=ContentFilters(links=True),
            exempt_admins=True,
        )
    )

    result = await ContentFilterMiddleware()(_handler([]), event, {"ctx": ctx})

    assert result is None
    assert len(queued) == 1
    assert queued[0].message_id == event.message_id


async def test_anonymous_admin_is_exempt_from_content_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[TelegramObject] = []

    async def unexpected_admin_lookup(*_args: Any) -> bool:
        raise AssertionError("anonymous administrators must not be looked up by fake user id")

    monkeypatch.setattr(admins, "is_admin", unexpected_admin_lookup)
    event = _message(
        text="https://example.com",
        from_user=User(id=1087968824, is_bot=True, first_name="GroupAnonymousBot"),
        sender_chat=Chat(id=TG_CHAT_ID, type="supergroup", title="Test"),
        entities=[MessageEntity(type="url", offset=0, length=19)],
    )
    ctx = _ctx(
        moderation=ModerationConfig(
            filters=ContentFilters(links=True),
            exempt_admins=True,
        )
    )

    result = await ContentFilterMiddleware()(_handler(calls), event, {"ctx": ctx})

    assert result == "handled"
    assert calls == [event]


async def test_ai_moderation_skips_admin_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[TelegramObject] = []
    inspected = False

    async def is_admin(_chat_id: int, _user_id: int) -> bool:
        return True

    async def inspect(*_args: Any, **_kwargs: Any) -> AiDecision:
        nonlocal inspected
        inspected = True
        return AiDecision(
            verdict=Verdict(label=AiVerdictLabel.SCAM, confidence=0.99),
            action=ModerationAction.DELETE,
            checked=True,
        )

    async def config(*_args: Any, **_kwargs: Any) -> AiModerationConfig:
        return AiModerationConfig(min_text_length=1)

    monkeypatch.setattr(admins, "is_admin", is_admin)
    monkeypatch.setattr(chat_context, "config", config)
    monkeypatch.setattr("bot.middlewares.ai_moderation.ai_moderation.inspect", inspect)
    event = _message(text="fake support asks for a code", from_user=_user())
    ctx = _ctx(modules=frozenset({ModuleName.AI_MODERATION.value}))

    result = await AiModerationMiddleware()(_handler(calls), event, {"ctx": ctx})

    assert result == "handled"
    assert calls == [event]
    assert inspected is False


async def test_ai_moderation_test_mode_checks_admin_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[TelegramObject] = []
    enforced: list[ModerationAction] = []

    async def is_admin(_chat_id: int, _user_id: int) -> bool:
        return True

    async def config(*_args: Any, **_kwargs: Any) -> AiModerationConfig:
        return AiModerationConfig(min_text_length=1, test_admin_messages=True)

    async def inspect(*_args: Any, **_kwargs: Any) -> AiDecision:
        return AiDecision(
            verdict=Verdict(label=AiVerdictLabel.SCAM, confidence=0.99),
            action=ModerationAction.DELETE,
            checked=True,
        )

    async def record(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def enforce(*_args: Any, **kwargs: Any) -> None:
        enforced.append(kwargs["action"])

    monkeypatch.setattr(admins, "is_admin", is_admin)
    monkeypatch.setattr(chat_context, "config", config)
    monkeypatch.setattr("bot.middlewares.ai_moderation.ai_moderation.inspect", inspect)
    monkeypatch.setattr("bot.middlewares.ai_moderation.ai_moderation.record", record)
    monkeypatch.setattr("bot.middlewares.ai_moderation.enforce", enforce)
    event = _message(text="fake support asks for a code", from_user=_user())
    ctx = _ctx(modules=frozenset({ModuleName.AI_MODERATION.value}))

    result = await AiModerationMiddleware()(_handler(calls), event, {"ctx": ctx})

    assert result is None
    assert calls == []
    assert enforced == [ModerationAction.DELETE]


async def test_senderless_stop_word_message_is_deleted(monkeypatch: pytest.MonkeyPatch) -> None:
    queued: list[Any] = []
    monkeypatch.setattr(sender, "enqueue", lambda method, **_kwargs: queued.append(method))
    event = _message(text="bad word", sender_chat=Chat(id=-100_999, type="channel"))
    ctx = _ctx(
        moderation=ModerationConfig(
            stop_words=["bad"],
            exempt_admins=False,
            anti_flood_enabled=False,
        )
    )

    result = await StopWordFloodMiddleware()(_handler([]), event, {"ctx": ctx})

    assert result is None
    assert len(queued) == 1
    assert queued[0].message_id == event.message_id


async def test_anonymous_admin_is_exempt_from_stop_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[TelegramObject] = []
    flood_checks: list[int] = []

    async def check(_chat_id: int, user_id: int, **_kwargs: Any) -> None:
        flood_checks.append(user_id)
        return None

    monkeypatch.setattr(anti_flood, "check", check)
    event = _message(
        text="bad word",
        from_user=User(id=1087968824, is_bot=True, first_name="GroupAnonymousBot"),
        sender_chat=Chat(id=TG_CHAT_ID, type="supergroup", title="Test"),
    )
    ctx = _ctx(moderation=ModerationConfig(stop_words=["bad"], exempt_admins=True))

    result = await StopWordFloodMiddleware()(_handler(calls), event, {"ctx": ctx})

    assert result == "handled"
    assert calls == [event]
    assert flood_checks == [1087968824]


async def test_edited_message_does_not_increment_anti_flood(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[TelegramObject] = []

    async def unexpected_check(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("edited messages must not increment anti-flood")

    monkeypatch.setattr(anti_flood, "check", unexpected_check)
    event = _message(text="edited", from_user=_user())
    ctx = _ctx(moderation=ModerationConfig(exempt_admins=False))

    result = await StopWordFloodMiddleware(count_flood=False)(_handler(calls), event, {"ctx": ctx})

    assert result == "handled"
    assert calls == [event]


@pytest.mark.parametrize(
    ("modules", "features"),
    [
        (frozenset(), frozenset({Feature.CAPTCHA})),
        (frozenset({ModuleName.ENTRY.value}), frozenset()),
    ],
)
async def test_captcha_gate_ignores_disabled_or_locked_feature(
    monkeypatch: pytest.MonkeyPatch,
    modules: frozenset[str],
    features: frozenset[Feature],
) -> None:
    calls: list[TelegramObject] = []

    async def unexpected_pending(*_args: Any) -> bool:
        raise AssertionError("disabled captcha must not query pending state")

    monkeypatch.setattr(captcha, "is_pending", unexpected_pending)
    event = _message(text="hello", from_user=_user())
    ctx = _ctx(
        modules=modules,
        features=features,
        entry=EntryConfig(captcha_enabled=True),
    )

    result = await CaptchaGateMiddleware()(_handler(calls), event, {"ctx": ctx})

    assert result == "handled"
    assert calls == [event]


async def test_captcha_gate_blocks_pending_member_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queued: list[Any] = []

    async def pending(_chat_id: int, _user_id: int) -> bool:
        return True

    monkeypatch.setattr(captcha, "is_pending", pending)
    monkeypatch.setattr(sender, "enqueue", lambda method, **_kwargs: queued.append(method))
    event = _message(text="hello", from_user=_user())
    ctx = _ctx(
        modules=frozenset({ModuleName.ENTRY.value}),
        features=frozenset({Feature.CAPTCHA}),
        entry=EntryConfig(captcha_enabled=True),
    )

    result = await CaptchaGateMiddleware()(_handler([]), event, {"ctx": ctx})

    assert result is None
    assert len(queued) == 1
    assert queued[0].message_id == event.message_id


def test_setup_marks_edited_message_middleware_as_non_counting() -> None:
    dispatcher = Dispatcher(disable_fsm=True)
    setup(dispatcher)

    message_stop_words = next(
        middleware
        for middleware in dispatcher.message.outer_middleware._middlewares
        if isinstance(middleware, StopWordFloodMiddleware)
    )
    edited_stop_words = next(
        middleware
        for middleware in dispatcher.edited_message.outer_middleware._middlewares
        if isinstance(middleware, StopWordFloodMiddleware)
    )

    assert message_stop_words._count_flood is True
    assert edited_stop_words._count_flood is False
