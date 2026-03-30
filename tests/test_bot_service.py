from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from vpn_rating_watcher.bot.service import (
    format_last_snapshot_summary,
    get_last_snapshot_summary,
    get_today_or_latest_chart,
    upsert_telegram_chat,
)
from vpn_rating_watcher.charts.service import LINE_CHART_TYPE
from vpn_rating_watcher.db.base import Base
from vpn_rating_watcher.db.models import (
    GeneratedChart,
    Snapshot,
    TelegramChat,
    Vpn,
    VpnSnapshotResult,
)


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def test_upsert_telegram_chat_creates_and_updates() -> None:
    with _session() as session:
        upsert_telegram_chat(session, chat_id="123", chat_type="private", title=None)
        upsert_telegram_chat(session, chat_id="123", chat_type="group", title="VPN Chat")

        rows = session.scalars(select(TelegramChat)).all()
        assert len(rows) == 1
        assert rows[0].chat_id == "123"
        assert rows[0].chat_type == "group"
        assert rows[0].title == "VPN Chat"
        assert rows[0].is_active is True


def test_get_today_or_latest_chart_prefers_today() -> None:
    with _session() as session:
        older = GeneratedChart(
            chart_date=date(2026, 3, 28),
            chart_type=LINE_CHART_TYPE,
            file_path="artifacts/charts/older.png",
        )
        today = GeneratedChart(
            chart_date=date(2026, 3, 29),
            chart_type=LINE_CHART_TYPE,
            file_path="artifacts/charts/today.png",
        )
        session.add_all([older, today])
        session.commit()

        found = get_today_or_latest_chart(session, today=date(2026, 3, 29))
        assert found is not None
        assert found.file_path == Path("artifacts/charts/today.png")


def test_get_today_or_latest_chart_falls_back_to_latest() -> None:
    with _session() as session:
        older = GeneratedChart(
            chart_date=date(2026, 3, 28),
            chart_type=LINE_CHART_TYPE,
            file_path="artifacts/charts/older.png",
        )
        newest = GeneratedChart(
            chart_date=date(2026, 3, 29),
            chart_type=LINE_CHART_TYPE,
            file_path="artifacts/charts/newest.png",
        )
        session.add_all([older, newest])
        session.commit()

        found = get_today_or_latest_chart(session, today=date(2026, 3, 30))
        assert found is not None
        assert found.file_path == Path("artifacts/charts/newest.png")


def test_last_snapshot_summary_top_ten_format() -> None:
    with _session() as session:
        snapshot = Snapshot(
            source_name="maximkatz",
            source_url="https://vpn.maximkatz.com/",
            fetched_at=datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc),
            content_hash="latest-hash",
            raw_payload_json={},
        )
        session.add(snapshot)
        session.flush()

        for i in range(12):
            vpn = Vpn(name=f"VPN {i + 1}", normalized_name=f"vpn {i + 1}")
            session.add(vpn)
            session.flush()
            session.add(
                VpnSnapshotResult(
                    snapshot_id=snapshot.id,
                    vpn_id=vpn.id,
                    rank_position=i + 1,
                    checked_at=None,
                    checked_at_raw=None,
                    result_raw="30/36",
                    score=30,
                    score_max=36,
                    score_pct=30 / 36,
                    price_raw=None,
                    traffic_raw=None,
                    devices_raw=None,
                    details_url=None,
                )
            )

        session.commit()

        summary = get_last_snapshot_summary(session)
        assert summary is not None
        assert len(summary.top_rows) == 10
        text = format_last_snapshot_summary(summary)

        assert "Source: maximkatz" in text
        assert "Fetched: 2026-03-29 12:00 UTC" in text
        assert "1. VPN 1" in text
        assert "10. VPN 10" in text
        assert "11. VPN 11" not in text
