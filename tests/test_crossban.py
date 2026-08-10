"""The cross-ban network: what propagates, what does not, and what stays local.

Spec §5.6. This suite is organized around the one question the network gets wrong
most easily — *whose* judgement is being applied. Three chats agreeing that
someone is a scammer is evidence; one moderator losing an argument is not, and
one chat forgiving someone is not evidence of innocence either.

DECISION: `CrossbanService` opens its own `UnitOfWork`, so it is patched at
`core.crossban.UnitOfWork` — the name the service actually calls. `cache` and
`jobs` are stubbed for the same reason the billing suite stubs them: a promotion
must be testable without a live Redis, and the enqueue is the seam that proves
propagation was handed off rather than run inline.
"""

from __future__ import annotations

from typing import Any

import pytest

from core import cache, jobs
from core import crossban as crossban_module
from core.crossban import crossban, is_network_reason
from core.jobs import JobName
from shared.schemas.module_configs import CrossbanConfig

USER_ID = 555
THRESHOLD = 3


class FakeGlobalBanRepo:
    """Distinct-chat reports in a set, plus the active blacklist flag."""

    def __init__(self) -> None:
        self.reporters: set[int] = set()
        self.promoted: list[dict[str, Any]] = []
        self.active = False
        self.revokes = 0

    async def report(
        self, *, chat_id: int, tg_user_id: int, reason: str, reported_by: int | None
    ) -> int:
        # A set, because the real unique constraint means a chat banning the same
        # user twice cannot inflate the counter.
        self.reporters.add(chat_id)
        return len(self.reporters)

    async def promote(self, *, tg_user_id: int, reason: str, banned_by: int | None) -> None:
        self.promoted.append({"tg_user_id": tg_user_id, "reason": reason, "banned_by": banned_by})
        self.active = True

    async def revoke(self, tg_user_id: int) -> bool:
        self.revokes += 1
        was_active, self.active = self.active, False
        return was_active

    async def get(self, tg_user_id: int) -> Any:
        if not self.reporters and not self.promoted:
            return None
        return type("Row", (), {"is_active": self.active, "chat_count": len(self.reporters)})()


class FakeUow:
    def __init__(self, repo: FakeGlobalBanRepo) -> None:
        self.global_bans = repo
        self.commits = 0

    async def __aenter__(self) -> FakeUow:
        return self

    async def __aexit__(self, *exc_info: Any) -> bool:
        return False

    async def commit(self) -> None:
        self.commits += 1


@pytest.fixture
def network(monkeypatch: pytest.MonkeyPatch) -> tuple[FakeGlobalBanRepo, list[tuple[Any, ...]]]:
    """Wire the service to an in-memory blacklist and a recording job queue."""
    repo = FakeGlobalBanRepo()
    uow = FakeUow(repo)
    monkeypatch.setattr(crossban_module, "UnitOfWork", lambda: uow)

    enqueued: list[tuple[Any, ...]] = []

    async def enqueue(name: Any, *args: Any, **kwargs: Any) -> None:
        enqueued.append((name, *args))

    async def invalidate_user(tg_user_id: int) -> None:
        return None

    monkeypatch.setattr(jobs, "enqueue", enqueue)
    monkeypatch.setattr(cache, "invalidate_user", invalidate_user)
    return repo, enqueued


# --- the allow-list: which local bans are the network's business ---------------


@pytest.mark.parametrize(
    "reason",
    ["scam", "SCAM: fake support", "ai:scam", "phishing link", "мошенник", "фишинг", "fraud ring"],
)
def test_scam_shaped_reasons_feed_the_network(reason: str) -> None:
    assert is_network_reason(reason)


@pytest.mark.parametrize(
    "reason",
    ["flood", "rude to the mods", "off-topic", "ban", "спам не по теме", ""],
)
def test_everything_else_stays_a_local_decision(reason: str) -> None:
    """A moderator ending an argument must not become a platform-wide ban."""
    assert not is_network_reason(reason)


# --- reporting and promotion --------------------------------------------------


async def test_promotion_waits_for_the_threshold_then_fires_once(
    network: tuple[FakeGlobalBanRepo, list[tuple[Any, ...]]],
) -> None:
    """Two chats is an opinion; the third is what the network acts on."""
    repo, enqueued = network
    config = CrossbanConfig.model_validate({"enabled": True, "contribute_bans": True})

    for chat_id in range(1, THRESHOLD):
        outcome = await crossban.report(
            chat_id=chat_id, tg_user_id=USER_ID, reason="scam", config=config
        )
        assert outcome.recorded
        assert not outcome.promoted
        assert not outcome.threshold_reached
    assert not repo.active
    assert enqueued == [], "nothing to fan out before the threshold"

    final = await crossban.report(
        chat_id=THRESHOLD, tg_user_id=USER_ID, reason="scam", config=config
    )
    assert final.promoted
    assert final.chat_count == THRESHOLD
    assert repo.active
    assert len(repo.promoted) == 1


async def test_promotion_hands_the_fan_out_to_the_worker(
    network: tuple[FakeGlobalBanRepo, list[tuple[Any, ...]]],
) -> None:
    """Spec §5.6: the moderator's `/ban` returns now, the fan-out happens later."""
    _, enqueued = network
    await crossban.promote(tg_user_id=USER_ID, reason="scam: fake giveaway", banned_by=1)
    assert enqueued == [(JobName.PROPAGATE_GLOBAL_BAN, USER_ID, "scam: fake giveaway")]


async def test_a_chat_reporting_twice_cannot_inflate_the_count(
    network: tuple[FakeGlobalBanRepo, list[tuple[Any, ...]]],
) -> None:
    """One chat is one vote however many times it presses the button."""
    repo, _ = network
    config = CrossbanConfig.model_validate({"enabled": True, "contribute_bans": True})
    for _ in range(THRESHOLD + 2):
        outcome = await crossban.report(
            chat_id=42, tg_user_id=USER_ID, reason="scam", config=config
        )
        assert outcome.chat_count == 1
    assert not repo.active


async def test_a_chat_that_opted_out_contributes_nothing(
    network: tuple[FakeGlobalBanRepo, list[tuple[Any, ...]]],
) -> None:
    repo, _ = network
    config = CrossbanConfig.model_validate({"enabled": True, "contribute_bans": False})
    outcome = await crossban.report(chat_id=1, tg_user_id=USER_ID, reason="scam", config=config)
    assert not outcome.recorded
    assert repo.reporters == set()


async def test_a_non_network_reason_is_not_recorded_at_all(
    network: tuple[FakeGlobalBanRepo, list[tuple[Any, ...]]],
) -> None:
    """The allow-list runs before the write, not after."""
    repo, _ = network
    config = CrossbanConfig.model_validate({"enabled": True, "contribute_bans": True})
    outcome = await crossban.report(
        chat_id=1, tg_user_id=USER_ID, reason="argued with a mod", config=config
    )
    assert not outcome.recorded
    assert repo.reporters == set()


async def test_an_operator_gban_promotes_on_the_first_report(
    network: tuple[FakeGlobalBanRepo, list[tuple[Any, ...]]],
) -> None:
    """`force=True` is the operator path: one chat, opted out, vague reason, done.

    This is the `/gban` and panel case — the operator pressing the button *is* the
    decision, so neither the threshold nor the chat's contribution setting applies.
    """
    repo, enqueued = network
    config = CrossbanConfig.model_validate({"enabled": True, "contribute_bans": False})
    outcome = await crossban.report(
        chat_id=1,
        tg_user_id=USER_ID,
        reason="operator judgement",
        reported_by=99,
        config=config,
        force=True,
    )
    assert outcome.promoted
    assert outcome.chat_count == 1
    assert repo.active
    assert repo.promoted == [
        {"tg_user_id": USER_ID, "reason": "operator judgement", "banned_by": 99}
    ]
    assert len(enqueued) == 1


# --- appeals: the asymmetry -----------------------------------------------------


async def test_revoking_lifts_the_ban_but_never_propagates(
    network: tuple[FakeGlobalBanRepo, list[tuple[Any, ...]]],
) -> None:
    """Spec §5.6: un-banning is manual, and it does not unban anyone's chat.

    A chat that banned this user itself still means it, so there is no fan-out to
    match the one promotion enqueued.
    """
    repo, enqueued = network
    await crossban.promote(tg_user_id=USER_ID, reason="scam", banned_by=1)
    assert len(enqueued) == 1

    assert await crossban.revoke(USER_ID) is True
    assert not repo.active
    assert len(enqueued) == 1, "revocation must not enqueue an unban fan-out"


async def test_revoking_someone_who_was_never_listed_reports_the_miss(
    network: tuple[FakeGlobalBanRepo, list[tuple[Any, ...]]],
) -> None:
    """The panel needs the difference between "lifted" and "nothing to lift"."""
    _, _ = network
    assert await crossban.revoke(USER_ID) is False


async def test_status_answers_the_join_gate(
    network: tuple[FakeGlobalBanRepo, list[tuple[Any, ...]]],
) -> None:
    listed, chats = await crossban.status(USER_ID)
    assert (listed, chats) == (False, 0)

    config = CrossbanConfig.model_validate({"enabled": True, "contribute_bans": True})
    await crossban.report(chat_id=1, tg_user_id=USER_ID, reason="scam", config=config)
    listed, chats = await crossban.status(USER_ID)
    assert (listed, chats) == (False, 1), "reported is not yet blacklisted"

    await crossban.promote(tg_user_id=USER_ID, reason="scam", banned_by=None)
    listed, _ = await crossban.status(USER_ID)
    assert listed


# --- what a chat wants done about a blacklisted joiner -------------------------


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"enabled": False}, "off"),
        ({"enabled": True, "alert_only": True}, "alert"),
        ({"enabled": True, "alert_only": False, "autoban_on_join": False}, "alert"),
        ({"enabled": True, "alert_only": False, "autoban_on_join": True}, "ban"),
    ],
)
def test_enforcement_mode_reads_the_config(overrides: dict[str, Any], expected: str) -> None:
    """`alert_only` and `autoban_on_join=False` both mean "tell me, do not act"."""
    assert crossban.enforcement_for(CrossbanConfig.model_validate(overrides)) == expected
