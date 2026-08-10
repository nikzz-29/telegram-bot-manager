"""Initial schema.

Explicit DDL rather than metadata.create_all so the migration stays a fixed,
reviewable artefact that does not drift when the models change.

Revision ID: 0001_initial
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

_NOW = sa.text("now()")


def _timestamps() -> tuple[sa.Column[datetime], sa.Column[datetime]]:
    # `sa.Column` is generic over the *Python* type, not the SQL one.
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "chats",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tg_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("plan", sa.String(length=32), nullable=False),
        sa.Column("plan_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("grace_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auto_renew", sa.Boolean(), nullable=False),
        sa.Column("owner_tg_id", sa.BigInteger(), nullable=True),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("members_count", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("lockdown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_chats"),
        sa.UniqueConstraint("tg_chat_id", name="uq_chats_tg_chat_id"),
    )
    op.create_index("ix_chats_plan_expires", "chats", ["plan", "plan_expires_at"])
    op.create_index("ix_chats_owner", "chats", ["owner_tg_id"])
    op.create_index(
        "ix_chats_settings_gin", "chats", ["settings"], postgresql_using="gin"
    )

    op.create_table(
        "tg_users",
        sa.Column("tg_user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("first_name", sa.String(length=128), nullable=False),
        sa.Column("last_name", sa.String(length=128), nullable=True),
        sa.Column("language_code", sa.String(length=8), nullable=True),
        sa.Column("is_bot", sa.Boolean(), nullable=False),
        sa.Column("has_photo", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("tg_user_id", name="pk_tg_users"),
    )

    op.create_table(
        "chat_module_configs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("module", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["chat_id"],
            ["chats.id"],
            name="fk_chat_module_configs_chat_id_chats",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chat_module_configs"),
        sa.UniqueConstraint("chat_id", "module", name="uq_chat_module"),
    )
    op.create_index("ix_chat_module_configs_chat_id", "chat_module_configs", ["chat_id"])
    op.create_index(
        "ix_module_configs_module_enabled", "chat_module_configs", ["module", "enabled"]
    )
    op.create_table(
        "admin_users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["chat_id"], ["chats.id"], name="fk_admin_users_chat_id_chats", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_admin_users"),
        sa.UniqueConstraint("chat_id", "tg_user_id", name="uq_admin_chat_user"),
    )
    op.create_index("ix_admin_users_chat_id", "admin_users", ["chat_id"])
    op.create_index("ix_admin_users_tg_user_id", "admin_users", ["tg_user_id"])

    op.create_table(
        "warns",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=False),
        sa.Column("moderator_tg_id", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.BigInteger(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["chat_id"], ["chats.id"], name="fk_warns_chat_id_chats", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_warns"),
    )
    op.create_index("ix_warns_chat_user", "warns", ["chat_id", "tg_user_id"])
    # Partial: the hot path only ever counts un-revoked warns.
    op.create_index(
        "ix_warns_active",
        "warns",
        ["chat_id", "tg_user_id", "expires_at"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    op.create_table(
        "punishments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=False),
        sa.Column("moderator_tg_id", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("arq_job_id", sa.String(length=128), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("lifted_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["chat_id"], ["chats.id"], name="fk_punishments_chat_id_chats", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_punishments"),
        sa.UniqueConstraint("arq_job_id", name="uq_punishments_arq_job_id"),
    )
    op.create_index("ix_punishments_chat_user", "punishments", ["chat_id", "tg_user_id"])
    op.create_index(
        "ix_punishments_active",
        "punishments",
        ["chat_id", "tg_user_id", "expires_at"],
        postgresql_where=sa.text("active = true"),
    )
    op.create_index(
        "ix_punishments_expiry_sweep",
        "punishments",
        ["expires_at"],
        postgresql_where=sa.text("active = true"),
    )

    op.create_table(
        "captcha_challenges",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("answer", sa.String(length=64), nullable=False),
        sa.Column("attempts", sa.SmallInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("arq_job_id", sa.String(length=128), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("solved_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["chat_id"],
            ["chats.id"],
            name="fk_captcha_challenges_chat_id_chats",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_captcha_challenges"),
        sa.UniqueConstraint("chat_id", "tg_user_id", name="uq_captcha_chat_user"),
    )
    op.create_index(
        "ix_captcha_expires",
        "captcha_challenges",
        ["expires_at"],
        postgresql_where=sa.text("solved_at IS NULL"),
    )

    op.create_table(
        "trigger_rules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("pattern", sa.String(length=256), nullable=False),
        sa.Column("match", sa.String(length=16), nullable=False),
        sa.Column("response", sa.Text(), nullable=False),
        sa.Column("media_file_id", sa.String(length=256), nullable=True),
        sa.Column("buttons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("case_sensitive", sa.Boolean(), nullable=False),
        sa.Column("delete_trigger", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["chat_id"], ["chats.id"], name="fk_trigger_rules_chat_id_chats", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_trigger_rules"),
    )
    op.create_index("ix_triggers_chat_enabled", "trigger_rules", ["chat_id", "enabled"])

    op.create_table(
        "scheduled_posts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("media_file_id", sa.String(length=256), nullable=True),
        sa.Column("buttons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("schedule_kind", sa.String(length=16), nullable=False),
        sa.Column("schedule_value", sa.String(length=64), nullable=False),
        sa.Column("target_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("pin", sa.Boolean(), nullable=False),
        sa.Column("delete_previous", sa.Boolean(), nullable=False),
        sa.Column("last_message_id", sa.BigInteger(), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("arq_job_id", sa.String(length=128), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["chat_id"], ["chats.id"], name="fk_scheduled_posts_chat_id_chats", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_scheduled_posts"),
    )
    op.create_index("ix_posts_chat_enabled", "scheduled_posts", ["chat_id", "enabled"])
    op.create_index(
        "ix_posts_next_run",
        "scheduled_posts",
        ["next_run_at"],
        postgresql_where=sa.text("enabled = true"),
    )

    op.create_table(
        "stat_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["chat_id"], ["chats.id"], name="fk_stat_events_chat_id_chats", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_stat_events"),
    )
    op.create_index("ix_stat_events_chat_created", "stat_events", ["chat_id", "created_at"])
    op.create_index("ix_stat_events_created", "stat_events", ["created_at"])

    op.create_table(
        "stat_daily",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("messages", sa.Integer(), nullable=False),
        sa.Column("active_users", sa.Integer(), nullable=False),
        sa.Column("joins", sa.Integer(), nullable=False),
        sa.Column("leaves", sa.Integer(), nullable=False),
        sa.Column("moderation_actions", sa.Integer(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["chat_id"], ["chats.id"], name="fk_stat_daily_chat_id_chats", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_stat_daily"),
        sa.UniqueConstraint("chat_id", "date", name="uq_stat_daily_chat_date"),
    )

    op.create_table(
        "stat_user_daily",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=False),
        sa.Column("messages", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["chat_id"], ["chats.id"], name="fk_stat_user_daily_chat_id_chats", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_stat_user_daily"),
        sa.UniqueConstraint("chat_id", "date", "tg_user_id", name="uq_stat_user_daily"),
    )
    op.create_index(
        "ix_stat_user_daily_lookup", "stat_user_daily", ["chat_id", "date", "messages"]
    )

    op.create_table(
        "reputations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("experience", sa.Integer(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("weekly_points", sa.Integer(), nullable=False),
        sa.Column("monthly_points", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["chat_id"], ["chats.id"], name="fk_reputations_chat_id_chats", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reputations"),
        sa.UniqueConstraint("chat_id", "tg_user_id", name="uq_reputation_chat_user"),
    )
    op.create_index("ix_reputation_top", "reputations", ["chat_id", "points"])

    op.create_table(
        "global_bans",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("chat_count", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("banned_by", sa.BigInteger(), nullable=True),
        sa.Column("appealed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_global_bans"),
        sa.UniqueConstraint("tg_user_id", name="uq_global_bans_tg_user_id"),
    )
    op.create_index("ix_global_bans_active", "global_bans", ["is_active", "chat_count"])

    op.create_table(
        "global_ban_reports",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("reported_by", sa.BigInteger(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["chat_id"],
            ["chats.id"],
            name="fk_global_ban_reports_chat_id_chats",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_global_ban_reports"),
        sa.UniqueConstraint("chat_id", "tg_user_id", name="uq_ban_report_chat_user"),
    )
    op.create_index("ix_global_ban_reports_tg_user_id", "global_ban_reports", ["tg_user_id"])

    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_payment_id", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.String(length=128), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("plan", sa.String(length=32), nullable=False),
        sa.Column("months", sa.SmallInteger(), nullable=False),
        sa.Column("payer_tg_id", sa.BigInteger(), nullable=True),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["chat_id"], ["chats.id"], name="fk_payments_chat_id_chats", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_payments"),
        # Makes webhook replays idempotent.
        sa.UniqueConstraint("provider", "provider_payment_id", name="uq_payment_provider_id"),
    )
    op.create_index("ix_payments_chat_created", "payments", ["chat_id", "created_at"])
    op.create_index("ix_payments_status", "payments", ["status"])

    op.create_table(
        "ai_check_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=True),
        sa.Column("label", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("text_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["chat_id"], ["chats.id"], name="fk_ai_check_logs_chat_id_chats", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_check_logs"),
    )
    op.create_index("ix_ai_logs_chat_created", "ai_check_logs", ["chat_id", "created_at"])
    op.create_index("ix_ai_check_logs_text_hash", "ai_check_logs", ["text_hash"])

    op.create_table(
        "moderation_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=True),
        sa.Column("moderator_tg_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["chat_id"], ["chats.id"], name="fk_moderation_logs_chat_id_chats", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_moderation_logs"),
    )
    op.create_index("ix_moderation_logs_chat_created", "moderation_logs", ["chat_id", "created_at"])


def downgrade() -> None:
    for table in (
        "moderation_logs",
        "ai_check_logs",
        "payments",
        "global_ban_reports",
        "global_bans",
        "reputations",
        "stat_user_daily",
        "stat_daily",
        "stat_events",
        "scheduled_posts",
        "trigger_rules",
        "captcha_challenges",
        "punishments",
        "warns",
        "admin_users",
        "chat_module_configs",
        "tg_users",
        "chats",
    ):
        op.drop_table(table)
