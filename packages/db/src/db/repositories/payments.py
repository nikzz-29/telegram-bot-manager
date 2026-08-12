"""Payment repository — idempotent on (provider, provider_payment_id)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Payment
from db.repositories._dml import execute_dml
from shared.enums import PaymentProvider, PaymentStatus, Plan


class PaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_provider_id(
        self, provider: PaymentProvider, provider_payment_id: str
    ) -> Payment | None:
        result = await self._session.execute(
            select(Payment).where(
                Payment.provider == provider,
                Payment.provider_payment_id == provider_payment_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, payment_id: int) -> Payment | None:
        return await self._session.get(Payment, payment_id)

    async def get_by_payload(self, payload: str) -> Payment | None:
        result = await self._session.execute(
            select(Payment).where(Payment.payload == payload).limit(1)
        )
        return result.scalar_one_or_none()

    async def record(
        self,
        *,
        chat_id: int,
        provider: PaymentProvider,
        provider_payment_id: str,
        payload: str,
        amount: Decimal,
        currency: str,
        plan: Plan,
        months: int,
        payer_tg_id: int | None,
        status: PaymentStatus,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
        raw: dict[str, Any] | None = None,
    ) -> tuple[Payment, bool]:
        """Insert a payment idempotently.

        Returns (payment, created). `created is False` means this exact provider
        payment was already recorded — a webhook replay — and the caller must
        not extend the subscription again.
        """
        stmt = (
            pg_insert(Payment)
            .values(
                chat_id=chat_id,
                provider=provider,
                provider_payment_id=provider_payment_id,
                payload=payload,
                amount=amount,
                currency=currency,
                plan=plan,
                months=months,
                payer_tg_id=payer_tg_id,
                status=status,
                period_start=period_start,
                period_end=period_end,
                raw=raw or {},
            )
            .on_conflict_do_nothing(constraint="uq_payment_provider_id")
            .returning(Payment)
        )
        result = await self._session.execute(stmt)
        created = result.scalar_one_or_none()
        if created is not None:
            await self._session.flush()
            return created, True

        existing = await self.get_by_provider_id(provider, provider_payment_id)
        if existing is None:  # pragma: no cover — the unique constraint guarantees a row
            raise RuntimeError("payment vanished between insert and lookup")
        return existing, False

    async def list_for_chat(self, chat_id: int, *, limit: int = 50) -> list[Payment]:
        result = await self._session.execute(
            select(Payment)
            .where(Payment.chat_id == chat_id)
            .order_by(Payment.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def revenue_since(self, since: datetime) -> dict[str, Decimal]:
        """Totals per currency for the superadmin dashboard."""
        result = await self._session.execute(
            select(Payment.currency, func.coalesce(func.sum(Payment.amount), 0))
            .where(Payment.status == PaymentStatus.PAID, Payment.created_at >= since)
            .group_by(Payment.currency)
        )
        return {str(currency): Decimal(total) for currency, total in result.all()}

    async def count_paid(self) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(Payment).where(Payment.status == PaymentStatus.PAID)
        )
        return int(result.scalar_one())

    async def mark_refunded(
        self,
        payment_id: int,
        *,
        refunded_at: datetime,
        refunded_by: int | None,
        reason: str = "",
    ) -> bool:
        """Flip a paid payment to refunded. True only for the call that did it.

        The `status == PAID` clause in the WHERE is the idempotency guard: a second
        press of the console's refund button updates nothing and gets False back,
        so the caller can report "already refunded" instead of revoking the plan a
        second time — which for a chat that has since renewed would take away a
        term it paid for.
        """
        return bool(
            await execute_dml(
                self._session,
                update(Payment)
                .where(Payment.id == payment_id, Payment.status == PaymentStatus.PAID)
                .values(
                    status=PaymentStatus.REFUNDED,
                    refunded_at=refunded_at,
                    refunded_by=refunded_by,
                    refund_reason=reason,
                ),
            )
        )
