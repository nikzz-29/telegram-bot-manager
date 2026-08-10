"""Stage 5 billing: payloads, settlement, the lifecycle sweeps and the webhook.

Money is the one part of the platform where a bug is not recoverable by trying
again, so this suite is organized around the three ways it could go wrong:

* the invoice payload — the only thing carrying *what was bought* from the moment
  the invoice opens to the moment it settles, across two providers that both echo
  it back verbatim;
* idempotency — Crypto Pay redelivers, and a chat must not gain two months from
  one payment;
* the lapse path — expiry, grace and downgrade, which decide when a paying chat
  stops being one.

DECISION: `apply_payment` opens its own `UnitOfWork`, so it is patched at
`core.billing.UnitOfWork` rather than reached through a dependency override. That
is the seam the production code actually uses; overriding anything else would
test a code path that does not exist.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
import hmac
import json
from typing import Any

import httpx
import pytest

from api.app import create_app
from api.routers import billing as billing_router
from core import billing as billing_module
from core.billing import InvoicePayload, billing, price_for, term_end
from core.cryptobot import PAID_STATUS, SIGNATURE_HEADER, CryptoBotClient
from core.features import effective_plan, in_grace_period
from db.models import Chat, Payment
from shared.enums import ChatType, PaymentProvider, PaymentStatus, Plan
from shared.errors import PaymentError
from shared.plans import (
    GRACE_PERIOD_DAYS,
    PLAN_PRICES,
    PURCHASABLE_PLANS,
    SUBSCRIPTION_PERIOD_DAYS,
)

CHAT_ID = 1
TG_CHAT_ID = -1001999888777
USER_ID = 7_654_321
NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def make_chat(**overrides: Any) -> Chat:
    chat = Chat(
        id=CHAT_ID,
        tg_chat_id=TG_CHAT_ID,
        title="Test Chat",
        type=ChatType.SUPERGROUP,
        plan=Plan.FREE,
        plan_expires_at=None,
        grace_until=None,
        owner_tg_id=USER_ID,
        language="ru",
        timezone="UTC",
        is_active=True,
        settings={},
    )
    for key, value in overrides.items():
        setattr(chat, key, value)
    return chat


# --- fakes ----------------------------------------------------------------------
class FakeChatRepo:
    def __init__(self, chats: dict[int, Chat]) -> None:
        self.chats = chats

    async def get_by_id(self, chat_id: int) -> Chat | None:
        return self.chats.get(chat_id)

    async def set_plan(
        self,
        chat_id: int,
        plan: Plan,
        *,
        expires_at: datetime | None,
        grace_until: datetime | None = None,
    ) -> None:
        chat = self.chats[chat_id]
        chat.plan = plan
        chat.plan_expires_at = expires_at
        chat.grace_until = grace_until

    async def update_fields(self, chat_id: int, **fields: Any) -> None:
        for key, value in fields.items():
            setattr(self.chats[chat_id], key, value)


class FakePaymentRepo:
    """The unique index on (provider, provider_payment_id), in a dict."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], Payment] = {}
        self._next_id = 1

    async def record(self, **fields: Any) -> tuple[Payment, bool]:
        key = (fields["provider"].value, fields["provider_payment_id"])
        existing = self.rows.get(key)
        if existing is not None:
            return existing, False
        row = Payment(id=self._next_id, **fields)
        self.rows[key] = row
        self._next_id += 1
        return row, True

    async def list_for_chat(self, chat_id: int, *, limit: int = 50) -> list[Payment]:
        rows = [row for row in self.rows.values() if row.chat_id == chat_id]
        return rows[:limit]


class FakeUow:
    """Async-context UoW handing back the two repositories billing touches."""

    def __init__(self, chats: dict[int, Chat], payments: FakePaymentRepo) -> None:
        self.chats = FakeChatRepo(chats)
        self.payments = payments
        self.commits = 0

    async def __aenter__(self) -> FakeUow:
        return self

    async def __aexit__(self, *exc_info: Any) -> bool:
        return False

    async def commit(self) -> None:
        self.commits += 1


@pytest.fixture
def ledger(monkeypatch: pytest.MonkeyPatch) -> FakeUow:
    """Wire `core.billing` to an in-memory chat table and payment ledger.

    Patched at `core.billing.UnitOfWork` — the name the service actually calls —
    and `cache.invalidate_chat_plan` is stubbed because a plan change must not
    need a live Redis to be tested.
    """
    payments = FakePaymentRepo()
    uow = FakeUow({CHAT_ID: make_chat()}, payments)
    monkeypatch.setattr(billing_module, "UnitOfWork", lambda: uow)

    invalidated: list[int] = []

    async def invalidate(chat_id: int) -> None:
        invalidated.append(chat_id)

    monkeypatch.setattr(billing_module.cache, "invalidate_chat_plan", invalidate)
    uow.invalidated = invalidated  # type: ignore[attr-defined]
    return uow


def payload_for(plan: Plan = Plan.PRO, months: int = 1) -> str:
    return InvoicePayload(chat_id=CHAT_ID, plan=plan, months=months).encode()


async def settle(
    uow: FakeUow,
    *,
    payment_id: str = "charge-1",
    plan: Plan = Plan.PRO,
    months: int = 1,
    now: datetime = NOW,
) -> Payment:
    return await billing.apply_payment(
        payload=payload_for(plan, months),
        provider=PaymentProvider.STARS,
        provider_payment_id=payment_id,
        amount=Decimal(PLAN_PRICES[plan].stars * months),
        currency="XTR",
        payer_tg_id=USER_ID,
        now=now,
    )


# --- the payload ----------------------------------------------------------------
def test_a_payload_round_trips_through_the_wire_format() -> None:
    """What the invoice said is what settlement reads back — across a string."""
    original = InvoicePayload(chat_id=CHAT_ID, plan=Plan.BUSINESS, months=6)
    assert InvoicePayload.decode(original.encode()) == original


def test_a_payload_fits_telegrams_128_byte_ceiling() -> None:
    """Telegram silently rejects a longer `invoice_payload`; check the worst case."""
    widest = InvoicePayload(chat_id=2**31, plan=Plan.WHITE_LABEL, months=12).encode()
    assert len(widest.encode("utf-8")) <= 128


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "sub:1:pro:1",  # unsigned
        "sub:1:pro:1:0000000000",  # wrong signature
        "gift:1:pro:1:0000000000",  # not ours
    ],
)
def test_a_payload_we_did_not_issue_is_refused(raw: str) -> None:
    with pytest.raises(PaymentError):
        InvoicePayload.decode(raw)


def test_editing_a_payload_invalidates_its_signature() -> None:
    """The whole point: an upgrade cannot be had by editing the plan in place."""
    tampered = payload_for(Plan.PRO).replace(":pro:", ":white_label:")
    with pytest.raises(PaymentError):
        InvoicePayload.decode(tampered)


def test_a_term_is_priced_by_multiplying_the_monthly_rate() -> None:
    stars, usd = price_for(Plan.PRO, 3)
    assert stars == PLAN_PRICES[Plan.PRO].stars * 3
    assert usd == Decimal(PLAN_PRICES[Plan.PRO].usd) * 3


def test_the_free_plan_is_not_for_sale() -> None:
    with pytest.raises(PaymentError):
        price_for(Plan.FREE, 1)


# --- settlement -----------------------------------------------------------------
async def test_a_first_payment_moves_the_chat_onto_its_plan(ledger: FakeUow) -> None:
    payment = await settle(ledger)
    chat = ledger.chats.chats[CHAT_ID]

    assert chat.plan is Plan.PRO
    assert chat.plan_expires_at == term_end(NOW, 1)
    assert payment.period_end == chat.plan_expires_at
    # The cached plan is what every gate reads; a stale entry would sell nothing.
    assert ledger.invalidated == [CHAT_ID]  # type: ignore[attr-defined]


async def test_the_same_payment_delivered_twice_buys_one_month(ledger: FakeUow) -> None:
    """Crypto Pay redelivers until it gets a 2xx — the second must be inert."""
    first = await settle(ledger, payment_id="charge-1")
    expiry = ledger.chats.chats[CHAT_ID].plan_expires_at

    second = await settle(ledger, payment_id="charge-1", now=NOW + timedelta(minutes=5))

    assert second.id == first.id
    assert ledger.chats.chats[CHAT_ID].plan_expires_at == expiry
    assert len(ledger.payments.rows) == 1


async def test_renewing_early_stacks_onto_the_unused_remainder(ledger: FakeUow) -> None:
    """Nobody is punished for paying before the last day."""
    await settle(ledger, payment_id="charge-1")
    first_expiry = ledger.chats.chats[CHAT_ID].plan_expires_at
    assert first_expiry is not None

    await settle(ledger, payment_id="charge-2", now=NOW + timedelta(days=10))

    assert ledger.chats.chats[CHAT_ID].plan_expires_at == term_end(first_expiry, 1)


async def test_changing_plan_restarts_the_term(ledger: FakeUow) -> None:
    """A Pro remainder is not carried into Business — the invoice said 30 days."""
    await settle(ledger, payment_id="charge-1", plan=Plan.PRO)
    later = NOW + timedelta(days=10)

    await settle(ledger, payment_id="charge-2", plan=Plan.BUSINESS, now=later)

    chat = ledger.chats.chats[CHAT_ID]
    assert chat.plan is Plan.BUSINESS
    assert chat.plan_expires_at == term_end(later, 1)


async def test_paying_during_grace_clears_the_grace_window(ledger: FakeUow) -> None:
    """Otherwise the downgrade sweep would still be holding a claim on the chat."""
    chat = ledger.chats.chats[CHAT_ID]
    chat.plan = Plan.PRO
    chat.plan_expires_at = NOW - timedelta(days=1)
    chat.grace_until = NOW + timedelta(days=2)

    await settle(ledger)

    assert chat.grace_until is None
    assert not in_grace_period(chat, now=NOW)


async def test_a_payment_for_a_vanished_chat_is_refused(ledger: FakeUow) -> None:
    ledger.chats.chats.clear()
    with pytest.raises(PaymentError):
        await settle(ledger)


async def test_a_multi_month_term_is_recorded_as_bought(ledger: FakeUow) -> None:
    payment = await settle(ledger, months=6)
    assert payment.months == 6
    assert payment.status is PaymentStatus.PAID
    expected = NOW + timedelta(days=SUBSCRIPTION_PERIOD_DAYS * 6)
    assert ledger.chats.chats[CHAT_ID].plan_expires_at == expected


# --- the lapse path -------------------------------------------------------------
async def test_grace_opens_from_the_expiry_not_from_the_sweep(ledger: FakeUow) -> None:
    """A sweep that ran late must not hand out extra paid days."""
    chat = ledger.chats.chats[CHAT_ID]
    chat.plan = Plan.PRO
    chat.plan_expires_at = NOW - timedelta(days=1)
    late = NOW + timedelta(hours=6)

    until = await billing.begin_grace(chat, now=late)

    assert until == chat.plan_expires_at + timedelta(days=GRACE_PERIOD_DAYS)
    assert chat.grace_until == until


async def test_a_chat_in_grace_still_gets_its_paid_features(ledger: FakeUow) -> None:
    """The whole point of the window — and it must not depend on cron having run."""
    chat = ledger.chats.chats[CHAT_ID]
    chat.plan = Plan.PRO
    chat.plan_expires_at = NOW - timedelta(hours=1)
    await billing.begin_grace(chat, now=NOW)

    assert effective_plan(chat, now=NOW) is Plan.PRO
    assert in_grace_period(chat, now=NOW)


async def test_a_lapsed_chat_falls_back_to_free_when_grace_runs_out() -> None:
    """`effective_plan` decides this from the row alone, before any job runs."""
    chat = make_chat(
        plan=Plan.PRO,
        plan_expires_at=NOW - timedelta(days=10),
        grace_until=NOW - timedelta(days=7),
    )
    assert effective_plan(chat, now=NOW) is Plan.FREE
    assert not in_grace_period(chat, now=NOW)


async def test_downgrade_clears_the_window_and_the_cached_plan(ledger: FakeUow) -> None:
    chat = ledger.chats.chats[CHAT_ID]
    chat.plan = Plan.BUSINESS
    chat.plan_expires_at = NOW - timedelta(days=5)
    chat.grace_until = NOW - timedelta(days=2)

    await billing.downgrade(CHAT_ID)

    assert chat.plan is Plan.FREE
    assert chat.plan_expires_at is None
    assert chat.grace_until is None
    assert ledger.invalidated == [CHAT_ID]  # type: ignore[attr-defined]


# --- the catalog ----------------------------------------------------------------
def test_the_catalog_quotes_every_purchasable_plan() -> None:
    catalog = billing.catalog(make_chat(), now=NOW)
    assert [option.plan for option in catalog.options] == list(PURCHASABLE_PLANS)
    assert Plan.FREE not in {option.plan for option in catalog.options}


def test_the_catalog_reports_the_effective_plan_during_grace() -> None:
    """A chat in grace is on Pro, so the panel must not offer to "upgrade" to it."""
    chat = make_chat(
        plan=Plan.PRO,
        plan_expires_at=NOW - timedelta(days=1),
        grace_until=NOW + timedelta(days=2),
    )
    assert billing.catalog(chat, now=NOW).current_plan is Plan.PRO


# --- the Crypto Pay webhook -----------------------------------------------------
CRYPTO_TOKEN = "12345:test-crypto-pay-token"


def crypto_signature(body: bytes, *, token: str = CRYPTO_TOKEN) -> str:
    """Sign a body the way Crypto Pay does: HMAC-SHA256 keyed by sha256(token).

    Re-derived here rather than borrowed from the client, so the test would still
    catch us verifying against the wrong key material.
    """
    key = hashlib.sha256(token.encode()).digest()
    return hmac.new(key, body, hashlib.sha256).hexdigest()


def invoice_update(
    *,
    invoice_id: str = "555001",
    payload: str | None = None,
    status: str = PAID_STATUS,
) -> bytes:
    """A webhook body, serialized once so the signature covers these exact bytes."""
    update = {
        "update_id": 1,
        "update_type": "invoice_paid",
        "payload": {
            "invoice_id": invoice_id,
            "status": status,
            "amount": "4.99",
            "fiat": "USD",
            "payload": payload if payload is not None else payload_for(Plan.PRO, 1),
        },
    }
    return json.dumps(update).encode()


@pytest.fixture
async def webhook(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[httpx.AsyncClient]:
    """The real app, with the Crypto Pay client pointed at a test token.

    The lifespan is not run: it would open a Bot session and a Redis connection,
    and the webhook route depends on neither.
    """
    monkeypatch.setattr(billing_router, "cryptobot", CryptoBotClient(CRYPTO_TOKEN))
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
        yield client


async def post_update(client: httpx.AsyncClient, body: bytes, *, signature: str | None = None):
    return await client.post(
        billing_router.CRYPTOBOT_WEBHOOK_PATH,
        content=body,
        headers={
            SIGNATURE_HEADER: crypto_signature(body) if signature is None else signature,
            "Content-Type": "application/json",
        },
    )


async def test_a_signed_paid_invoice_settles(webhook: httpx.AsyncClient, ledger: FakeUow) -> None:
    response = await post_update(webhook, invoice_update())

    assert response.status_code == 200
    chat = ledger.chats.chats[CHAT_ID]
    assert chat.plan is Plan.PRO
    assert len(ledger.payments.rows) == 1


async def test_a_redelivered_invoice_does_not_extend_the_term(
    webhook: httpx.AsyncClient, ledger: FakeUow
) -> None:
    """Crypto Pay retries on any non-2xx, and duplicates happen even on 200."""
    body = invoice_update()
    await post_update(webhook, body)
    expiry = ledger.chats.chats[CHAT_ID].plan_expires_at

    second = await post_update(webhook, body)

    assert second.status_code == 200
    assert ledger.chats.chats[CHAT_ID].plan_expires_at == expiry
    assert len(ledger.payments.rows) == 1


async def test_an_unsigned_update_settles_nothing(
    webhook: httpx.AsyncClient, ledger: FakeUow
) -> None:
    """The only case answered with a non-2xx: forgery is worth retrying against."""
    response = await post_update(webhook, invoice_update(), signature="deadbeef")

    assert response.status_code == 401
    assert ledger.chats.chats[CHAT_ID].plan is Plan.FREE
    assert not ledger.payments.rows


async def test_a_signature_over_different_bytes_is_rejected(
    webhook: httpx.AsyncClient, ledger: FakeUow
) -> None:
    """Re-serializing the parsed body before verifying would let this through."""
    signed = invoice_update(invoice_id="555001")
    delivered = invoice_update(invoice_id="555002")

    response = await post_update(webhook, delivered, signature=crypto_signature(signed))

    assert response.status_code == 401
    assert not ledger.payments.rows
