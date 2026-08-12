"""Operator console: plan overrides, refunds, reporting indexes.

Revision ID: 0002_platform_console
Revises: 0001_initial

Three unrelated-looking changes ship as one revision because they are one
feature: the creator-only console needs somewhere to store edited prices and
feature sets, somewhere to record a refund, and indexes for the two queries it
adds that read across every chat.

`plan_overrides` is deliberately sparse — a NULL column means "use the shipped
default from `shared.plans`" rather than a copy of today's value, so a plan whose
price was edited still tracks feature changes that ship in a release.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_platform_console"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

_NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "plan_overrides",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("plan", sa.String(length=32), nullable=False),
        # NULL means "not overridden"; see the module docstring.
        sa.Column("stars", sa.Integer(), nullable=True),
        sa.Column("usd", sa.String(length=16), nullable=True),
        sa.Column("features", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_plan_overrides"),
        # One row per plan: the resolver reads the whole table and expects to find
        # at most one answer per plan.
        sa.UniqueConstraint("plan", name="uq_plan_overrides_plan"),
    )

    # Refund bookkeeping. `status` already carries `refunded`; these say when, by
    # whom and why, which is the part an operator has to be able to answer later.
    op.add_column(
        "payments", sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("payments", sa.Column("refunded_by", sa.BigInteger(), nullable=True))
    op.add_column(
        "payments", sa.Column("refund_reason", sa.Text(), nullable=False, server_default="")
    )

    # Platform-wide revenue and growth series: both scan a date range across every
    # chat, which the existing (chat_id, created_at) indexes cannot serve.
    op.create_index("ix_payments_created", "payments", ["created_at"])
    op.create_index("ix_chats_created", "chats", ["created_at"])

    # Per-moderator reporting inside one chat.
    op.create_index(
        "ix_moderation_logs_moderator",
        "moderation_logs",
        ["chat_id", "moderator_tg_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_moderation_logs_moderator", table_name="moderation_logs")
    op.drop_index("ix_chats_created", table_name="chats")
    op.drop_index("ix_payments_created", table_name="payments")
    op.drop_column("payments", "refund_reason")
    op.drop_column("payments", "refunded_by")
    op.drop_column("payments", "refunded_at")
    op.drop_table("plan_overrides")
