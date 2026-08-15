"""Telegram Stars handler copy and settlement delivery."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from bot.commands import payments
from core.billing import billing
from i18n.runtime import translator
from shared.enums import Plan


def _pre_checkout_handler() -> Any:
    return payments.build_router().pre_checkout_query.handlers[0].callback


def _successful_payment_handler() -> Any:
    return payments.build_router().message.handlers[0].callback


@pytest.mark.asyncio
async def test_invalid_invoice_is_declined_in_the_payers_language() -> None:
    answers: list[dict[str, Any]] = []

    async def answer(**kwargs: Any) -> None:
        answers.append(kwargs)

    query = SimpleNamespace(
        invoice_payload="invalid",
        from_user=SimpleNamespace(id=42, language_code="ru"),
        answer=answer,
    )

    await _pre_checkout_handler()(query)

    assert answers == [{"ok": False, "error_message": translator("ru")("billing-invoice-expired")}]


@pytest.mark.asyncio
async def test_success_receipt_uses_the_localized_plan_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[tuple[int, str]] = []
    recorded = SimpleNamespace(
        plan=Plan.WHITE_LABEL,
        period_end=datetime(2026, 9, 14, tzinfo=UTC),
    )

    async def settle(_: Any, *, payer_tg_id: int | None) -> Any:
        assert payer_tg_id == 42
        return recorded

    async def send(chat_id: int, text: str, **_: Any) -> None:
        sent.append((chat_id, text))

    monkeypatch.setattr(billing, "settle_stars_payment", settle)
    monkeypatch.setattr(payments, "send", send)
    message = SimpleNamespace(
        successful_payment=SimpleNamespace(telegram_payment_charge_id="charge-1"),
        from_user=SimpleNamespace(id=42, language_code="ru"),
        chat=SimpleNamespace(id=77),
    )

    await _successful_payment_handler()(message)

    assert sent == [
        (
            77,
            translator("ru")(
                "billing-payment-received",
                plan=translator("ru")("plan-white_label"),
                until="2026-09-14",
            ),
        )
    ]
    assert "WHITE_LABEL" not in sent[0][1]
