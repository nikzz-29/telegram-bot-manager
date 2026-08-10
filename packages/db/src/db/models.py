"""SQLAlchemy 2.0 models.

All datetimes are timezone-aware UTC. Enum columns are stored as short strings
rather than native PG enums, so adding a variant needs no migration.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base, TimestampMixin
from db.types import StrEnumType
from shared.enums import (
    AdminRole,
    AiVerdictLabel,
    ChatType,
    PaymentProvider,
    PaymentStatus,
    Plan,
    PunishmentType,
    ScheduleKind,
    StatEventType,
    TriggerMatch,
)

JsonDict = dict[str, Any]


class Chat(TimestampMixin, Base):
    """A connected Telegram chat — the tenant boundary for everything else."""

    __tablename__ = "chats"
    __table_args__ = (
        Index("ix_chats_plan_expires", "plan", "plan_expires_at"),
        Index("ix_chats_settings_gin", "settings", postgresql_using="gin"),
        Index("ix_chats_owner", "owner_tg_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    username: Mapped[str | None] = mapped_column(String(64))
    type: Mapped[ChatType] = mapped_column(
        StrEnumType(ChatType), default=ChatType.SUPERGROUP, nullable=False
    )

    plan: Mapped[Plan] = mapped_column(StrEnumType(Plan), default=Plan.FREE, nullable=False)
    plan_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    grace_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    owner_tg_id: Mapped[int | None] = mapped_column(BigInteger)
    language: Mapped[str] = mapped_column(String(8), default="ru", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    members_count: Mapped[int | None] = mapped_column(Integer)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    lockdown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settings: Mapped[JsonDict] = mapped_column(JSONB, default=dict, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    module_configs: Mapped[list[ChatModuleConfig]] = relationship(
        back_populates="chat", cascade="all, delete-orphan", lazy="selectin"
    )


class ChatModuleConfig(TimestampMixin, Base):
    """Per-chat module toggle plus its validated JSONB config.

    Configs survive a plan downgrade so re-subscribing restores prior settings.
    """

    __tablename__ = "chat_module_configs"
    __table_args__ = (
        UniqueConstraint("chat_id", "module", name="uq_chat_module"),
        Index("ix_module_configs_module_enabled", "module", "enabled"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), nullable=False, index=True
    )
    module: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    config: Mapped[JsonDict] = mapped_column(JSONB, default=dict, nullable=False)

    chat: Mapped[Chat] = relationship(back_populates="module_configs")


class TgUser(TimestampMixin, Base):
    """Cache of Telegram user profiles, used to render names in the Mini App."""

    __tablename__ = "tg_users"

    tg_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(128))
    language_code: Mapped[str | None] = mapped_column(String(8))
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_photo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    @property
    def display_name(self) -> str:
        parts = [self.first_name, self.last_name or ""]
        return " ".join(part for part in parts if part).strip() or f"id{self.tg_user_id}"


class AdminUser(TimestampMixin, Base):
    """Known chat administrators; refreshed from getChatAdministrators."""

    __tablename__ = "admin_users"
    __table_args__ = (UniqueConstraint("chat_id", "tg_user_id", name="uq_admin_chat_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tg_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    role: Mapped[AdminRole] = mapped_column(
        StrEnumType(AdminRole), default=AdminRole.ADMIN, nullable=False
    )


class Warn(TimestampMixin, Base):
    __tablename__ = "warns"
    __table_args__ = (
        Index("ix_warns_chat_user", "chat_id", "tg_user_id"),
        # Partial index: the hot query only ever looks at un-revoked warns.
        Index(
            "ix_warns_active",
            "chat_id",
            "tg_user_id",
            "expires_at",
            postgresql_where="revoked_at IS NULL",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    moderator_tg_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[int | None] = mapped_column(BigInteger)


class Punishment(TimestampMixin, Base):
    """Mute/ban/kick record; `arq_job_id` lets us cancel a pending expiry job."""

    __tablename__ = "punishments"
    __table_args__ = (
        Index("ix_punishments_chat_user", "chat_id", "tg_user_id"),
        Index(
            "ix_punishments_active",
            "chat_id",
            "tg_user_id",
            "expires_at",
            postgresql_where="active = true",
        ),
        Index("ix_punishments_expiry_sweep", "expires_at", postgresql_where="active = true"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    moderator_tg_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    type: Mapped[PunishmentType] = mapped_column(StrEnumType(PunishmentType), nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    arq_job_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    lifted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CaptchaChallenge(TimestampMixin, Base):
    """Pending captcha; a user stays restricted until it is solved or expires."""

    __tablename__ = "captcha_challenges"
    __table_args__ = (
        UniqueConstraint("chat_id", "tg_user_id", name="uq_captcha_chat_user"),
        Index("ix_captcha_expires", "expires_at", postgresql_where="solved_at IS NULL"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    answer: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    arq_job_id: Mapped[str | None] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    solved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TriggerRule(TimestampMixin, Base):
    """Admin-defined phrase → response rule."""

    __tablename__ = "trigger_rules"
    __table_args__ = (Index("ix_triggers_chat_enabled", "chat_id", "enabled"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    pattern: Mapped[str] = mapped_column(String(256), nullable=False)
    match: Mapped[TriggerMatch] = mapped_column(
        StrEnumType(TriggerMatch, 16), default=TriggerMatch.CONTAINS, nullable=False
    )
    response: Mapped[str] = mapped_column(Text, nullable=False)
    media_file_id: Mapped[str | None] = mapped_column(String(256))
    buttons: Mapped[list[JsonDict]] = mapped_column(JSONB, default=list, nullable=False)
    case_sensitive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    delete_trigger: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    hits: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class ScheduledPost(TimestampMixin, Base):
    """Recurring or one-shot post; executed by an ARQ job keyed on `arq_job_id`."""

    __tablename__ = "scheduled_posts"
    __table_args__ = (
        Index("ix_posts_chat_enabled", "chat_id", "enabled"),
        Index("ix_posts_next_run", "next_run_at", postgresql_where="enabled = true"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    media_file_id: Mapped[str | None] = mapped_column(String(256))
    buttons: Mapped[list[JsonDict]] = mapped_column(JSONB, default=list, nullable=False)
    schedule_kind: Mapped[ScheduleKind] = mapped_column(
        StrEnumType(ScheduleKind, 16), default=ScheduleKind.DAILY, nullable=False
    )
    schedule_value: Mapped[str] = mapped_column(String(64), nullable=False)
    target_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    pin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    delete_previous: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_message_id: Mapped[int | None] = mapped_column(BigInteger)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    arq_job_id: Mapped[str | None] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class StatEvent(Base):
    """Raw activity event, written in batches and pruned after retention."""

    __tablename__ = "stat_events"
    __table_args__ = (
        Index("ix_stat_events_chat_created", "chat_id", "created_at"),
        Index("ix_stat_events_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    tg_user_id: Mapped[int | None] = mapped_column(BigInteger)
    event_type: Mapped[StatEventType] = mapped_column(StrEnumType(StatEventType), nullable=False)
    payload: Mapped[JsonDict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class StatDaily(TimestampMixin, Base):
    """Daily rollup produced by the aggregation cron job."""

    __tablename__ = "stat_daily"
    __table_args__ = (UniqueConstraint("chat_id", "date", name="uq_stat_daily_chat_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    messages: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active_users: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    joins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    leaves: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    moderation_actions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metrics: Mapped[JsonDict] = mapped_column(JSONB, default=dict, nullable=False)


class StatUserDaily(TimestampMixin, Base):
    """Per-user daily message counts, powering the top-10 leaderboard."""

    __tablename__ = "stat_user_daily"
    __table_args__ = (
        UniqueConstraint("chat_id", "date", "tg_user_id", name="uq_stat_user_daily"),
        Index("ix_stat_user_daily_lookup", "chat_id", "date", "messages"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    messages: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Reputation(TimestampMixin, Base):
    """Reputation points and activity level per user per chat."""

    __tablename__ = "reputations"
    __table_args__ = (
        UniqueConstraint("chat_id", "tg_user_id", name="uq_reputation_chat_user"),
        Index("ix_reputation_top", "chat_id", "points"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    experience: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    weekly_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    monthly_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class GlobalBan(TimestampMixin, Base):
    """Cross-chat scammer blacklist; `chat_count` drives the promotion threshold."""

    __tablename__ = "global_bans"
    __table_args__ = (Index("ix_global_bans_active", "is_active", "chat_count"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    chat_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    banned_by: Mapped[int | None] = mapped_column(BigInteger)
    appealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GlobalBanReport(TimestampMixin, Base):
    """One report per (chat, user) so the same chat cannot inflate the counter."""

    __tablename__ = "global_ban_reports"
    __table_args__ = (UniqueConstraint("chat_id", "tg_user_id", name="uq_ban_report_chat_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    reported_by: Mapped[int | None] = mapped_column(BigInteger)


class Payment(TimestampMixin, Base):
    """Payment record. The unique (provider, provider_payment_id) pair makes
    webhook replays idempotent."""

    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("provider", "provider_payment_id", name="uq_payment_provider_id"),
        Index("ix_payments_chat_created", "chat_id", "created_at"),
        Index("ix_payments_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[PaymentProvider] = mapped_column(StrEnumType(PaymentProvider), nullable=False)
    provider_payment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        StrEnumType(PaymentStatus), default=PaymentStatus.PENDING, nullable=False
    )
    plan: Mapped[Plan] = mapped_column(StrEnumType(Plan), nullable=False)
    months: Mapped[int] = mapped_column(SmallInteger, default=1, nullable=False)
    payer_tg_id: Mapped[int | None] = mapped_column(BigInteger)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw: Mapped[JsonDict] = mapped_column(JSONB, default=dict, nullable=False)


class AiCheckLog(Base):
    """Audit trail of AI verdicts; also the source for per-day budget reporting."""

    __tablename__ = "ai_check_logs"
    __table_args__ = (Index("ix_ai_logs_chat_created", "chat_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    tg_user_id: Mapped[int | None] = mapped_column(BigInteger)
    label: Mapped[AiVerdictLabel] = mapped_column(StrEnumType(AiVerdictLabel), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("0"), nullable=False)
    action: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ModerationLog(Base):
    """Every moderation action, mirrored to the chat's log channel."""

    __tablename__ = "moderation_logs"
    __table_args__ = (Index("ix_moderation_logs_chat_created", "chat_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    tg_user_id: Mapped[int | None] = mapped_column(BigInteger)
    moderator_tg_id: Mapped[int | None] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    details: Mapped[JsonDict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


__all__ = [
    "AdminUser",
    "AiCheckLog",
    "CaptchaChallenge",
    "Chat",
    "ChatModuleConfig",
    "GlobalBan",
    "GlobalBanReport",
    "ModerationLog",
    "Payment",
    "Punishment",
    "Reputation",
    "ScheduledPost",
    "StatDaily",
    "StatEvent",
    "StatUserDaily",
    "TgUser",
    "TriggerRule",
    "Warn",
]
