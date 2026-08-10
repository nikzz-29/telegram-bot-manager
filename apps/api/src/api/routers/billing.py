"""Plans, invoices and payment history — the Billing section of the panel.

Spec §5.8. The panel quotes plans and opens invoices here; the money itself
never touches this process. A Stars purchase is completed inside Telegram and
settles through the bot's `successful_payment` handler, and a crypto purchase
settles through the CryptoBot webhook below. Both land in
`core.billing.apply_payment`, so this router has no settlement logic of its own.

DECISION: the webhook is mounted here rather than in `system.py` and is excluded
from the OpenAPI document. It is the one route with no `Authorization` header —
its caller is Crypto Pay, authenticated by an HMAC over the raw body — and
publishing it in the schema would put an unauthenticated path into the generated
TS client, which no browser should ever call.

DECISION: the webhook answers 200 for anything it has already handled or cannot
act on, and only fails loudly on a bad signature. Crypto Pay retries a non-2xx,
so returning 500 for an unparseable payload would buy an endless redelivery of a
message that will never succeed.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response, status

from api.deps import ChatAccessDep, TranslatorDep, UowDep
from api.errors import problem_responses
from core.billing import billing
from core.cryptobot import PAID_STATUS, SIGNATURE_HEADER, cryptobot
from shared.config import get_settings
from shared.errors import PaymentError
from shared.logging import get_logger
from shared.schemas.api import InvoiceRequest, InvoiceResponse, PaymentEntry, PlanCatalog

logger = get_logger(__name__)

router = APIRouter(
    prefix="/chats/{chat_id}",
    tags=["billing"],
    responses=problem_responses(
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_402_PAYMENT_REQUIRED,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        status.HTTP_503_SERVICE_UNAVAILABLE,
    ),
)

webhook_router = APIRouter(tags=["billing"], include_in_schema=False)

# Read once at import so the route path is a literal FastAPI can register. The
# setting exists so an operator can move the endpoint off a guessable URL; it is
# a nicety on top of the signature check, never a substitute for it.
CRYPTOBOT_WEBHOOK_PATH = get_settings().cryptobot_webhook_path

# How many payments the history endpoint returns. The panel shows a receipt
# list, not an accounting ledger; a chat with more than this has an export need
# that a paged endpoint would serve better than a bigger page.
PAYMENT_HISTORY_LIMIT = 50


@router.get(
    "/plans",
    response_model=PlanCatalog,
    operation_id="getChatPlans",
    summary="The chat's current plan and what it can move to",
)
async def get_plans(access: ChatAccessDep) -> PlanCatalog:
    """`current_plan` is the effective one, so a chat in grace sees what it has."""
    return billing.catalog(access.chat)


@router.post(
    "/invoice",
    response_model=InvoiceResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createChatInvoice",
    summary="Open a Stars or CryptoBot invoice for a plan",
)
async def create_invoice(
    access: ChatAccessDep,
    payload: InvoiceRequest,
    t: TranslatorDep,
) -> InvoiceResponse:
    """Quote and open an invoice; nothing about the chat changes until it is paid.

    Opening a second invoice while a first is unpaid is allowed on purpose — a
    payer who abandoned a Stars link and came back for crypto would otherwise be
    stuck behind their own dead invoice. Both carry the same signed payload, and
    settlement is idempotent per provider payment id.
    """
    invoice = await billing.create_invoice(
        access.chat,
        plan=payload.plan,
        months=payload.months,
        provider=payload.provider,
        t=t,
    )
    logger.info(
        "api.invoice_created",
        chat_id=access.chat_id,
        plan=payload.plan.value,
        provider=payload.provider.value,
        months=payload.months,
        actor=access.principal.tg_user_id,
    )
    return invoice


@router.get(
    "/payments",
    response_model=list[PaymentEntry],
    operation_id="listChatPayments",
    summary="Recent payments for a chat",
)
async def list_payments(access: ChatAccessDep, uow: UowDep) -> list[PaymentEntry]:
    """Newest first. Pending rows are included: an admin who paid in crypto and
    is waiting for a confirmation should see that the platform knows about it."""
    rows = await uow.payments.list_for_chat(access.chat_id, limit=PAYMENT_HISTORY_LIMIT)
    return [PaymentEntry.model_validate(row) for row in rows]


@webhook_router.post(
    CRYPTOBOT_WEBHOOK_PATH,
    status_code=status.HTTP_200_OK,
    summary="Crypto Pay settlement callback",
)
async def cryptobot_webhook(request: Request) -> Response:
    """Settle a paid Crypto Pay invoice.

    The signature is checked against the raw body before anything is parsed, so a
    forged call never reaches the settlement path. Note the body is read once and
    verified as bytes — re-serializing the parsed JSON would change the byte
    sequence the HMAC was computed over.
    """
    body = await request.body()
    signature = request.headers.get(SIGNATURE_HEADER, "")
    if not cryptobot.verify_signature(body, signature):
        logger.warning("api.cryptobot_bad_signature", bytes=len(body))
        # 401, not 403: the call carries a credential that failed to verify.
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    try:
        update: dict[str, Any] = await request.json()
    except ValueError:
        logger.warning("api.cryptobot_unparseable")
        return Response(status_code=status.HTTP_200_OK)

    invoice = update.get("payload") if isinstance(update.get("payload"), dict) else update
    if not isinstance(invoice, dict) or invoice.get("status") != PAID_STATUS:
        logger.info("api.cryptobot_ignored", update_type=update.get("update_type"))
        return Response(status_code=status.HTTP_200_OK)

    try:
        await billing.settle_crypto_invoice(invoice)
    except PaymentError as error:
        # A payload we did not issue, or one whose chat has since been removed.
        # Retrying will not change that, so the delivery is acknowledged.
        logger.warning("api.cryptobot_rejected", error=str(error))
    return Response(status_code=status.HTTP_200_OK)


__all__ = ["PAYMENT_HISTORY_LIMIT", "router", "webhook_router"]
