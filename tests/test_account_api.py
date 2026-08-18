"""User-level Mini App profile and dashboard endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

from fastapi import FastAPI
import httpx
import pytest

from api.deps import get_admin_service, get_principal, get_uow
from api.routers.account import get_user_dashboard, get_user_profile
from api.routers.account import router as account_router
from api.security import Principal
from db.models import Chat
from db.uow import UnitOfWork
from shared.enums import ChatType, Plan
from shared.errors import ChatNotFoundError
from shared.time_utils import utc_now

USER_ID = 7_654_321
PRINCIPAL = Principal(
    tg_user_id=USER_ID,
    username="ada",
    first_name="Ada",
    last_name="Lovelace",
    language="ru",
    is_premium=True,
)


def make_chat(chat_id: int, *, plan: Plan, owner: bool, members: int) -> Chat:
    return Chat(
        id=chat_id,
        tg_chat_id=-1_001_000 - chat_id,
        title=f"Chat {chat_id}",
        type=ChatType.SUPERGROUP,
        plan=plan,
        plan_expires_at=None,
        grace_until=None,
        owner_tg_id=USER_ID if owner else 99,
        language="ru",
        timezone="UTC",
        members_count=members,
        is_active=True,
        settings={},
    )


class FakeChats:
    def __init__(self, chats: list[Chat]) -> None:
        self.items = chats

    async def list_for_admin(self, tg_user_id: int) -> list[Chat]:
        assert tg_user_id == USER_ID
        return self.items


class FakeAdmins:
    def __init__(self, admin_tg_chat_ids: set[int] | None = None) -> None:
        self.admin_tg_chat_ids = admin_tg_chat_ids

    async def is_admin(self, tg_chat_id: int, tg_user_id: int) -> bool:
        assert tg_user_id == USER_ID
        return self.admin_tg_chat_ids is None or tg_chat_id in self.admin_tg_chat_ids


class FakeStats:
    def __init__(self) -> None:
        self.daily_chat_ids: list[int] = []
        self.top_chat_ids: list[int] = []

    async def daily_range_many(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.daily_chat_ids = list(kwargs["chat_ids"])
        today = utc_now().date()
        return [
            {
                "date": today - timedelta(days=1),
                "messages": 40,
                "active_users": 8,
                "joins": 3,
                "leaves": 1,
                "moderation_actions": 0,
            },
            {
                "date": today,
                "messages": 55,
                "active_users": 11,
                "joins": 4,
                "leaves": 2,
                "moderation_actions": 0,
            },
        ]

    async def top_users_many(self, **kwargs: Any) -> list[tuple[int, int]]:
        self.top_chat_ids = list(kwargs["chat_ids"])
        return [(123, 25)]


class FakeModeration:
    async def dashboard_many(self, chat_ids: list[int], **kwargs: Any) -> dict[str, Any]:
        if not chat_ids:
            return {"total": 0, "mine": 0, "automated": 0, "moderators": 0, "breakdown": []}
        if kwargs.get("until") is not None:
            return {"total": 2, "mine": 1, "automated": 0, "moderators": 1, "breakdown": []}
        return {
            "total": 5,
            "mine": 2,
            "automated": 2,
            "moderators": 2,
            "breakdown": [("warn", 3), ("mute", 2)],
        }


class FakeWarns:
    async def count_issued_many(self, chat_ids: list[int], since: datetime) -> int:
        if not chat_ids:
            return 0
        assert since.tzinfo is UTC
        return 3


class FakePunishments:
    async def count_issued_by_type_many(
        self, chat_ids: list[int], since: datetime
    ) -> dict[str, int]:
        if not chat_ids:
            return {}
        return {"mute": 2, "ban": 1, "kick": 4}


class FakeUsers:
    def __init__(self) -> None:
        self.profile = SimpleNamespace(
            username="ada",
            display_name="Ada Lovelace",
            created_at=datetime(2025, 1, 2, tzinfo=UTC),
            has_photo=True,
        )

    async def get(self, tg_user_id: int) -> Any:
        assert tg_user_id == USER_ID
        return self.profile

    async def get_many(self, tg_user_ids: list[int]) -> dict[int, Any]:
        return {
            user_id: SimpleNamespace(username="leader", display_name="Top User")
            for user_id in tg_user_ids
        }


class FakeUow:
    def __init__(self) -> None:
        self.chats = FakeChats(
            [
                make_chat(1, plan=Plan.PRO, owner=True, members=120),
                make_chat(2, plan=Plan.FREE, owner=False, members=80),
            ]
        )
        self.stats = FakeStats()
        self.moderation_logs = FakeModeration()
        self.warns = FakeWarns()
        self.punishments = FakePunishments()
        self.users = FakeUsers()


async def test_profile_contains_account_and_chat_footprint() -> None:
    profile = await get_user_profile(PRINCIPAL, FakeUow(), FakeAdmins())  # type: ignore[arg-type]

    assert profile.display_name == "Ada Lovelace"
    assert profile.user.is_premium is True
    assert profile.user.has_photo is True
    assert profile.chats_total == 2
    assert profile.chats_owned == 1
    assert profile.chats_admin == 1
    assert profile.paid_chats == 1
    assert profile.total_members == 200


async def test_dashboard_batches_paid_analytics_and_keeps_free_moderation() -> None:
    uow = FakeUow()
    dashboard = await get_user_dashboard(
        PRINCIPAL,
        cast(UnitOfWork, uow),
        cast(Any, FakeAdmins()),
        days=1,
        chat_id=None,
    )

    assert dashboard.analytics_available is True
    assert dashboard.totals.messages == 55
    assert dashboard.previous.messages == 40
    assert dashboard.totals.moderation_actions == 5
    assert dashboard.previous.moderation_actions == 2
    assert dashboard.moderation.warns == 3
    assert dashboard.moderation.restrictions == 3
    assert dashboard.moderation.mine == 2
    assert dashboard.series[0].messages == 55
    assert dashboard.top_users[0].display_name == "Top User"
    assert uow.stats.daily_chat_ids == [1]
    assert uow.stats.top_chat_ids == [1]
    assert len(dashboard.chats) == 2


async def test_dashboard_rejects_a_chat_outside_the_user_scope() -> None:
    with pytest.raises(ChatNotFoundError):
        await get_user_dashboard(
            PRINCIPAL,
            cast(UnitOfWork, FakeUow()),
            cast(Any, FakeAdmins()),
            days=7,
            chat_id=999,
        )


async def test_dashboard_accepts_a_period_from_the_http_query_string() -> None:
    app = FastAPI()
    app.include_router(account_router, prefix="/api")
    app.dependency_overrides[get_principal] = lambda: PRINCIPAL
    app.dependency_overrides[get_uow] = FakeUow
    app.dependency_overrides[get_admin_service] = FakeAdmins

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
        response = await client.get("/api/me/dashboard?days=7")

    assert response.status_code == 200
    assert response.json()["period_days"] == 7


async def test_dashboard_excludes_stale_and_inactive_mirror_rows() -> None:
    uow = FakeUow()
    uow.chats.items[1].is_active = False
    uow.chats.items.append(make_chat(3, plan=Plan.PRO, owner=True, members=10))
    admins = FakeAdmins({uow.chats.items[1].tg_chat_id})

    dashboard = await get_user_dashboard(
        PRINCIPAL,
        cast(UnitOfWork, uow),
        cast(Any, admins),
        days=1,
        chat_id=None,
    )

    assert dashboard.scoped_chat_count == 0
    assert dashboard.analytics_chat_count == 0
    assert dashboard.chats == []
    assert uow.stats.daily_chat_ids == []


async def test_dashboard_aggregate_excludes_a_live_mirror_stale_admin() -> None:
    uow = FakeUow()
    admins = FakeAdmins({uow.chats.items[0].tg_chat_id})

    dashboard = await get_user_dashboard(
        PRINCIPAL,
        cast(UnitOfWork, uow),
        cast(Any, admins),
        days=1,
        chat_id=None,
    )

    assert dashboard.scoped_chat_count == 1
    assert dashboard.analytics_chat_count == 1
    assert [chat.id for chat in dashboard.chats] == [1]
    assert uow.stats.daily_chat_ids == [1]


async def test_dashboard_selected_chat_requires_live_admin_and_active_row() -> None:
    uow = FakeUow()
    admins = FakeAdmins({uow.chats.items[0].tg_chat_id})
    uow.chats.items[1].is_active = False

    with pytest.raises(ChatNotFoundError):
        await get_user_dashboard(
            PRINCIPAL,
            cast(UnitOfWork, uow),
            cast(Any, admins),
            days=7,
            chat_id=2,
        )

    with pytest.raises(ChatNotFoundError):
        await get_user_dashboard(
            PRINCIPAL,
            cast(UnitOfWork, uow),
            cast(Any, FakeAdmins(set())),
            days=7,
            chat_id=1,
        )
