"""Telegram Stars checkout: the two updates that complete a purchase.

Spec §5.8. Telegram runs the payment UI; the bot only gets a say twice — once to
approve the checkout, and once to be told it succeeded.

DECISION: `pre_checkout_query` is answered `ok=True` for any payload that parses
and names a chat that exists, and rejected otherwise. Telegram gives this answer
ten seconds and charges the user the moment it is positive, so it must not do
database-heavy validation or reach for the network. Everything that decides *what
the payment buys* is already inside the signed payload, and re-deciding it here
would risk approving one thing and granting another.

DECISION: the handler is not filtered to private chats. An invoice link opened
from the Mini App settles in whatever chat Telegram delivers it to, and dropping
a `successful_payment` because it arrived somewhere unexpected would take money
without granting the plan.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message, PreCheckoutQuery

from bot.replies import send
from core.billing import InvoicePayload, billing
from core.sender import SendPriority
from db.uow import UnitOfWork
from i18n.runtime import normalize_locale, translator
from shared.errors import PaymentError
from shared.logging import get_logger

logger = get_logger(__name__)

# Shown in Telegram's own error sheet when the bot declines a checkout, so it is
# deliberately vague: the payer can act on "try again from the panel", and a
# stranger probing invoice payloads learns nothing from it.
DECLINE_MESSAGE = "This invoice is no longer valid. Please reopen it from the panel."


def _locale(user_language: str | None) -> str:
    """Receipts are addressed to the payer, so they follow the payer's locale."""
    return normalize_locale(user_language)


def build_router() -> Router:
    """Handlers for the Stars checkout, in any chat type."""
    router = Router(name="payments")

    @router.pre_checkout_query()
    async def approve_checkout(query: PreCheckoutQuery) -> None:
        try:
            payload = InvoicePayload.decode(query.invoice_payload)
        except PaymentError as error:
            logger.warning(
                "payments.pre_checkout_rejected",
                error=str(error),
                user_id=query.from_user.id,
            )
            await query.answer(ok=False, error_message=DECLINE_MESSAGE)
            return

        async with UnitOfWork() as uow:
            chat = await uow.chats.get_by_id(payload.chat_id)
        if chat is None:
            logger.warning("payments.pre_checkout_orphan", chat_id=payload.chat_id)
            await query.answer(ok=False, error_message=DECLINE_MESSAGE)
            return

        logger.info(
            "payments.pre_checkout_approved",
            chat_id=payload.chat_id,
            plan=payload.plan.value,
            months=payload.months,
            user_id=query.from_user.id,
        )
        await query.answer(ok=True)

    @router.message(F.successful_payment)
    async def confirm_payment(message: Message) -> None:
        payment = message.successful_payment
        if payment is None:  # pragma: no cover — the filter guarantees it
            return
        payer = message.from_user
        locale = _locale(payer.language_code if payer else None)

        try:
            recorded = await billing.settle_stars_payment(
                payment, payer_tg_id=payer.id if payer else None
            )
        except PaymentError as error:
            # The charge already happened, so this is a refund case for support,
            # not something the payer can fix. It is logged at error level for
            # exactly that reason.
            logger.error(
                "payments.settlement_failed",
                error=str(error),
                charge_id=payment.telegram_payment_charge_id,
                user_id=payer.id if payer else None,
            )
            await send(
                message.chat.id,
                translator(locale)("error-payment"),
                priority=SendPriority.REPLY,
                silent=False,
            )
            return

        until = recorded.period_end
        await send(
            message.chat.id,
            translator(locale)(
                "billing-payment-received",
                plan=recorded.plan.value.upper(),
                until=until.strftime("%Y-%m-%d") if until else "",
            ),
            priority=SendPriority.REPLY,
            silent=False,
        )

    return router


__all__ = ["DECLINE_MESSAGE", "build_router"]
