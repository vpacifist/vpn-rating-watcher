"""add update schedule fields to telegram chat

Revision ID: 20260424_0005
Revises: 20260409_0004
Create Date: 2026-04-24 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260424_0005"
down_revision = "20260409_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "telegram_chat",
        sa.Column("update_interval_hours", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "telegram_chat",
        sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("telegram_chat", "last_notified_at")
    op.drop_column("telegram_chat", "update_interval_hours")
