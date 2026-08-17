from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

from fastapi import FastAPI
import httpx
import pytest

from api.app import create_app
from api.deps import get_principal, get_uow
from api.routers import platform as platform_router
from api.security import Principal
from core import cache
from db.models import Chat, Payment
from db.repositories.platform import (
    PlatformDay,
    PlatformPaymentRow,
    PlatformPlanRow,
    PlatformTotals,
    PlatformUserRow,
)
from shared.config import Settings
from shared.enums import ChatType, PaymentProvider, PaymentStatus, Plan
from shared.plans import (
    DEFAULT_PLAN_FEATURES,
    DEFAULT_PLAN_PRICES,
    reset_plan_overrides,
)

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
USER_ID = 7_654_321


def _chat(**overrides: Any) -> Chat:
    chat = Chat(
        id=11,
        tg_chat_id=-1001234567890,
        title="Operator Chat",
        username="operator_chat",
        type=ChatType.SUPERGROUP,
        plan=Plan.PRO,
        plan_expires_at=None,
        grace_until=None,
        owner_tg_id=USER_ID,
        language="ru",
        timezone="Europe/Moscow",
        members_count=321,
        is_active=True,
        settings={},
    )
    for key, value in overrides.items():
        setattr(chat, key, value)
    return chat


def _user() -> PlatformUserRow:
    return PlatformUserRow(
        tg_user_id=USER_ID,
        username="ada",
        first_name="Ada",
        last_name="Lovelace",
        is_bot=False,
        first_seen_at=NOW,
        last_seen_at=NOW,
        admin_chats=2,
        owned_chats=1,
        is_globally_banned=False,
        ban_reports=0,
        payments=1,
        spent_stars=299,
        spent_usd=Decimal("0"),
        last_payment_at=NOW,
    )


class FakePlatformRepository:
    def __init__(self) -> None:
        self.user_page_kwargs: dict[str, Any] = {}
        self.payment_page_kwargs: dict[str, Any] = {}
        self.user_chat = _chat()

    async def totals(self, *, start: date, end: date) -> PlatformTotals:
        assert end >= start
        return PlatformTotals(
            chats=5,
            active_chats=4,
            paying_chats=2,
            new_chats=1,
            known_users=20,
            messages=900,
            active_chats_in_window=3,
            moderation_actions=12,
            subscriptions=2,
            refunds=1,
            revenue_stars=598,
            revenue_usd=Decimal("14.99"),
            refunded_stars=299,
            refunded_usd=Decimal("0"),
        )

    async def daily_series(self, *, start: date, end: date) -> list[PlatformDay]:
        return [
            PlatformDay(
                day=start,
                chats=5,
                new_chats=1,
                active_chats=3,
                messages=900,
                moderation_actions=12,
                joins=8,
                leaves=2,
                subscriptions=2,
                revenue_stars=598,
                revenue_usd=Decimal("14.99"),
                refunds=1,
                churned_chats=0,
            )
        ]

    async def plan_mix(self, *, start: date, end: date) -> list[PlatformPlanRow]:
        return [
            PlatformPlanRow(
                plan=Plan.PRO,
                chats=2,
                active_chats=2,
                subscriptions=2,
                revenue_stars=598,
                revenue_usd=Decimal("0"),
            )
        ]

    async def user_page(self, **kwargs: Any) -> tuple[list[PlatformUserRow], int]:
        self.user_page_kwargs = kwargs
        return [_user()], 1

    async def user_chats(self, tg_user_id: int, *, limit: int = 50) -> list[Chat]:
        assert tg_user_id == USER_ID
        return [self.user_chat]

    async def payment_page(self, **kwargs: Any) -> tuple[list[PlatformPaymentRow], int]:
        self.payment_page_kwargs = kwargs
        payment = SimpleNamespace(
            id=91,
            chat_id=11,
            provider=PaymentProvider.STARS,
            provider_payment_id="stars-91",
            amount=Decimal("299"),
            currency="XTR",
            status=PaymentStatus.PAID,
            plan=Plan.PRO,
            months=1,
            payer_tg_id=USER_ID,
            created_at=NOW,
            period_start=NOW,
            period_end=NOW,
            refunded_at=None,
            refund_reason="",
        )
        return [
            PlatformPaymentRow(
                payment=cast(Payment, payment), chat_title="Operator Chat", tg_chat_id=-1
            )
        ], 1


class FakeChatRepository:
    def __init__(self) -> None:
        self.grants: list[tuple[int, Plan, datetime | None, datetime | None]] = []

    async def set_plan(
        self,
        chat_id: int,
        plan: Plan,
        *,
        expires_at: datetime | None,
        grace_until: datetime | None = None,
    ) -> None:
        self.grants.append((chat_id, plan, expires_at, grace_until))


class FakePlanOverrideRepository:
    def __init__(self) -> None:
        self.rows: dict[Plan, SimpleNamespace] = {}
        self.saved: list[tuple[Plan, dict[str, Any]]] = []
        self.deleted: list[Plan] = []

    async def list_all(self) -> list[SimpleNamespace]:
        return list(self.rows.values())

    async def save(self, plan: Plan, **kwargs: Any) -> SimpleNamespace:
        self.saved.append((plan, kwargs))
        row = SimpleNamespace(
            plan=plan,
            stars=kwargs["stars"],
            usd=kwargs["usd"],
            features=kwargs["features"],
            note=kwargs["note"],
            updated_by=kwargs["updated_by"],
            updated_at=NOW,
        )
        self.rows[plan] = row
        return row

    async def delete(self, plan: Plan) -> bool:
        self.deleted.append(plan)
        return self.rows.pop(plan, None) is not None


class FakePlatformSettingRepository:
    def __init__(self) -> None:
        self.saved: list[tuple[str, dict[str, Any], int]] = []

    async def set(self, key: str, value: dict[str, Any], *, updated_by: int) -> SimpleNamespace:
        self.saved.append((key, value, updated_by))
        return SimpleNamespace(key=key, value=value, updated_by=updated_by)


class FakeUow:
    def __init__(self) -> None:
        self.platform = FakePlatformRepository()
        self.chats = FakeChatRepository()
        self.plan_overrides = FakePlanOverrideRepository()
        self.platform_settings = FakePlatformSettingRepository()
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class PlatformBed:
    def __init__(self, app: FastAPI, client: httpx.AsyncClient, uow: FakeUow) -> None:
        self.app = app
        self.client = client
        self.uow = uow


@pytest.fixture
async def platform_bed() -> AsyncIterator[PlatformBed]:
    cache.cache.setup("mem://")
    reset_plan_overrides()
    uow = FakeUow()
    app = create_app()
    app.dependency_overrides[get_uow] = lambda: uow
    app.dependency_overrides[get_principal] = lambda: Principal(
        tg_user_id=USER_ID,
        first_name="Ada",
        is_superadmin=True,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api"
    ) as client:
        yield PlatformBed(app, client, uow)
    reset_plan_overrides()


async def test_platform_routes_reject_non_superadmins(platform_bed: PlatformBed) -> None:
    platform_bed.app.dependency_overrides[get_principal] = lambda: Principal(tg_user_id=1)

    response = await platform_bed.client.get("/api/platform/dashboard")

    assert response.status_code == 403
    assert response.json()["code"] == "not-chat-admin"


async def test_platform_dashboard_returns_repository_aggregates(
    platform_bed: PlatformBed,
) -> None:
    response = await platform_bed.client.get("/api/platform/dashboard", params={"days": 7})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["days"] == 7
    assert body["totals"]["messages"] == 900
    assert body["series"][0]["revenue_stars"] == 598
    assert body["plan_mix"][0]["plan"] == "pro"


@pytest.mark.parametrize("days", [1, 7, 30, 90, 365])
async def test_platform_dashboard_accepts_supported_periods(
    platform_bed: PlatformBed, days: int
) -> None:
    response = await platform_bed.client.get("/api/platform/dashboard", params={"days": days})

    assert response.status_code == 200, response.text
    assert response.json()["days"] == days


async def test_platform_dashboard_rejects_an_arbitrary_period(platform_bed: PlatformBed) -> None:
    response = await platform_bed.client.get("/api/platform/dashboard", params={"days": 14})

    assert response.status_code == 422


async def test_platform_users_forwards_search_and_filters(platform_bed: PlatformBed) -> None:
    response = await platform_bed.client.get(
        "/api/platform/users",
        params={
            "search": "@ada",
            "banned_only": True,
            "admins_only": True,
            "limit": 25,
            "offset": 50,
        },
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["tg_user_id"] == USER_ID
    assert platform_bed.uow.platform.user_page_kwargs == {
        "search": "@ada",
        "banned_only": True,
        "admins_only": True,
        "limit": 25,
        "offset": 50,
    }


async def test_platform_user_detail_contains_administered_chats(
    platform_bed: PlatformBed,
) -> None:
    response = await platform_bed.client.get(f"/api/platform/users/{USER_ID}")

    assert response.status_code == 200
    assert response.json()["user"]["username"] == "ada"
    assert response.json()["chats"][0]["title"] == "Operator Chat"
    assert platform_bed.uow.platform.user_page_kwargs == {
        "tg_user_id": USER_ID,
        "limit": 1,
        "offset": 0,
    }


async def test_platform_payments_are_paginated_and_filterable(platform_bed: PlatformBed) -> None:
    response = await platform_bed.client.get(
        "/api/platform/payments",
        params={
            "status": "paid",
            "provider": "cryptobot",
            "tg_user_id": USER_ID,
            "limit": 10,
        },
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["provider_payment_id"] == "stars-91"
    assert platform_bed.uow.platform.payment_page_kwargs == {
        "status": PaymentStatus.PAID,
        "provider": PaymentProvider.CRYPTOBOT,
        "tg_user_id": USER_ID,
        "limit": 10,
        "offset": 0,
    }


async def test_superadmin_can_grant_a_chat_subscription(platform_bed: PlatformBed) -> None:
    response = await platform_bed.client.post(
        f"/api/platform/users/{USER_ID}/subscription",
        json={"chat_id": 11, "plan": "business", "months": 3},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    grant = platform_bed.uow.chats.grants[0]
    assert grant[0:2] == (11, Plan.BUSINESS)
    assert grant[2] is not None
    assert platform_bed.uow.commits == 1


async def test_granting_free_clears_the_subscription_expiry(platform_bed: PlatformBed) -> None:
    response = await platform_bed.client.post(
        f"/api/platform/users/{USER_ID}/subscription",
        json={"chat_id": 11, "plan": "free", "months": 1},
    )

    assert response.status_code == 200
    assert platform_bed.uow.chats.grants[0] == (11, Plan.FREE, None, None)


async def test_granting_the_same_paid_plan_extends_the_existing_term(
    platform_bed: PlatformBed, monkeypatch: pytest.MonkeyPatch
) -> None:
    existing_expiry = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    platform_bed.uow.platform.user_chat = _chat(plan=Plan.PRO, plan_expires_at=existing_expiry)
    monkeypatch.setattr(platform_router, "utc_now", lambda: NOW)

    response = await platform_bed.client.post(
        f"/api/platform/users/{USER_ID}/subscription",
        json={"chat_id": 11, "plan": "pro", "months": 2},
    )

    assert response.status_code == 200
    assert platform_bed.uow.chats.grants[0][2] == datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


async def test_plan_override_can_be_listed_updated_and_reset(
    platform_bed: PlatformBed,
) -> None:
    update = await platform_bed.client.put(
        "/api/platform/plans/pro",
        json={
            "stars": 555,
            "usd": "7.50",
            "features": ["moderation", "stats"],
            "note": "support offer",
        },
    )

    assert update.status_code == 200
    assert update.json()["effective_stars"] == 555
    assert update.json()["effective_features"] == ["moderation", "stats"]
    saved_plan, saved = platform_bed.uow.plan_overrides.saved[0]
    assert saved_plan == Plan.PRO
    assert saved["updated_by"] == USER_ID

    listing = await platform_bed.client.get("/api/platform/plans")
    assert listing.status_code == 200
    assert len(listing.json()) == len(Plan)
    assert next(row for row in listing.json() if row["plan"] == "pro")["stars"] == 555

    reset = await platform_bed.client.delete("/api/platform/plans/pro")
    assert reset.status_code == 200
    assert reset.json()["effective_stars"] == DEFAULT_PLAN_PRICES[Plan.PRO].stars
    assert reset.json()["effective_features"] == sorted(
        feature.value for feature in DEFAULT_PLAN_FEATURES[Plan.PRO]
    )
    assert platform_bed.uow.plan_overrides.deleted == [Plan.PRO]


async def test_cryptobot_testnet_cannot_be_enabled_in_production(
    platform_bed: PlatformBed, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(_env_file=None).model_copy(update={"app_env": "production"})
    fake_cryptobot = SimpleNamespace(configured=True, testnet=False, network="mainnet")
    monkeypatch.setattr(platform_router, "get_settings", lambda: settings)
    monkeypatch.setattr(platform_router, "cryptobot", fake_cryptobot)

    response = await platform_bed.client.patch(
        "/api/platform/settings/cryptobot", json={"testnet": True}
    )

    assert response.status_code == 409


async def test_cryptobot_testnet_toggle_is_persisted_and_applied(
    platform_bed: PlatformBed, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(_env_file=None)

    class FakeCryptoBot:
        configured = True
        closed = 0

        @property
        def testnet(self) -> bool:
            return settings.cryptobot_testnet

        @property
        def network(self) -> str:
            return "testnet" if self.testnet else "mainnet"

        async def close(self) -> None:
            self.closed += 1

    fake_cryptobot = FakeCryptoBot()
    monkeypatch.setattr(platform_router, "get_settings", lambda: settings)
    monkeypatch.setattr(platform_router, "cryptobot", fake_cryptobot)

    response = await platform_bed.client.patch(
        "/api/platform/settings/cryptobot", json={"testnet": True}
    )

    assert response.status_code == 200, response.text
    assert response.json()["cryptobot"]["testnet"] is True
    assert settings.cryptobot_testnet is True
    assert fake_cryptobot.closed == 1
    assert platform_bed.uow.platform_settings.saved == [
        ("cryptobot_testnet", {"enabled": True}, USER_ID)
    ]
    assert platform_bed.uow.commits == 1
