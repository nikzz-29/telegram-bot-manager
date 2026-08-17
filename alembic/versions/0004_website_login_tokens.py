"""Single-use credentials for the standalone user website.

Revision ID: 0004_website_login_tokens
Revises: 0003_platform_settings
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004_website_login_tokens"
down_revision = "0003_platform_settings"
branch_labels = None
depends_on = None

_NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "website_login_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False, server_default="website"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_website_login_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_website_login_tokens_token_hash"),
    )
    op.create_index(
        "ix_website_login_tokens_lookup",
        "website_login_tokens",
        ["token_hash", "scope", "expires_at"],
    )
    op.create_index(
        "ix_website_login_tokens_tg_user_id",
        "website_login_tokens",
        ["tg_user_id"],
    )
    op.create_index(
        "ix_website_login_tokens_user",
        "website_login_tokens",
        ["tg_user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_website_login_tokens_user", table_name="website_login_tokens")
    op.drop_index("ix_website_login_tokens_lookup", table_name="website_login_tokens")
    op.drop_index("ix_website_login_tokens_tg_user_id", table_name="website_login_tokens")
    op.drop_table("website_login_tokens")
