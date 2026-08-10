"""Subscriptions: what a plan costs, how it is bought, and when it lapses.

Spec §5.8. Two rails — Telegram Stars (native, `XTR`) and CryptoBot (fiat-priced
crypto) — converge on one idempotent `apply_payment`, which is the *only* place
in the codebase that moves a chat onto a paid plan.

DECISION: the invoice payload is the whole transaction. Telegram echoes it back
in `successful_payment` and Crypto Pay echoes it in the webhook, so the chat,
plan and term never have to be looked up from a side table that could drift from
the invoice the payer actually saw. It carries a short HMAC so a malformed or
foreign payload is rejected by parsing rather than by trusting an upstream check.

DECISION: buying a *different* plan restarts the term instead of extending it.
Carrying a Pro remainder into a Business subscription would either shortchange
the buyer or hand out free Business days depending on which direction they moved;
starting fresh is the rule that is the same in both directions and is what the
invoice says.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import hmac
from typing import TYPE_CHECKING, Any, Final

from aiogram.types import LabeledPrice, SuccessfulPayment

from core import cache
from core.cryptobot import cryptobot
from core.features import effective_plan
from db.models import Chat, Payment
from db.uow import UnitOfWork
from i18n.runtime import Translator
from shared.config import get_settings
from shared.enums import PaymentProvider, PaymentStatus, Plan
from shared.errors import PaymentError, ProviderUnavailableError
from shared.logging import get_logger
from shared.plans import (
    GRACE_PERIOD_DAYS,
    PLAN_PRICES,
    PURCHASABLE_PLANS,
    SUBSCRIPTION_PERIOD_DAYS,
    features_for_plan,
)
from shared.schemas.api import InvoiceResponse, PlanCatalog, PlanOption
from shared.time_utils import utc_now

if TYPE_CHECKING:  # pragma: no cover
    from aiogram import Bot

logger = get_logger(__name__)

# Telegram caps `invoice_payload` at 128 bytes; everything below fits in ~50.
PAYLOAD_PREFIX: Final = "sub"
PAYLOAD_SEPARATOR: Final = ":"
SIGNATURE_LENGTH: Final = 10
MAX_MONTHS: Final = 12

STARS_CURRENCY: Final = "XTR"
CRYPTO_CURRENCY: Final = "USD"

# Stars invoice links are generated without a provider token and stay valid until
# used; the payload's plan is re-read at settlement, so a stale link is safe.
INVOICE_TITLE_KEY: Final = "billing-invoice-title"
INVOICE_DESCRIPTION_KEY: Final = "billing-invoice-description"


@dataclass(frozen=True, slots=True)
class InvoicePayload:
    """The chat, plan and term an invoice was opened for."""

    chat_id: int
    plan: Plan
    months: int

    def unsigned(self) -> str:
        return PAYLOAD_SEPARATOR.join(
            (PAYLOAD_PREFIX, str(self.chat_id), self.plan.value, str(self.months))
        )

    def encode(self) -> str:
        body = self.unsigned()
        return f"{body}{PAYLOAD_SEPARATOR}{_sign(body)}"

    @classmethod
    def decode(cls, raw: str) -> InvoicePayload:
        """Parse a payload we issued, or raise.

        Every failure mode is the same failure: this string is not one of ours.
        """
        parts = raw.split(PAYLOAD_SEPARATOR)
        if len(parts) != 5 or parts[0] != PAYLOAD_PREFIX:
            raise PaymentError("Unrecognized invoice payload.")
        _, chat_raw, plan_raw, months_raw, signature = parts
        body = PAYLOAD_SEPARATOR.join(parts[:4])
        if not hmac.compare_digest(signature, _sign(body)):
            logger.warning("billing.payload_signature_mismatch", payload=raw)
            raise PaymentError("Invoice payload failed verification.")
        try:
            chat_id = int(chat_raw)
            months = int(months_raw)
            plan = Plan(plan_raw)
        except ValueError as error:
            raise PaymentError("Malformed invoice payload.") from error
        if months < 1 or months > MAX_MONTHS:
            raise PaymentError("Invoice payload has an impossible term.")
        return cls(chat_id=chat_id, plan=plan, months=months)


def _sign(body: str) -> str:
    """Short HMAC over the payload body, keyed by the app secret."""
    digest = hmac.new(get_settings().jwt_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return digest[:SIGNATURE_LENGTH]


def price_for(plan: Plan, months: int) -> tuple[int, Decimal]:
    """(stars, usd) for a term. Both rails quote from this one table.

    `PaymentError` rather than a validation error: asking to buy Free is not a
    malformed request, it is a purchase that cannot be made, and 402 is what the
    panel already knows how to render as a billing message.
    """
    if plan not in PLAN_PRICES:
        raise PaymentError(f"Plan {plan.value} is not for sale.")
    if months < 1 or months > MAX_MONTHS:
        raise PaymentError("Subscription term must be between 1 and 12 months.")
    price = PLAN_PRICES[plan]
    return price.stars * months, Decimal(price.usd) * months


def term_end(start: datetime, months: int) -> datetime:
    """A month is a fixed 30 days here — the same length the invoice quoted."""
    return start + timedelta(days=SUBSCRIPTION_PERIOD_DAYS * months)


class BillingService:
    """Quotes plans, opens invoices, and settles the ones that get paid."""

    def __init__(self, bot: Bot | None = None) -> None:
        self._bot = bot

    def bind(self, bot: Bot) -> None:
        """Attach the Bot that mints Stars invoice links."""
        self._bot = bot

    # --- quoting --------------------------------------------------------------
    def catalog(self, chat: Chat, *, now: datetime | None = None) -> PlanCatalog:
        """What this chat is on, and what it could move to.

        `current_plan` is the *effective* plan, not the stored one: a chat inside
        its grace window should see the plan it is still getting, or the panel
        would offer to "upgrade" to what it already has.
        """
        return PlanCatalog(
            current_plan=effective_plan(chat, now=now),
            expires_at=chat.plan_expires_at,
            options=[
                PlanOption(
                    plan=plan,
                    stars=PLAN_PRICES[plan].stars,
                    usd=PLAN_PRICES[plan].usd,
                    features=sorted(feature.value for feature in features_for_plan(plan)),
                )
                for plan in PURCHASABLE_PLANS
            ],
        )

    # --- invoices -------------------------------------------------------------
    async def create_invoice(
        self,
        chat: Chat,
        *,
        plan: Plan,
        months: int,
        provider: PaymentProvider,
        t: Translator,
    ) -> InvoiceResponse:
        stars, usd = price_for(plan, months)
        payload = InvoicePayload(chat_id=chat.id, plan=plan, months=months).encode()
        title = t(INVOICE_TITLE_KEY, plan=plan.value.upper())
        description = t(INVOICE_DESCRIPTION_KEY, plan=plan.value.upper(), months=months)

        if provider is PaymentProvider.STARS:
            url = await self._stars_link(
                title=title, description=description, payload=payload, stars=stars
            )
            amount = str(stars)
            currency = STARS_CURRENCY
        else:
            invoice = await cryptobot.create_invoice(
                amount=usd, payload=payload, description=description
            )
            url = invoice.pay_url
            amount = str(invoice.amount)
            currency = invoice.currency

        logger.info(
            "billing.invoice_opened",
            chat_id=chat.id,
            plan=plan.value,
            months=months,
            provider=provider.value,
        )
        return InvoiceResponse(
            provider=provider,
            invoice_url=url,
            invoice_payload=payload,
            amount=amount,
            currency=currency,
        )

    async def _stars_link(self, *, title: str, description: str, payload: str, stars: int) -> str:
        """A `t.me` invoice link the Mini App opens and the bot can button up.

        DECISION: `createInvoiceLink`, not `sendInvoice`. The panel needs a URL it
        can hand to `WebApp.openInvoice`, and the same URL works as an inline
        button in a DM — one code path instead of a message-shaped one and a
        panel-shaped one. Stars invoices carry no provider token by definition.
        """
        if self._bot is None:
            raise ProviderUnavailableError("Stars payments need a bound Bot.")
        link: str = await self._bot.create_invoice_link(
            title=title,
            description=description,
            payload=payload,
            currency=STARS_CURRENCY,
            prices=[LabeledPrice(label=title, amount=stars)],
        )
        return link

    # --- settlement -----------------------------------------------------------
    async def apply_payment(
        self,
        *,
        payload: str,
        provider: PaymentProvider,
        provider_payment_id: str,
        amount: Decimal,
        currency: str,
        payer_tg_id: int | None,
        raw: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> Payment:
        """Record a settled payment and move the chat onto its plan.

        Idempotent by construction: the payment row is inserted against the
        `(provider, provider_payment_id)` unique index, and a replayed webhook —
        which Crypto Pay will send — comes back as `created is False` and returns
        the original row without touching the subscription a second time.
        """
        parsed = InvoicePayload.decode(payload)
        moment = now or utc_now()

        async with UnitOfWork() as uow:
            chat = await uow.chats.get_by_id(parsed.chat_id)
            if chat is None:
                raise PaymentError("The chat this payment was for no longer exists.")

            start = self._term_start(chat, plan=parsed.plan, now=moment)
            end = term_end(start, parsed.months)

            payment, created = await uow.payments.record(
                chat_id=chat.id,
                provider=provider,
                provider_payment_id=provider_payment_id,
                payload=payload,
                amount=amount,
                currency=currency,
                plan=parsed.plan,
                months=parsed.months,
                payer_tg_id=payer_tg_id,
                status=PaymentStatus.PAID,
                period_start=start,
                period_end=end,
                raw=raw,
            )
            if not created:
                logger.info(
                    "billing.payment_replayed",
                    chat_id=chat.id,
                    provider=provider.value,
                    provider_payment_id=provider_payment_id,
                )
                return payment

            # Grace is cleared, not merely ignored: a chat that paid while lapsed
            # must not be picked up by the downgrade sweep on its old window.
            await uow.chats.set_plan(chat.id, parsed.plan, expires_at=end, grace_until=None)
            await uow.commit()

        await cache.invalidate_chat_plan(parsed.chat_id)
        logger.info(
            "billing.subscription_extended",
            chat_id=parsed.chat_id,
            plan=parsed.plan.value,
            months=parsed.months,
            until=end.isoformat(),
            provider=provider.value,
        )
        return payment

    # --- provider adapters ----------------------------------------------------
    async def settle_stars_payment(
        self, payment: SuccessfulPayment, *, payer_tg_id: int | None
    ) -> Payment:
        """Settle a Telegram Stars purchase from the update that announced it."""
        return await self.apply_payment(
            payload=payment.invoice_payload,
            provider=PaymentProvider.STARS,
            provider_payment_id=payment.telegram_payment_charge_id,
            amount=Decimal(payment.total_amount),
            currency=payment.currency,
            payer_tg_id=payer_tg_id,
            raw=payment.model_dump(mode="json", exclude_none=True),
        )

    async def settle_crypto_invoice(self, invoice: dict[str, Any]) -> Payment:
        """Settle a paid Crypto Pay invoice from the webhook body.

        The quoted fiat amount is recorded, not the asset the payer happened to
        send: revenue reporting compares plans, and a mix of TON and USDT rows
        would not add up to anything.
        """
        payload = str(invoice.get("payload") or "")
        invoice_id = str(invoice.get("invoice_id") or "")
        if not payload or not invoice_id:
            raise PaymentError("Crypto Pay invoice arrived without a payload.")
        amount = Decimal(str(invoice.get("amount") or "0"))
        currency = str(invoice.get("fiat") or invoice.get("asset") or CRYPTO_CURRENCY)
        return await self.apply_payment(
            payload=payload,
            provider=PaymentProvider.CRYPTOBOT,
            provider_payment_id=invoice_id,
            amount=amount,
            currency=currency,
            # Crypto Pay never names the payer, and an invoice may be settled by
            # someone other than the admin who opened it.
            payer_tg_id=None,
            raw=invoice,
        )

    def _term_start(self, chat: Chat, *, plan: Plan, now: datetime) -> datetime:
        """Where the new term begins.

        Renewing the same plan early stacks onto the unused remainder, so nobody
        is punished for paying before the last day. Changing plan — or coming back
        after the window closed — starts from now.
        """
        if chat.plan != plan or chat.plan_expires_at is None:
            return now
        return max(now, chat.plan_expires_at)

    # --- lapse ----------------------------------------------------------------
    async def begin_grace(self, chat: Chat, *, now: datetime | None = None) -> datetime:
        """Open the grace window for a chat whose paid term just ended."""
        moment = now or utc_now()
        until = (chat.plan_expires_at or moment) + timedelta(days=GRACE_PERIOD_DAYS)
        async with UnitOfWork() as uow:
            await uow.chats.update_fields(chat.id, grace_until=until)
            await uow.commit()
        await cache.invalidate_chat_plan(chat.id)
        logger.info("billing.grace_started", chat_id=chat.id, until=until.isoformat())
        return until

    async def downgrade(self, chat_id: int) -> None:
        """Drop a chat to Free. Module configs are deliberately left intact.

        Spec §5.8: re-subscribing must restore what the chat had. The paid modules
        stop running because `features` says so, not because their settings were
        deleted.
        """
        async with UnitOfWork() as uow:
            await uow.chats.set_plan(chat_id, Plan.FREE, expires_at=None, grace_until=None)
            await uow.commit()
        await cache.invalidate_chat_plan(chat_id)
        logger.info("billing.downgraded", chat_id=chat_id, plan=Plan.FREE.value)


billing = BillingService()


__all__ = [
    "CRYPTO_CURRENCY",
    "MAX_MONTHS",
    "STARS_CURRENCY",
    "BillingService",
    "InvoicePayload",
    "billing",
    "price_for",
    "term_end",
]
