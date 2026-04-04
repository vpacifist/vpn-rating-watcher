"""create initial persistence tables

Revision ID: 20260329_0001
Revises:
Create Date: 2026-03-29 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260329_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vpn",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("normalized_name", name="uq_vpn_normalized_name"),
    )

    op.create_table(
        "snapshot",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_name", sa.String(length=100), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("raw_payload_json", sa.JSON(), nullable=False),
        sa.Column("raw_html_path", sa.Text(), nullable=True),
        sa.Column("screenshot_path", sa.Text(), nullable=True),
        sa.Column("normalized_json_path", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("source_name", "content_hash", name="uq_snapshot_source_hash"),
    )

    op.create_table(
        "vpn_snapshot_result",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "snapshot_id",
            sa.Integer(),
            sa.ForeignKey("snapshot.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "vpn_id", sa.Integer(), sa.ForeignKey("vpn.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("rank_position", sa.Integer(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checked_at_raw", sa.Text(), nullable=True),
        sa.Column("result_raw", sa.String(length=32), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("score_max", sa.Integer(), nullable=False),
        sa.Column("score_pct", sa.Float(), nullable=False),
        sa.Column("price_raw", sa.Text(), nullable=True),
        sa.Column("traffic_raw", sa.Text(), nullable=True),
        sa.Column("devices_raw", sa.Text(), nullable=True),
        sa.Column("details_url", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("snapshot_id", "vpn_id", name="uq_vpn_snapshot_result_snapshot_vpn"),
    )

    op.create_table(
        "generated_chart",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chart_date", sa.Date(), nullable=True),
        sa.Column("chart_type", sa.String(length=100), nullable=False),
        sa.Column("source_name", sa.String(length=100), nullable=True),
        sa.Column("range_start_date", sa.Date(), nullable=True),
        sa.Column("range_end_date", sa.Date(), nullable=True),
        sa.Column("range_days", sa.Integer(), nullable=True),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "telegram_chat",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chat_id", sa.String(length=100), nullable=False),
        sa.Column("chat_type", sa.String(length=50), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_posted_date", sa.Date(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("chat_id", name="uq_telegram_chat_id"),
    )


def downgrade() -> None:
    op.drop_table("telegram_chat")
    op.drop_table("generated_chart")
    op.drop_table("vpn_snapshot_result")
    op.drop_table("snapshot")
    op.drop_table("vpn")
