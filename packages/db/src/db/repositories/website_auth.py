"""Single-use website login credentials."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from sqlalchemy import CursorResult, delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import WebsiteLoginToken
from shared.time_utils import utc_now


class WebsiteLoginTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def issue(
        self,
        *,
        tg_user_id: int,
        token_hash: str,
        scope: str,
        expires_at: datetime,
    ) -> None:
        await self._session.execute(
            update(WebsiteLoginToken)
            .where(
                WebsiteLoginToken.tg_user_id == tg_user_id,
                WebsiteLoginToken.scope == scope,
                WebsiteLoginToken.consumed_at.is_(None),
            )
            .values(consumed_at=utc_now())
        )
        self._session.add(
            WebsiteLoginToken(
                tg_user_id=tg_user_id,
                token_hash=token_hash,
                scope=scope,
                expires_at=expires_at,
            )
        )

    async def consume(self, *, token_hash: str, scope: str, now: datetime) -> int | None:
        result = await self._session.execute(
            update(WebsiteLoginToken)
            .where(
                WebsiteLoginToken.token_hash == token_hash,
                WebsiteLoginToken.scope == scope,
                WebsiteLoginToken.consumed_at.is_(None),
                WebsiteLoginToken.expires_at > now,
            )
            .values(consumed_at=now)
            .returning(WebsiteLoginToken.tg_user_id)
        )
        return result.scalar_one_or_none()

    async def purge_expired(self, *, before: datetime) -> int:
        result = cast(
            CursorResult[None],
            await self._session.execute(
                delete(WebsiteLoginToken).where(WebsiteLoginToken.expires_at <= before)
            ),
        )
        return int(result.rowcount or 0)


__all__ = ["WebsiteLoginTokenRepository"]
