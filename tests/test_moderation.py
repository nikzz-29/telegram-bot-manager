"""The moderation service, minus the database.

`ModerationService` takes its `UnitOfWork` factory as a constructor argument for
exactly this: a fake that records what each action wrote. The one invariant these
tests defend is that *every logged moderation action is one — and only one —
`MODERATION` stat event*, so the private report (which counts `moderation_logs`)
and the group `/stats` chart (which counts the rolled-up events) can never
disagree about how much moderation happened.

No ARQ, no Redis: the actions exercised here (a ban with no duration, a kick, a
warn below the limit, a log line) schedule nothing, so `core.jobs` is never
reached and does not need to be faked.
"""

from __future__ import annotations

from typing import Any

from core.moderation import ModerationService, ModerationTarget
from shared.enums import PunishmentType, StatEventType, WarnPunishment
from shared.schemas.module_configs import ModerationConfig

TARGET = ModerationTarget(
    chat_id=10, tg_chat_id=-1001, tg_user_id=555, moderator_tg_id=999, display_name="Bob"
)


def cfg(**overrides: Any) -> ModerationConfig:
    base: dict[str, Any] = {"warn_limit": 3, "warn_lifetime_days": 30}
    base.update(overrides)
    return ModerationConfig.model_validate(base)


class FakeWarns:
    """`count_active` and `revoke_last` are scripted; the rest just record."""

    def __init__(self, *, count: int = 1, revoke_last: int | None = 1) -> None:
        self._count = count
        self._revoke_last = revoke_last
        self.added: list[dict[str, Any]] = []

    async def add(self, **kwargs: Any) -> None:
        self.added.append(kwargs)

    async def count_active(self, chat_id: int, tg_user_id: int) -> int:
        return self._count

    async def revoke_last(
        self, chat_id: int, tg_user_id: int, *, moderator_tg_id: int
    ) -> int | None:
        return self._revoke_last

    async def revoke_all(self, chat_id: int, tg_user_id: int, *, moderator_tg_id: int) -> int:
        return 0


class FakePunishments:
    """No live punishment to supersede, so nothing to cancel or schedule."""

    def __init__(self) -> None:
        self.added: list[dict[str, Any]] = []

    async def get_active(self, chat_id: int, tg_user_id: int, ptype: PunishmentType) -> None:
        return None

    async def deactivate_for_user(
        self, chat_id: int, tg_user_id: int, ptype: PunishmentType
    ) -> int:
        return 0

    async def add(self, **kwargs: Any) -> None:
        self.added.append(kwargs)


class FakeModerationLogs:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def add(self, **kwargs: Any) -> None:
        self.rows.append(kwargs)


class FakeStats:
    def __init__(self) -> None:
        self.events: list[tuple[int, StatEventType, int | None]] = []

    async def add_event(
        self,
        *,
        chat_id: int,
        event_type: StatEventType,
        tg_user_id: int | None = None,
        payload: Any = None,
    ) -> None:
        self.events.append((chat_id, event_type, tg_user_id))


class FakeUow:
    """One shared instance stands in for every transaction an action opens."""

    def __init__(self, *, warn_count: int = 1, revoke_last: int | None = 1) -> None:
        self.warns = FakeWarns(count=warn_count, revoke_last=revoke_last)
        self.punishments = FakePunishments()
        self.moderation_logs = FakeModerationLogs()
        self.stats = FakeStats()
        self.commits = 0

    async def __aenter__(self) -> FakeUow:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def commit(self) -> None:
        self.commits += 1


def _service(uow: FakeUow) -> ModerationService:
    # A factory returning the one shared fake, so escalating actions accumulate
    # their rows on the same instance the test inspects.
    return ModerationService(uow_factory=lambda: uow)  # type: ignore[arg-type]


def _moderation_events(uow: FakeUow) -> list[tuple[int, StatEventType, int | None]]:
    return [event for event in uow.stats.events if event[1] is StatEventType.MODERATION]


async def test_a_warn_below_the_limit_logs_once_and_counts_once() -> None:
    uow = FakeUow(warn_count=1)
    outcome = await _service(uow).warn(TARGET, reason="spam", config=cfg(warn_limit=3))

    assert not outcome.limit_reached
    assert [row["action"] for row in uow.moderation_logs.rows] == ["warn"]
    assert _moderation_events(uow) == [(10, StatEventType.MODERATION, 555)]


async def test_a_ban_logs_once_and_counts_once() -> None:
    uow = FakeUow()
    await _service(uow).ban(TARGET, reason="scam")

    assert [row["action"] for row in uow.moderation_logs.rows] == ["ban"]
    assert _moderation_events(uow) == [(10, StatEventType.MODERATION, 555)]


async def test_a_kick_logs_once_and_counts_once() -> None:
    uow = FakeUow()
    await _service(uow).kick(TARGET, reason="bye")

    assert [row["action"] for row in uow.moderation_logs.rows] == ["kick"]
    assert _moderation_events(uow) == [(10, StatEventType.MODERATION, 555)]


async def test_an_automatic_action_logs_once_and_counts_once() -> None:
    """A filter's auto-delete is moderation too — it must land on the chart like a
    human action, which is the whole point of routing both through `_log`."""
    uow = FakeUow()
    await _service(uow).log_action(TARGET, action="auto_delete", reason="stopword")

    assert [row["action"] for row in uow.moderation_logs.rows] == ["auto_delete"]
    assert _moderation_events(uow) == [(10, StatEventType.MODERATION, 555)]


async def test_an_unwarn_with_nothing_to_revoke_logs_nothing() -> None:
    """No warn was revoked, so there is no action to record — and nothing to
    inflate the moderation count with."""
    uow = FakeUow(revoke_last=None)
    await _service(uow).unwarn(TARGET)

    assert uow.moderation_logs.rows == []
    assert _moderation_events(uow) == []


async def test_a_warn_that_trips_the_limit_records_both_actions() -> None:
    """Hitting the limit is one warn plus one punishment — two logged actions, so
    two `MODERATION` events. A BAN punishment schedules nothing, keeping this a
    pure test of the 1:1 invariant through an escalation."""
    uow = FakeUow(warn_count=3)
    outcome = await _service(uow).warn(
        TARGET, reason="last straw", config=cfg(warn_limit=3, warn_punishment=WarnPunishment.BAN)
    )

    assert outcome.limit_reached
    assert [row["action"] for row in uow.moderation_logs.rows] == ["warn", "ban"]
    assert _moderation_events(uow) == [
        (10, StatEventType.MODERATION, 555),
        (10, StatEventType.MODERATION, 555),
    ]
