from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from vpn_rating_watcher.bot.service import (
    TelegramBotService,
    format_last_snapshot_summary,
    get_last_snapshot_summary,
    get_today_or_latest_chart,
    upsert_telegram_chat,
)
from vpn_rating_watcher.charts.service import (
    CHART_MODE_MEDIAN_3D,
    CHART_THEME_DARK,
    CHART_THEME_LIGHT,
    LINE_CHART_TYPE,
)
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


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(engine)


def test_upsert_telegram_chat_creates_and_updates() -> None:
    with _session() as session:
        upsert_telegram_chat(session, chat_id="123", chat_type="private", title=None)
        upsert_telegram_chat(
            session,
            chat_id="123",
            chat_type="group",
            title="VPN Chat",
            chart_theme=CHART_THEME_LIGHT,
            is_active=False,
        )

        rows = session.scalars(select(TelegramChat)).all()
        assert len(rows) == 1
        assert rows[0].chat_id == "123"
        assert rows[0].chat_type == "group"
        assert rows[0].title == "VPN Chat"
        assert rows[0].chart_theme == CHART_THEME_LIGHT
        assert rows[0].is_active is False


def test_set_chat_theme_persists_theme_without_changing_subscription() -> None:
    session_factory = _session_factory()
    service = TelegramBotService(session_factory=session_factory)

    service.set_chat_subscription(
        chat_id="123",
        chat_type="private",
        title=None,
        is_active=False,
    )
    service.set_chat_theme(
        chat_id="123",
        chat_type="private",
        title=None,
        chart_theme=CHART_THEME_LIGHT,
    )

    with session_factory() as session:
        chat = session.execute(
            select(TelegramChat).where(TelegramChat.chat_id == "123")
        ).scalar_one()
        assert chat.chart_theme == CHART_THEME_LIGHT
        assert chat.is_active is False


def test_get_chat_theme_returns_none_or_saved_theme() -> None:
    session_factory = _session_factory()
    service = TelegramBotService(session_factory=session_factory)

    assert service.get_chat_theme(chat_id="missing") is None

    service.set_chat_theme(
        chat_id="123",
        chat_type="private",
        title=None,
        chart_theme=CHART_THEME_DARK,
    )

    assert service.get_chat_theme(chat_id="123") == CHART_THEME_DARK


def test_chat_subscription_status_uses_current_active_flag() -> None:
    session_factory = _session_factory()
    service = TelegramBotService(session_factory=session_factory)

    service.set_chat_subscription(
        chat_id="-100123",
        chat_type="supergroup",
        title="VPN Group",
        is_active=True,
    )
    assert service.is_chat_subscribed(chat_id="-100123") is True

    service.set_chat_subscription(
        chat_id="-100123",
        chat_type="supergroup",
        title="VPN Group",
        is_active=False,
    )
    assert service.is_chat_subscribed(chat_id="-100123") is False


def test_get_today_or_latest_chart_prefers_today() -> None:
    with _session() as session:
        older = GeneratedChart(
            chart_date=date(2026, 3, 28),
            chart_type=LINE_CHART_TYPE,
            source_name="maximkatz",
            range_start_date=date(2026, 3, 28),
            range_end_date=date(2026, 3, 28),
            range_days=1,
            file_path="artifacts/charts/older.png",
        )
        today = GeneratedChart(
            chart_date=date(2026, 3, 29),
            chart_type=LINE_CHART_TYPE,
            source_name="maximkatz",
            range_start_date=date(2026, 3, 29),
            range_end_date=date(2026, 3, 29),
            range_days=1,
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
            source_name="maximkatz",
            range_start_date=date(2026, 3, 28),
            range_end_date=date(2026, 3, 28),
            range_days=1,
            file_path="artifacts/charts/older.png",
        )
        newest = GeneratedChart(
            chart_date=date(2026, 3, 29),
            chart_type=LINE_CHART_TYPE,
            source_name="maximkatz",
            range_start_date=date(2026, 3, 29),
            range_end_date=date(2026, 3, 29),
            range_days=1,
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
                    checked_at=datetime(2026, 3, 29, 8, i, tzinfo=timezone.utc),
                    checked_at_raw=f"29 мар, 08:{i:02d}",
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

        assert "🏆 Top VPN — snapshot 2026-03-29 12:00 UTC" in text
        assert "ℹ️ Source: maximkatz · 36 checks/provider" in text
        assert "🟢 #1 VPN 1 — 83.3% (30/36)" in text
        assert "🟢 #10 VPN 10 — 83.3% (30/36)" in text
        assert "11. VPN 11" not in text
        assert "checked:" not in text
        assert "🕒 Freshness:" in text


def test_last_snapshot_summary_uses_checked_at_raw_when_checked_at_missing() -> None:
    with _session() as session:
        snapshot = Snapshot(
            source_name="maximkatz",
            source_url="https://vpn.maximkatz.com/",
            fetched_at=datetime(2026, 4, 3, 12, 0, tzinfo=timezone.utc),
            content_hash="raw-time-hash",
            raw_payload_json={},
        )
        session.add(snapshot)
        session.flush()

        vpn = Vpn(name="blancvpn", normalized_name="blancvpn")
        session.add(vpn)
        session.flush()
        session.add(
            VpnSnapshotResult(
                snapshot_id=snapshot.id,
                vpn_id=vpn.id,
                rank_position=1,
                checked_at=None,
                checked_at_raw="3 апр, 09:13",
                result_raw="34/36",
                score=34,
                score_max=36,
                score_pct=34 / 36,
                price_raw=None,
                traffic_raw=None,
                devices_raw=None,
                details_url=None,
            )
        )
        session.commit()

        summary = get_last_snapshot_summary(session)
        assert summary is not None
        text = format_last_snapshot_summary(summary)
        assert "🕒 Freshness: 3 Apr, 09:13–09:13 UTC" in text


def test_last_snapshot_summary_shows_end_date_for_cross_day_freshness_range() -> None:
    with _session() as session:
        snapshot = Snapshot(
            source_name="maximkatz",
            source_url="https://vpn.maximkatz.com/",
            fetched_at=datetime(2026, 4, 3, 12, 0, tzinfo=timezone.utc),
            content_hash="cross-day-freshness",
            raw_payload_json={},
        )
        session.add(snapshot)
        session.flush()

        first_vpn = Vpn(name="firstvpn", normalized_name="firstvpn")
        second_vpn = Vpn(name="secondvpn", normalized_name="secondvpn")
        session.add_all([first_vpn, second_vpn])
        session.flush()

        session.add_all(
            [
                VpnSnapshotResult(
                    snapshot_id=snapshot.id,
                    vpn_id=first_vpn.id,
                    rank_position=1,
                    checked_at=datetime(2026, 4, 2, 21, 42, tzinfo=timezone.utc),
                    checked_at_raw="2 апр, 21:42",
                    result_raw="34/36",
                    score=34,
                    score_max=36,
                    score_pct=34 / 36,
                    price_raw=None,
                    traffic_raw=None,
                    devices_raw=None,
                    details_url=None,
                ),
                VpnSnapshotResult(
                    snapshot_id=snapshot.id,
                    vpn_id=second_vpn.id,
                    rank_position=2,
                    checked_at=datetime(2026, 4, 3, 12, 4, tzinfo=timezone.utc),
                    checked_at_raw="3 апр, 12:04",
                    result_raw="30/36",
                    score=30,
                    score_max=36,
                    score_pct=30 / 36,
                    price_raw=None,
                    traffic_raw=None,
                    devices_raw=None,
                    details_url=None,
                ),
            ]
        )
        session.commit()

        summary = get_last_snapshot_summary(session)
        assert summary is not None
        text = format_last_snapshot_summary(summary)
        assert "🕒 Freshness: 2 Apr, 21:42–3 Apr, 12:04 UTC" in text


def test_load_latest_chart_regenerates_file_when_metadata_exists_but_file_missing() -> None:
    session_factory = _session_factory()
    with session_factory() as session:
        snapshot = Snapshot(
            source_name="maximkatz",
            source_url="https://vpn.maximkatz.com/",
            fetched_at=datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc),
            content_hash="chart-regenerate",
            raw_payload_json={},
        )
        session.add(snapshot)
        session.flush()

        vpn = Vpn(name="VPN A", normalized_name="vpn a")
        session.add(vpn)
        session.flush()
        session.add(
            VpnSnapshotResult(
                snapshot_id=snapshot.id,
                vpn_id=vpn.id,
                rank_position=1,
                checked_at=datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc),
                checked_at_raw=None,
                result_raw="34/36",
                score=34,
                score_max=36,
                score_pct=34 / 36,
                price_raw=None,
                traffic_raw=None,
                devices_raw=None,
                details_url=None,
            )
        )
        session.add(
            GeneratedChart(
                chart_date=date(2026, 3, 29),
                chart_type=LINE_CHART_TYPE,
                source_name="mixed",
                range_start_date=date(2026, 3, 20),
                range_end_date=date(2026, 3, 29),
                range_days=10,
                file_path="artifacts/charts/missing-from-other-service.png",
            )
        )
        session.commit()

    service = TelegramBotService(session_factory=session_factory)
    chart, error = service.load_latest_chart()

    assert error is None
    assert chart is not None
    assert chart.file_path.exists()


def test_load_latest_chart_passes_generated_chart_metadata_for_regeneration(tmp_path: Path) -> None:
    session_factory = _session_factory()
    with session_factory() as session:
        session.add(
            GeneratedChart(
                chart_date=date(2026, 3, 29),
                chart_type=LINE_CHART_TYPE,
                source_name="mixed",
                range_start_date=date(2026, 3, 20),
                range_end_date=date(2026, 3, 29),
                range_days=10,
                file_path="artifacts/charts/missing-metadata-source.png",
            )
        )
        session.commit()

    fake_output = tmp_path / "regenerated.png"
    fake_output.write_bytes(b"png")
    service = TelegramBotService(session_factory=session_factory)

    with patch("vpn_rating_watcher.bot.service.regenerate_chart_to_temp_file") as regenerate:
        regenerate.return_value = fake_output
        chart, error = service.load_latest_chart()

    assert error is None
    assert chart is not None
    assert chart.file_path == fake_output
    assert chart.is_temporary is True
    assert regenerate.call_args is not None
    metadata = regenerate.call_args.kwargs["metadata"]
    assert metadata.source_name == "mixed"
    assert metadata.range_start_date == date(2026, 3, 20)
    assert metadata.range_end_date == date(2026, 3, 29)
    assert metadata.range_days == 10


def test_load_latest_chart_median_mode_always_uses_regeneration(tmp_path: Path) -> None:
    session_factory = _session_factory()
    existing_file = tmp_path / "existing-daily.png"
    existing_file.write_bytes(b"daily")
    with session_factory() as session:
        session.add(
            GeneratedChart(
                chart_date=date(2026, 3, 29),
                chart_type=LINE_CHART_TYPE,
                source_name="mixed",
                range_start_date=date(2026, 3, 20),
                range_end_date=date(2026, 3, 29),
                range_days=10,
                file_path=str(existing_file),
            )
        )
        session.commit()

    fake_output = tmp_path / "regenerated-median.png"
    fake_output.write_bytes(b"png")
    service = TelegramBotService(session_factory=session_factory)

    with patch("vpn_rating_watcher.bot.service.regenerate_chart_to_temp_file") as regenerate:
        regenerate.return_value = fake_output
        chart, error = service.load_latest_chart(mode=CHART_MODE_MEDIAN_3D)

    assert error is None
    assert chart is not None
    assert chart.file_path == fake_output
    assert chart.is_temporary is True
    assert regenerate.call_args is not None
    assert regenerate.call_args.kwargs["mode"] == CHART_MODE_MEDIAN_3D


def test_load_latest_chart_light_theme_always_uses_regeneration(tmp_path: Path) -> None:
    session_factory = _session_factory()
    existing_file = tmp_path / "existing-dark.png"
    existing_file.write_bytes(b"dark")
    with session_factory() as session:
        session.add(
            GeneratedChart(
                chart_date=date(2026, 3, 29),
                chart_type=LINE_CHART_TYPE,
                source_name="mixed",
                range_start_date=date(2026, 3, 20),
                range_end_date=date(2026, 3, 29),
                range_days=10,
                file_path=str(existing_file),
            )
        )
        session.commit()

    fake_output = tmp_path / "regenerated-light.png"
    fake_output.write_bytes(b"png")
    service = TelegramBotService(session_factory=session_factory)

    with patch("vpn_rating_watcher.bot.service.regenerate_chart_to_temp_file") as regenerate:
        regenerate.return_value = fake_output
        chart, error = service.load_latest_chart(theme=CHART_THEME_LIGHT)

    assert error is None
    assert chart is not None
    assert chart.file_path == fake_output
    assert chart.is_temporary is True
    assert regenerate.call_args is not None
    assert regenerate.call_args.kwargs["theme"] == CHART_THEME_LIGHT
