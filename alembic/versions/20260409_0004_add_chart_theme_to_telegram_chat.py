"""add chart theme preference to telegram chat

Revision ID: 20260409_0004
Revises: 20260404_0003
Create Date: 2026-04-09 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260409_0004"
down_revision = "20260404_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("telegram_chat", sa.Column("chart_theme", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("telegram_chat", "chart_theme")
