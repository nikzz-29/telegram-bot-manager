"""Stage 4 routers: triggers, posts, stats and reputation over real HTTP.

The Stage 3 suite proved the auth story once; this one takes it as given and
covers what the content routes add on top:

* the plan gate (402) and the quota gate (409), which are the only thing standing
  between a Free chat and an unbounded number of rows;
* validation of the two user-supplied grammars — trigger patterns and post
  schedules — which reach the database as text and the runtime as behaviour;
* the coupling between a scheduled post and the ARQ queue: `next_run_at` in the
  row and the queued job must never disagree.

DECISION: `stats.overview` and the autopost `arm`/`disarm` pair are patched
rather than faked through their repositories. They open their own `UnitOfWork`
and their own Redis connection, so a fake at the repository level would not be
reached — and the router's job is to clamp the window and keep the queue in step,
not to aggregate rows.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
import httpx
import pytest

from api.app import create_app
from api.deps import (
    get_admin_service,
    get_app_settings,
    get_features,
    get_module_configs,
    get_uow,
)
from api.security import Principal, issue_token
from core import cache
from db.models import Chat, Reputation, ScheduledPost, TgUser, TriggerRule
from shared.config import get_settings
from shared.enums import ChatType, ScheduleKind, TriggerMatch
from shared.errors import FeatureLockedError, LimitExceededError
from shared.plans import PLAN_FEATURES, PLAN_LIMITS, Feature, Plan, PlanLimits, minimum_plan_for
from shared.schemas.api import StatsOverview, TopUser

USER_ID = 7_654_321
CHAT_ID = 1
TG_CHAT_ID = -1001999888777
NOW = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)

PRINCIPAL = Principal(
    tg_user_id=USER_ID,
    username="ada",
    first_name="Ada",
    last_name="Lovelace",
    language="ru",
)


def make_chat(**overrides: Any) -> Chat:
    chat = Chat(
        id=CHAT_ID,
        tg_chat_id=TG_CHAT_ID,
        title="Test Chat",
        type=ChatType.SUPERGROUP,
        plan=Plan.PRO,
        plan_expires_at=None,
        grace_until=None,
        owner_tg_id=USER_ID,
        language="ru",
        timezone="UTC",
        members_count=1234,
        is_active=True,
        settings={},
    )
    for key, value in overrides.items():
        setattr(chat, key, value)
    return chat


# --- fakes ----------------------------------------------------------------------
def with_defaults(row: Any) -> Any:
    """Apply the column defaults SQLAlchemy would fill in at flush time.

    A detached instance leaves every unset column at `None`, so a row the real
    repository would hand back fully populated fails response validation here
    for reasons that have nothing to do with the router under test.
    """
    for column in row.__table__.columns:
        default = column.default
        if default is None or getattr(row, column.name, None) is not None:
            continue
        setattr(row, column.name, default.arg(None) if default.is_callable else default.arg)
    return row


class FakeRowRepo:
    """Shared CRUD for the two row-per-chat tables, keyed by a synthetic id."""

    model: type[Any]

    def __init__(self) -> None:
        self.rows: dict[int, Any] = {}
        self._next_id = 1

    def _add(self, chat_id: int, fields: dict[str, Any]) -> Any:
        row = with_defaults(self.model(id=self._next_id, chat_id=chat_id, **fields))
        self.rows[self._next_id] = row
        self._next_id += 1
        return row

    def seed(self, **fields: Any) -> Any:
        return self._add(CHAT_ID, fields)

    async def list_for_chat(self, chat_id: int, *, enabled_only: bool = False) -> list[Any]:
        rows = [row for row in self.rows.values() if row.chat_id == chat_id]
        return [row for row in rows if row.enabled] if enabled_only else rows

    async def get(self, chat_id: int, row_id: int) -> Any | None:
        row = self.rows.get(row_id)
        return row if row is not None and row.chat_id == chat_id else None

    async def count(self, chat_id: int) -> int:
        return len([row for row in self.rows.values() if row.chat_id == chat_id])

    async def create(self, chat_id: int, **fields: Any) -> Any:
        return self._add(chat_id, fields)

    async def update(self, chat_id: int, row_id: int, **fields: Any) -> Any | None:
        row = self.rows.get(row_id)
        if row is None or row.chat_id != chat_id:
            return None
        for key, value in fields.items():
            setattr(row, key, value)
        return row

    async def delete(self, chat_id: int, row_id: int) -> bool:
        row = self.rows.get(row_id)
        if row is None or row.chat_id != chat_id:
            return False
        del self.rows[row_id]
        return True


class FakeTriggerRepo(FakeRowRepo):
    model = TriggerRule


class FakePostRepo(FakeRowRepo):
    model = ScheduledPost


class FakeChatRepo:
    def __init__(self, chats: dict[int, Chat]) -> None:
        self.chats = chats

    async def get_by_id(self, chat_id: int) -> Chat | None:
        return self.chats.get(chat_id)

    async def update_fields(self, chat_id: int, **fields: Any) -> None:
        for key, value in fields.items():
            setattr(self.chats[chat_id], key, value)


class FakeUserRepo:
    def __init__(self) -> None:
        self.profiles: dict[int, TgUser] = {}

    def seed(self, **fields: Any) -> TgUser:
        user = TgUser(
            tg_user_id=fields["tg_user_id"],
            username=fields.get("username"),
            first_name=fields.get("first_name", ""),
            last_name=fields.get("last_name"),
        )
        self.profiles[user.tg_user_id] = user
        return user

    async def get_many(self, tg_user_ids: list[int]) -> dict[int, TgUser]:
        return {uid: self.profiles[uid] for uid in tg_user_ids if uid in self.profiles}


class FakeReputationRepo:
    def __init__(self) -> None:
        self.rows: dict[int, Reputation] = {}
        self._next_id = 1

    def seed(self, tg_user_id: int, *, points: int = 0, level: int = 1) -> None:
        self.rows[tg_user_id] = with_defaults(
            Reputation(
                id=self._next_id,
                chat_id=CHAT_ID,
                tg_user_id=tg_user_id,
                points=points,
                experience=points,
                level=level,
            )
        )
        self._next_id += 1

    async def get(self, chat_id: int, tg_user_id: int) -> Reputation | None:
        return self.rows.get(tg_user_id)

    async def top(
        self, chat_id: int, *, limit: int = 10, field: str = "points"
    ) -> list[Reputation]:
        rows = sorted(self.rows.values(), key=lambda row: getattr(row, field), reverse=True)
        return rows[:limit]

    async def add_points(self, *, chat_id: int, tg_user_id: int, delta: int) -> Reputation:
        row = self.rows.get(tg_user_id)
        if row is None:
            row = with_defaults(
                Reputation(id=self._next_id, chat_id=chat_id, tg_user_id=tg_user_id)
            )
            self.rows[tg_user_id] = row
            self._next_id += 1
        row.points += delta
        row.weekly_points += delta
        row.monthly_points += delta
        return row


class FakeConfigs:
    """Only `get_as` is reached — the routers read the autopost timezone and stop."""

    def __init__(self) -> None:
        self.stored: dict[str, dict[str, Any]] = {}

    async def get_as(self, chat_id: int, module: Any, model: type[Any]) -> Any:
        key = module.value if hasattr(module, "value") else str(module)
        return model.model_validate(self.stored.get(key, {}))


class FakeUow:
    """One fake per repository the four routers reach for."""

    def __init__(self, chats: dict[int, Chat]) -> None:
        self.chats = FakeChatRepo(chats)
        self.users = FakeUserRepo()
        self.triggers = FakeTriggerRepo()
        self.posts = FakePostRepo()
        self.reputation = FakeReputationRepo()
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class FakeAdmins:
    def __init__(self) -> None:
        self.admin_of = {TG_CHAT_ID}

    async def is_admin(self, tg_chat_id: int, tg_user_id: int) -> bool:
        return tg_chat_id in self.admin_of


class FakeFeatures:
    def __init__(self, plan: Plan = Plan.PRO) -> None:
        self.plan_value = plan

    async def features(self, chat_id: int) -> frozenset[Feature]:
        return PLAN_FEATURES[self.plan_value]

    async def has(self, chat_id: int, feature: Feature) -> bool:
        return feature in PLAN_FEATURES[self.plan_value]

    async def require(self, chat_id: int, feature: Feature) -> None:
        if not await self.has(chat_id, feature):
            raise FeatureLockedError(
                f"Feature '{feature.value}' is locked.",
                feature=feature.value,
                required_plan=minimum_plan_for(feature).value,
            )

    async def limits(self, chat_id: int) -> PlanLimits:
        return PLAN_LIMITS[self.plan_value]

    async def check_quota(self, chat_id: int, resource: str, current: int) -> None:
        allowed = int(getattr(await self.limits(chat_id), resource))
        if current >= allowed:
            raise LimitExceededError(
                f"Plan allows {allowed} {resource}; {current} already exist.",
                resource=resource,
                limit=allowed,
                current=current,
            )


# --- HTTP test bed --------------------------------------------------------------
class Bed:
    """The app plus handles on every fake it was wired with."""

    def __init__(self, app: FastAPI, client: httpx.AsyncClient) -> None:
        self.app = app
        self.client = client
        self.uow: FakeUow
        self.admins: FakeAdmins
        self.features: FakeFeatures
        self.configs: FakeConfigs
        self.chat: Chat

    def auth(self) -> dict[str, str]:
        token, _ = issue_token(PRINCIPAL)
        return {"Authorization": f"Bearer {token}"}

    def url(self, path: str) -> str:
        return f"/api/chats/{CHAT_ID}{path}"


@pytest.fixture
async def bed() -> AsyncIterator[Bed]:
    """`create_app()` with the outward-facing dependencies replaced."""
    cache.cache.setup("mem://")
    chat = make_chat()
    uow = FakeUow({CHAT_ID: chat})
    admins = FakeAdmins()
    features = FakeFeatures()
    configs = FakeConfigs()

    app = create_app()
    app.dependency_overrides[get_uow] = lambda: uow
    app.dependency_overrides[get_admin_service] = lambda: admins
    app.dependency_overrides[get_features] = lambda: features
    app.dependency_overrides[get_module_configs] = lambda: configs
    app.dependency_overrides[get_app_settings] = get_settings

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
        harness = Bed(app, client)
        harness.uow = uow
        harness.admins = admins
        harness.features = features
        harness.configs = configs
        harness.chat = chat
        yield harness


# --- triggers -------------------------------------------------------------------
TRIGGER = {"pattern": "привет", "response": "И тебе привет!"}


async def test_creating_a_trigger_returns_it_with_an_id(bed: Bed) -> None:
    response = await bed.client.post(bed.url("/triggers"), json=TRIGGER, headers=bed.auth())
    assert response.status_code == 201
    body = response.json()
    assert body["id"] >= 1
    assert body["pattern"] == "привет"
    assert body["match"] == "contains"
    assert body["hits"] == 0


async def test_a_free_chat_cannot_create_a_trigger(bed: Bed) -> None:
    """The plan gate, not the quota gate: Free has no triggers feature at all."""
    bed.features.plan_value = Plan.FREE
    response = await bed.client.post(bed.url("/triggers"), json=TRIGGER, headers=bed.auth())
    assert response.status_code == 402
    assert response.json()["code"] == "feature-locked"


async def test_the_trigger_quota_is_enforced_at_the_plan_limit(bed: Bed) -> None:
    for index in range(PLAN_LIMITS[Plan.PRO].triggers):
        bed.uow.triggers.seed(pattern=f"p{index}", response="r", match=TriggerMatch.CONTAINS)

    response = await bed.client.post(bed.url("/triggers"), json=TRIGGER, headers=bed.auth())
    assert response.status_code == 409
    problem = response.json()
    assert problem["code"] == "limit-exceeded"
    assert problem["context"]["limit"] == PLAN_LIMITS[Plan.PRO].triggers


async def test_a_regex_that_does_not_compile_is_rejected(bed: Bed) -> None:
    payload = {**TRIGGER, "pattern": "(unclosed", "match": "regex"}
    response = await bed.client.post(bed.url("/triggers"), json=payload, headers=bed.auth())
    assert response.status_code == 422
    assert response.json()["code"] == "invalid-pattern"


async def test_a_catastrophic_regex_is_rejected(bed: Bed) -> None:
    """`(a+)+` compiles fine and then eats a CPU on the right input."""
    payload = {**TRIGGER, "pattern": "(a+)+$", "match": "regex"}
    response = await bed.client.post(bed.url("/triggers"), json=payload, headers=bed.auth())
    assert response.status_code == 422
    assert response.json()["code"] == "invalid-pattern"


async def test_switching_match_mode_revalidates_the_stored_pattern(bed: Bed) -> None:
    """A literal that is a broken regex must not become one via PATCH.

    `(unclosed` is a perfectly good "contains" pattern. Flipping `match` to
    regex without re-checking it would leave a rule that throws on every message.
    """
    row = bed.uow.triggers.seed(pattern="(unclosed", response="r", match=TriggerMatch.CONTAINS)
    response = await bed.client.patch(
        bed.url(f"/triggers/{row.id}"), json={"match": "regex"}, headers=bed.auth()
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid-pattern"


async def test_updating_a_trigger_persists_and_returns_the_new_row(bed: Bed) -> None:
    row = bed.uow.triggers.seed(pattern="old", response="r", match=TriggerMatch.CONTAINS)
    response = await bed.client.patch(
        bed.url(f"/triggers/{row.id}"),
        json={"pattern": "new", "enabled": False},
        headers=bed.auth(),
    )
    assert response.status_code == 200
    assert response.json()["pattern"] == "new"
    assert response.json()["enabled"] is False
    assert bed.uow.triggers.rows[row.id].pattern == "new"


async def test_deleting_a_trigger_works_on_a_downgraded_chat(bed: Bed) -> None:
    """Clearing rules must never be plan-gated — that would trap the data."""
    row = bed.uow.triggers.seed(pattern="p", response="r", match=TriggerMatch.CONTAINS)
    bed.features.plan_value = Plan.FREE

    response = await bed.client.delete(bed.url(f"/triggers/{row.id}"), headers=bed.auth())
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert row.id not in bed.uow.triggers.rows


async def test_an_unknown_trigger_id_is_a_404(bed: Bed) -> None:
    response = await bed.client.get(bed.url("/triggers/999"), headers=bed.auth())
    assert response.status_code == 404
    assert response.json()["code"] == "not-found"


async def test_a_trigger_from_another_chat_is_invisible(bed: Bed) -> None:
    """Row ids are global; scoping them by chat is what stops a cross-read."""
    row = bed.uow.triggers.seed(pattern="p", response="r", match=TriggerMatch.CONTAINS)
    row.chat_id = CHAT_ID + 1

    response = await bed.client.get(bed.url(f"/triggers/{row.id}"), headers=bed.auth())
    assert response.status_code == 404


async def test_trigger_routes_need_a_session(bed: Bed) -> None:
    response = await bed.client.get(bed.url("/triggers"))
    assert response.status_code == 401


# --- scheduled posts ------------------------------------------------------------
POST = {"content": "Доброе утро!", "schedule_kind": "daily", "schedule_value": "09:00"}


class Queue:
    """Records what the router asked of the ARQ queue, in order."""

    def __init__(self) -> None:
        self.armed: list[tuple[int, datetime]] = []
        self.disarmed: list[int] = []

    async def arm(self, post_id: int, when: datetime | None) -> None:
        assert when is not None
        self.armed.append((post_id, when))

    async def disarm(self, post_id: int) -> bool:
        self.disarmed.append(post_id)
        return True


@pytest.fixture
def queue(monkeypatch: pytest.MonkeyPatch) -> Queue:
    """Replace the two Redis-backed calls the posts router makes.

    Patched at the router's own namespace: `arm`/`disarm` are imported by value
    there, so patching `core.autopost` would leave the bound names untouched.
    """
    recorder = Queue()
    monkeypatch.setattr("api.routers.posts.arm", recorder.arm)
    monkeypatch.setattr("api.routers.posts.disarm", recorder.disarm)
    return recorder


async def test_creating_a_post_stores_the_next_run_and_arms_the_queue(
    bed: Bed, queue: Queue
) -> None:
    response = await bed.client.post(bed.url("/posts"), json=POST, headers=bed.auth())
    assert response.status_code == 201
    body = response.json()

    post_id = body["id"]
    stored = bed.uow.posts.rows[post_id]
    assert stored.next_run_at is not None
    assert body["next_run_at"] is not None
    # The row and the job must name the same moment — this is the whole contract.
    assert queue.armed == [(post_id, stored.next_run_at)]


async def test_a_free_chat_cannot_schedule_a_post(bed: Bed, queue: Queue) -> None:
    bed.features.plan_value = Plan.FREE
    response = await bed.client.post(bed.url("/posts"), json=POST, headers=bed.auth())
    assert response.status_code == 402
    assert not queue.armed


async def test_the_post_quota_is_enforced_at_the_plan_limit(bed: Bed, queue: Queue) -> None:
    for index in range(PLAN_LIMITS[Plan.PRO].scheduled_posts):
        bed.uow.posts.seed(
            content=f"c{index}", schedule_kind=ScheduleKind.DAILY, schedule_value="09:00"
        )

    response = await bed.client.post(bed.url("/posts"), json=POST, headers=bed.auth())
    assert response.status_code == 409
    assert response.json()["context"]["resource"] == "scheduled_posts"


async def test_an_unparseable_schedule_is_rejected(bed: Bed, queue: Queue) -> None:
    payload = {**POST, "schedule_value": "25:99"}
    response = await bed.client.post(bed.url("/posts"), json=payload, headers=bed.auth())
    assert response.status_code == 422
    assert response.json()["code"] == "invalid-schedule"
    assert not bed.uow.posts.rows


async def test_a_cron_schedule_survives_the_round_trip(bed: Bed, queue: Queue) -> None:
    payload = {**POST, "schedule_kind": "cron", "schedule_value": "0 */6 * * *"}
    response = await bed.client.post(bed.url("/posts"), json=payload, headers=bed.auth())
    assert response.status_code == 201
    assert response.json()["schedule_kind"] == "cron"
    assert response.json()["next_run_at"] is not None


async def test_a_one_shot_in_the_past_is_stored_without_a_job(bed: Bed, queue: Queue) -> None:
    """`once` in the past has no next fire; the row is kept, the queue stays clear.

    Rejecting it would lose a post an admin scheduled seconds before the clock
    passed it; arming it would queue a job for a moment that will never come.
    """
    payload = {**POST, "schedule_kind": "once", "schedule_value": "2020-01-01 09:00"}
    response = await bed.client.post(bed.url("/posts"), json=payload, headers=bed.auth())

    assert response.status_code == 201
    assert response.json()["next_run_at"] is None
    assert not queue.armed
    assert queue.disarmed == [response.json()["id"]]


async def test_disabling_a_post_clears_its_job_and_its_next_run(bed: Bed, queue: Queue) -> None:
    row = bed.uow.posts.seed(
        content="c", schedule_kind=ScheduleKind.DAILY, schedule_value="09:00", next_run_at=NOW
    )
    response = await bed.client.patch(
        bed.url(f"/posts/{row.id}"), json={"enabled": False}, headers=bed.auth()
    )

    assert response.status_code == 200
    assert response.json()["next_run_at"] is None
    assert bed.uow.posts.rows[row.id].next_run_at is None
    assert queue.disarmed == [row.id]


async def test_re_enabling_a_post_arms_it_again(bed: Bed, queue: Queue) -> None:
    row = bed.uow.posts.seed(
        content="c",
        schedule_kind=ScheduleKind.DAILY,
        schedule_value="09:00",
        enabled=False,
    )
    response = await bed.client.patch(
        bed.url(f"/posts/{row.id}"), json={"enabled": True}, headers=bed.auth()
    )

    assert response.status_code == 200
    assert queue.armed == [(row.id, bed.uow.posts.rows[row.id].next_run_at)]


async def test_changing_only_the_schedule_kind_revalidates_the_value(
    bed: Bed, queue: Queue
) -> None:
    """`09:00` is a fine daily time and a nonsense cron line."""
    row = bed.uow.posts.seed(content="c", schedule_kind=ScheduleKind.DAILY, schedule_value="09:00")
    response = await bed.client.patch(
        bed.url(f"/posts/{row.id}"), json={"schedule_kind": "cron"}, headers=bed.auth()
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid-schedule"


async def test_deleting_a_post_disarms_it_on_a_downgraded_chat(bed: Bed, queue: Queue) -> None:
    row = bed.uow.posts.seed(content="c", schedule_kind=ScheduleKind.DAILY, schedule_value="09:00")
    bed.features.plan_value = Plan.FREE

    response = await bed.client.delete(bed.url(f"/posts/{row.id}"), headers=bed.auth())
    assert response.status_code == 200
    assert row.id not in bed.uow.posts.rows
    assert queue.disarmed == [row.id]


async def test_an_unknown_post_id_is_a_404(bed: Bed, queue: Queue) -> None:
    response = await bed.client.delete(bed.url("/posts/999"), headers=bed.auth())
    assert response.status_code == 404
    assert not queue.disarmed


async def test_the_module_timezone_overrides_the_chat_timezone(bed: Bed, queue: Queue) -> None:
    """A schedule means a wall-clock time, so the zone decides the stored instant.

    Same resolution order the worker uses; if the two disagreed, the post would
    be stored for one hour and sent at another.
    """
    bed.chat.timezone = "UTC"
    bed.configs.stored["autopost"] = {"timezone": "Asia/Tokyo"}

    response = await bed.client.post(bed.url("/posts"), json=POST, headers=bed.auth())
    assert response.status_code == 201
    fires_at = datetime.fromisoformat(response.json()["next_run_at"])
    # 09:00 in Tokyo is 00:00 UTC — not the 09:00 UTC the chat zone would give.
    assert fires_at.astimezone(UTC).hour == 0


# --- statistics -----------------------------------------------------------------
@pytest.fixture
def rollups(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Capture the window `stats.overview` was actually asked for.

    The aggregation itself is covered where it lives; what the router owns is
    the clamp and the profile join, and both are visible from here.
    """
    windows: list[int] = []

    async def overview(chat_id: int, *, days: int = 7, end: Any = None) -> StatsOverview:
        windows.append(days)
        return StatsOverview(
            period_days=days,
            total_messages=120,
            total_active_users=8,
            total_joins=3,
            total_leaves=1,
            net_growth=2,
            series=[],
            top_users=[
                TopUser(tg_user_id=USER_ID, messages=90),
                TopUser(tg_user_id=USER_ID + 1, messages=30),
            ],
        )

    monkeypatch.setattr("api.routers.stats.stats.overview", overview)
    return windows


async def test_stats_are_served_for_the_requested_window(bed: Bed, rollups: list[int]) -> None:
    response = await bed.client.get(bed.url("/stats?days=30"), headers=bed.auth())
    assert response.status_code == 200
    assert rollups == [30]
    assert response.json()["total_messages"] == 120


async def test_the_window_is_clamped_to_the_plans_retention(bed: Bed, rollups: list[int]) -> None:
    """Serving 365 days on a 90-day plan would look like missing data, not a limit."""
    response = await bed.client.get(bed.url("/stats?days=365"), headers=bed.auth())
    assert response.status_code == 200
    assert rollups == [PLAN_LIMITS[Plan.PRO].stats_retention_days]
    assert response.json()["period_days"] == PLAN_LIMITS[Plan.PRO].stats_retention_days


async def test_a_free_chat_gets_no_statistics(bed: Bed, rollups: list[int]) -> None:
    bed.features.plan_value = Plan.FREE
    response = await bed.client.get(bed.url("/stats"), headers=bed.auth())
    assert response.status_code == 402
    assert not rollups


async def test_top_users_are_named_from_the_profile_cache(bed: Bed, rollups: list[int]) -> None:
    bed.uow.users.seed(tg_user_id=USER_ID, username="ada", first_name="Ada")

    response = await bed.client.get(bed.url("/stats"), headers=bed.auth())
    top = response.json()["top_users"]

    assert top[0]["username"] == "ada"
    assert top[0]["display_name"] == "Ada"
    # An id the cache has never seen stays anonymous rather than failing the row.
    assert top[1]["username"] is None


async def test_an_absurd_window_is_a_422_not_a_clamp(bed: Bed, rollups: list[int]) -> None:
    """The plan clamp is a product rule; `days=99999` is a malformed request."""
    response = await bed.client.get(bed.url("/stats?days=99999"), headers=bed.auth())
    assert response.status_code == 422
    assert not rollups


# --- reputation -----------------------------------------------------------------
async def test_the_leaderboard_is_ordered_and_named(bed: Bed) -> None:
    bed.uow.reputation.seed(USER_ID, points=10, level=2)
    bed.uow.reputation.seed(USER_ID + 1, points=90, level=5)
    bed.uow.users.seed(tg_user_id=USER_ID + 1, username="grace", first_name="Grace")

    response = await bed.client.get(bed.url("/reputation"), headers=bed.auth())
    assert response.status_code == 200
    board = response.json()

    assert [row["points"] for row in board] == [90, 10]
    assert board[0]["username"] == "grace"
    assert board[1]["username"] is None


async def test_the_leaderboard_can_be_ordered_by_the_weekly_board(bed: Bed) -> None:
    response = await bed.client.get(
        bed.url("/reputation?order_by=weekly_points"), headers=bed.auth()
    )
    assert response.status_code == 200


async def test_an_unknown_order_field_is_rejected(bed: Bed) -> None:
    """A typo answering with the wrong board is worse than a 422."""
    response = await bed.client.get(bed.url("/reputation?order_by=karma"), headers=bed.auth())
    assert response.status_code == 422


async def test_a_free_chat_has_no_reputation(bed: Bed) -> None:
    bed.features.plan_value = Plan.FREE
    response = await bed.client.get(bed.url("/reputation"), headers=bed.auth())
    assert response.status_code == 402


async def test_a_member_without_a_row_is_a_404(bed: Bed) -> None:
    response = await bed.client.get(bed.url(f"/reputation/{USER_ID}"), headers=bed.auth())
    assert response.status_code == 404
    assert response.json()["code"] == "not-found"


async def test_adjusting_reputation_applies_a_delta(bed: Bed) -> None:
    bed.uow.reputation.seed(USER_ID, points=10, level=2)

    response = await bed.client.post(
        bed.url(f"/reputation/{USER_ID}/adjust"), json={"delta": -4}, headers=bed.auth()
    )
    assert response.status_code == 200
    assert response.json()["points"] == 6
    assert bed.uow.reputation.rows[USER_ID].points == 6
    assert bed.uow.commits == 1


async def test_adjusting_a_member_who_has_no_row_yet_creates_one(bed: Bed) -> None:
    """A correction must not require the member to have earned a point first."""
    response = await bed.client.post(
        bed.url(f"/reputation/{USER_ID}/adjust"), json={"delta": 5}, headers=bed.auth()
    )
    assert response.status_code == 200
    assert response.json()["points"] == 5


async def test_an_absurd_delta_is_rejected(bed: Bed) -> None:
    response = await bed.client.post(
        bed.url(f"/reputation/{USER_ID}/adjust"), json={"delta": 10**9}, headers=bed.auth()
    )
    assert response.status_code == 422
