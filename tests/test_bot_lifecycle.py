"""Telegram bot membership lifecycle and administrator mirroring."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from aiogram.enums import ChatMemberStatus
from aiogram.types import Chat, ChatMemberUpdated
import pytest

from bot import __main__ as bot_main
from bot import lifecycle
from core import admins as admins_module
from core import cache
from core.admins import AdminService, admins
from core.context import ChatContext
from shared.enums import AdminRole


class _FakeChatRepo:
    def __init__(self) -> None:
        self.updates: list[tuple[int, dict[str, Any]]] = []

    async def update_fields(self, chat_id: int, **fields: Any) -> None:
        self.updates.append((chat_id, fields))


class _FakeAdminRepo:
    def __init__(self) -> None:
        self.replaced: list[tuple[int, dict[int, AdminRole]]] = []

    async def replace_for_chat(self, chat_id: int, roles: dict[int, AdminRole]) -> None:
        self.replaced.append((chat_id, roles))


class _FakeUow:
    def __init__(self) -> None:
        self.chats = _FakeChatRepo()
        self.admins = _FakeAdminRepo()
        self.commits = 0

    async def __aenter__(self) -> _FakeUow:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


def _event(status: ChatMemberStatus) -> Any:
    return SimpleNamespace(
        chat=Chat(id=-100, type="supergroup", title="Updated", username="updated"),
        new_chat_member=SimpleNamespace(status=status),
    )


@pytest.mark.asyncio
async def test_adding_bot_activates_chat_and_syncs_admins(monkeypatch: pytest.MonkeyPatch) -> None:
    uow = _FakeUow()
    synced: list[tuple[int, int]] = []

    async def sync_to_db(chat_id: int, tg_chat_id: int) -> int:
        synced.append((chat_id, tg_chat_id))
        return 2

    monkeypatch.setattr(lifecycle, "UnitOfWork", lambda: uow)
    monkeypatch.setattr(admins, "sync_to_db", sync_to_db)

    ctx = cast(ChatContext, SimpleNamespace(chat_id=7, tg_chat_id=-100))
    await lifecycle.handle_bot_membership(_event(ChatMemberStatus.ADMINISTRATOR), ctx)

    assert uow.chats.updates[0][1]["is_active"] is True
    assert "owner_tg_id" not in uow.chats.updates[0][1]
    assert synced == [(7, -100)]


@pytest.mark.asyncio
async def test_demotion_deactivates_chat_but_still_refreshes_admins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uow = _FakeUow()
    synced: list[int] = []

    async def sync_to_db(chat_id: int, tg_chat_id: int) -> int:
        synced.append(chat_id)
        return 1

    monkeypatch.setattr(lifecycle, "UnitOfWork", lambda: uow)
    monkeypatch.setattr(admins, "sync_to_db", sync_to_db)

    await lifecycle.handle_bot_membership(
        _event(ChatMemberStatus.MEMBER),
        cast(ChatContext, SimpleNamespace(chat_id=7, tg_chat_id=-100)),
    )

    assert uow.chats.updates[0][1]["is_active"] is False
    assert synced == [7]


@pytest.mark.asyncio
async def test_removal_deactivates_chat_and_invalidates_admin_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uow = _FakeUow()
    invalidated: list[int] = []

    async def invalidate(tg_chat_id: int) -> None:
        invalidated.append(tg_chat_id)

    monkeypatch.setattr(lifecycle, "UnitOfWork", lambda: uow)
    monkeypatch.setattr(admins, "invalidate", invalidate)

    await lifecycle.handle_bot_membership(
        _event(ChatMemberStatus.LEFT),
        cast(ChatContext, SimpleNamespace(chat_id=7, tg_chat_id=-100)),
    )

    assert uow.chats.updates[0][1]["is_active"] is False
    assert invalidated == [-100]


@pytest.mark.asyncio
async def test_admin_sync_updates_owner_from_telegram_creator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uow = _FakeUow()

    class FakeBot:
        async def get_chat_member(self, _chat_id: int, _user_id: int) -> Any:
            return SimpleNamespace(status=ChatMemberStatus.MEMBER)

        async def get_chat_administrators(self, _chat_id: int) -> list[Any]:
            return [
                SimpleNamespace(
                    user=SimpleNamespace(id=11, is_bot=False),
                    status=ChatMemberStatus.CREATOR,
                ),
                SimpleNamespace(
                    user=SimpleNamespace(id=12, is_bot=False),
                    status=ChatMemberStatus.ADMINISTRATOR,
                ),
            ]

    async def invalidate_admins(_tg_chat_id: int) -> None:
        return None

    monkeypatch.setattr(admins_module, "UnitOfWork", lambda: uow)
    monkeypatch.setattr(cache, "invalidate_admins", invalidate_admins)

    count = await AdminService(FakeBot()).sync_to_db(7, -100)

    assert count == 2
    assert uow.admins.replaced == [(7, {11: AdminRole.OWNER, 12: AdminRole.ADMIN})]
    assert uow.chats.updates == [(7, {"owner_tg_id": 11})]


def test_dispatcher_requests_bot_membership_updates() -> None:
    dispatcher = bot_main.build_dispatcher()
    assert "my_chat_member" in dispatcher.resolve_used_update_types()


@pytest.mark.asyncio
async def test_admin_promotion_refreshes_the_mirror(monkeypatch: pytest.MonkeyPatch) -> None:
    synced: list[tuple[int, int]] = []

    async def sync_to_db(chat_id: int, tg_chat_id: int) -> int:
        synced.append((chat_id, tg_chat_id))
        return 1

    monkeypatch.setattr(admins, "sync_to_db", sync_to_db)
    event = cast(
        ChatMemberUpdated,
        SimpleNamespace(
            old_chat_member=SimpleNamespace(status=ChatMemberStatus.MEMBER),
            new_chat_member=SimpleNamespace(
                status=ChatMemberStatus.ADMINISTRATOR,
                user=SimpleNamespace(is_bot=False),
            ),
        ),
    )
    ctx = cast(ChatContext, SimpleNamespace(chat_id=7, tg_chat_id=-100))

    changed = await lifecycle.sync_administrator_membership(event, ctx)

    assert changed is True
    assert synced == [(7, -100)]
