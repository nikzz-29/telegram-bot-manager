"""CryptoBot (Crypto Pay API) — the crypto half of the paywall.

Spec §5.8 asks for two payment rails: Telegram Stars and CryptoBot. Stars are
native to the Bot API and need no client; CryptoBot is a third-party HTTP API, so
it is wrapped here and nowhere else. `core.billing` talks to this module, never to
`aiocryptopay`.

DECISION: the client is built lazily and kept for the process. `AioCryptoPay`
owns an aiohttp session, and opening one per invoice would leak a connector on
every purchase. A chat that never buys crypto never opens the session at all.

DECISION: an unconfigured token is not an error at import — the platform is
perfectly usable on Stars alone, and CI has no CryptoBot credentials. It becomes
`ProviderUnavailableError` at the moment someone actually asks for a crypto
invoice, which is where the caller can turn it into a 503 the panel can render.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Final

from shared.config import get_settings
from shared.errors import ProviderUnavailableError
from shared.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from aiocryptopay import AioCryptoPay

logger = get_logger(__name__)

# Crypto Pay quotes in fiat and lets the payer choose the asset at checkout, so
# the platform prices in USD and never touches an exchange rate itself.
FIAT_CURRENCY: Final = "USD"
CURRENCY_TYPE_FIAT: Final = "fiat"

# An abandoned invoice should not sit in the payer's list forever, and a stale
# one must not settle against a plan the chat may have changed since.
INVOICE_TTL_SECONDS: Final = 3600

# The webhook header carrying the HMAC of the raw body.
SIGNATURE_HEADER: Final = "Crypto-Pay-Api-Signature"

PAID_STATUS: Final = "paid"


@dataclass(frozen=True, slots=True)
class CryptoInvoice:
    """The parts of a Crypto Pay invoice the rest of the platform uses."""

    invoice_id: str
    pay_url: str
    amount: Decimal
    currency: str
    payload: str


class CryptoBotClient:
    """Thin, testable seam over `aiocryptopay`."""

    def __init__(self, token: str | None = None) -> None:
        self._token = token
        self._client: AioCryptoPay | None = None

    @property
    def configured(self) -> bool:
        return bool(self._token or get_settings().cryptobot_token)

    def _api(self) -> AioCryptoPay:
        if self._client is not None:
            return self._client
        token = self._token or get_settings().cryptobot_token
        if not token:
            raise ProviderUnavailableError("CryptoBot is not configured.")
        from aiocryptopay import AioCryptoPay

        self._client = AioCryptoPay(token)
        return self._client

    async def create_invoice(
        self,
        *,
        amount: Decimal,
        payload: str,
        description: str,
    ) -> CryptoInvoice:
        """Open a fiat-priced invoice the payer settles in any supported asset."""
        api = self._api()
        try:
            invoice = await api.create_invoice(
                amount=float(amount),
                fiat=FIAT_CURRENCY,
                currency_type=CURRENCY_TYPE_FIAT,
                description=description,
                payload=payload,
                expires_in=INVOICE_TTL_SECONDS,
                allow_anonymous=False,
            )
        except ProviderUnavailableError:
            raise
        except Exception as error:
            logger.warning("cryptobot.invoice_failed", error=str(error))
            raise ProviderUnavailableError("CryptoBot rejected the invoice request.") from error

        pay_url = invoice.mini_app_invoice_url or invoice.bot_invoice_url or ""
        return CryptoInvoice(
            invoice_id=str(invoice.invoice_id),
            pay_url=pay_url,
            amount=Decimal(str(invoice.amount)),
            currency=invoice.fiat or FIAT_CURRENCY,
            payload=invoice.payload or payload,
        )

    def verify_signature(self, body: bytes, signature: str) -> bool:
        """Is this webhook body really from Crypto Pay?

        The SDK derives the HMAC key from our own token, so a forged call cannot
        pass without it. An unconfigured token verifies nothing — refuse rather
        than accept, or a platform with Stars only would have an open endpoint.
        """
        if not signature or not self.configured:
            return False
        try:
            return bool(self._api().check_signature(body.decode("utf-8"), signature))
        except ProviderUnavailableError:
            return False
        except (UnicodeDecodeError, ValueError):
            return False

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None


cryptobot = CryptoBotClient()

__all__ = [
    "CURRENCY_TYPE_FIAT",
    "FIAT_CURRENCY",
    "INVOICE_TTL_SECONDS",
    "PAID_STATUS",
    "SIGNATURE_HEADER",
    "CryptoBotClient",
    "CryptoInvoice",
    "cryptobot",
]
