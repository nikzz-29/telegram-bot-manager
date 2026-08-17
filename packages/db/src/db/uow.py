"""Unit of Work — one transaction, all repositories.

Services take a `UnitOfWork` and never touch `AsyncSession` directly, so the
transaction boundary lives in exactly one place.
"""

from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.base import get_session_factory
from db.repositories import (
    AdminRepository,
    AiCheckLogRepository,
    CaptchaRepository,
    ChatRepository,
    GlobalBanRepository,
    ModerationLogRepository,
    ModuleConfigRepository,
    PaymentRepository,
    PlanOverrideRepository,
    PlatformRepository,
    PlatformSettingRepository,
    PunishmentRepository,
    ReputationRepository,
    ScheduledPostRepository,
    StatsRepository,
    TgUserRepository,
    TriggerRepository,
    WarnRepository,
    WebsiteLoginTokenRepository,
)


class UnitOfWork:
    """Async context manager wrapping a single session/transaction."""

    session: AsyncSession

    admins: AdminRepository
    ai_logs: AiCheckLogRepository
    captcha: CaptchaRepository
    chats: ChatRepository
    global_bans: GlobalBanRepository
    module_configs: ModuleConfigRepository
    moderation_logs: ModerationLogRepository
    payments: PaymentRepository
    plan_overrides: PlanOverrideRepository
    platform: PlatformRepository
    platform_settings: PlatformSettingRepository
    posts: ScheduledPostRepository
    punishments: PunishmentRepository
    reputation: ReputationRepository
    stats: StatsRepository
    triggers: TriggerRepository
    users: TgUserRepository
    warns: WarnRepository
    website_tokens: WebsiteLoginTokenRepository

    def __init__(self, session_factory: async_sessionmaker[AsyncSession] | None = None) -> None:
        self._session_factory = session_factory
        self._owns_session = True

    @classmethod
    def from_session(cls, session: AsyncSession) -> Self:
        """Wrap an externally managed session (the FastAPI request session).

        The caller keeps ownership: `commit()` still works, but `__aexit__` will
        not close the session.
        """
        uow = cls()
        uow.session = session
        uow._owns_session = False
        uow._bind_repositories(session)
        return uow

    def _bind_repositories(self, session: AsyncSession) -> None:
        self.admins = AdminRepository(session)
        self.ai_logs = AiCheckLogRepository(session)
        self.captcha = CaptchaRepository(session)
        self.chats = ChatRepository(session)
        self.global_bans = GlobalBanRepository(session)
        self.module_configs = ModuleConfigRepository(session)
        self.moderation_logs = ModerationLogRepository(session)
        self.payments = PaymentRepository(session)
        self.plan_overrides = PlanOverrideRepository(session)
        self.platform = PlatformRepository(session)
        self.platform_settings = PlatformSettingRepository(session)
        self.posts = ScheduledPostRepository(session)
        self.punishments = PunishmentRepository(session)
        self.reputation = ReputationRepository(session)
        self.stats = StatsRepository(session)
        self.triggers = TriggerRepository(session)
        self.users = TgUserRepository(session)
        self.warns = WarnRepository(session)
        self.website_tokens = WebsiteLoginTokenRepository(session)

    async def __aenter__(self) -> Self:
        if not hasattr(self, "session"):
            factory = self._session_factory or get_session_factory()
            self.session = factory()
            self._owns_session = True
            self._bind_repositories(self.session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            await self.rollback()
        elif self._owns_session:
            await self.commit()
        if self._owns_session:
            await self.session.close()

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

    async def flush(self) -> None:
        await self.session.flush()


__all__ = ["UnitOfWork"]
