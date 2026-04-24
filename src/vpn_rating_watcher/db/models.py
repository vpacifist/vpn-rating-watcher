from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from vpn_rating_watcher.db.base import Base


class Vpn(Base):
    __tablename__ = "vpn"
    __table_args__ = (UniqueConstraint("normalized_name", name="uq_vpn_normalized_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Snapshot(Base):
    __tablename__ = "snapshot"
    __table_args__ = (
        UniqueConstraint("source_name", "content_hash", name="uq_snapshot_source_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_name: Mapped[str] = mapped_column(String(100), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    raw_html_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    screenshot_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_json_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VpnSnapshotResult(Base):
    __tablename__ = "vpn_snapshot_result"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "vpn_id", name="uq_vpn_snapshot_result_snapshot_vpn"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("snapshot.id", ondelete="CASCADE"), nullable=False
    )
    vpn_id: Mapped[int] = mapped_column(ForeignKey("vpn.id", ondelete="CASCADE"), nullable=False)
    rank_position: Mapped[int] = mapped_column(Integer, nullable=False)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checked_at_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_raw: Mapped[str] = mapped_column(String(32), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    score_max: Mapped[int] = mapped_column(Integer, nullable=False)
    score_pct: Mapped[float] = mapped_column(Float, nullable=False)
    price_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    traffic_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    devices_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    details_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GeneratedChart(Base):
    __tablename__ = "generated_chart"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chart_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    chart_type: Mapped[str] = mapped_column(String(100), nullable=False)
    source_name: Mapped[str] = mapped_column(String(100), nullable=False)
    range_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    range_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    range_days: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TelegramChat(Base):
    __tablename__ = "telegram_chat"
    __table_args__ = (UniqueConstraint("chat_id", name="uq_telegram_chat_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[str] = mapped_column(String(100), nullable=False)
    chat_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    chart_theme: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    update_interval_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    last_posted_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
