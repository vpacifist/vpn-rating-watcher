from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from vpn_rating_watcher.charts.service import LINE_CHART_TYPE
from vpn_rating_watcher.db.base import Base
from vpn_rating_watcher.db.models import (
    GeneratedChart,
    Snapshot,
    TelegramChat,
    Vpn,
    VpnSnapshotResult,
)
from vpn_rating_watcher.jobs.daily_telegram_post import (
    parse_default_chat_ids,
    run_daily_posting_job,
)


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(engine)


def test_parse_default_chat_ids() -> None:
    assert parse_default_chat_ids(None) == []
    assert parse_default_chat_ids("") == []
    assert parse_default_chat_ids(" 1001, -1002 ,, 1003 ") == ["1001", "-1002", "1003"]


def test_post_daily_is_idempotent_for_same_day(tmp_path: Path) -> None:
    session_factory = _session_factory()
    chart_path = tmp_path / "chart.png"
    chart_path.write_bytes(b"png")

    with session_factory() as session:
        session.add(
            GeneratedChart(
                chart_date=date(2026, 3, 29),
                chart_type=LINE_CHART_TYPE,
                source_name="maximkatz",
                range_start_date=date(2026, 3, 29),
                range_end_date=date(2026, 3, 29),
                range_days=1,
                file_path=str(chart_path),
            )
        )
        session.add(
            TelegramChat(chat_id="1001", chat_type="private", title=None, is_active=True)
        )
        session.commit()

    sends: list[str] = []

    async def _fake_send(**kwargs: str) -> None:
        sends.append(kwargs["chat_id"])

    first = run_daily_posting_job(
        session_factory=session_factory,
        token="test-token",
        default_chat_ids_raw=None,
        today=date(2026, 3, 29),
        send_chart_func=_fake_send,
    )
    second = run_daily_posting_job(
        session_factory=session_factory,
        token="test-token",
        default_chat_ids_raw=None,
        today=date(2026, 3, 29),
        send_chart_func=_fake_send,
    )

    assert first.posted_count == 1
    assert first.failed_count == 0
    assert second.posted_count == 0
    assert second.failed_count == 0
    assert sends == ["1001"]


def test_post_daily_skips_inactive_chats(tmp_path: Path) -> None:
    session_factory = _session_factory()
    chart_path = tmp_path / "chart.png"
    chart_path.write_bytes(b"png")

    with session_factory() as session:
        session.add(
            GeneratedChart(
                chart_date=date(2026, 3, 29),
                chart_type=LINE_CHART_TYPE,
                source_name="maximkatz",
                range_start_date=date(2026, 3, 29),
                range_end_date=date(2026, 3, 29),
                range_days=1,
                file_path=str(chart_path),
            )
        )
        session.add(
            TelegramChat(chat_id="1001", chat_type="private", title=None, is_active=True)
        )
        session.add(
            TelegramChat(chat_id="1002", chat_type="private", title=None, is_active=False)
        )
        session.commit()

    sends: list[str] = []

    async def _fake_send(**kwargs: str) -> None:
        sends.append(kwargs["chat_id"])

    result = run_daily_posting_job(
        session_factory=session_factory,
        token="test-token",
        default_chat_ids_raw=None,
        today=date(2026, 3, 29),
        send_chart_func=_fake_send,
    )

    assert result.posted_count == 1
    assert result.failed_count == 0
    assert result.active_chat_count == 1
    assert sends == ["1001"]


def test_post_daily_exits_cleanly_when_today_chart_missing() -> None:
    session_factory = _session_factory()

    sends: list[str] = []

    async def _fake_send(**kwargs: str) -> None:
        sends.append(kwargs["chat_id"])

    result = run_daily_posting_job(
        session_factory=session_factory,
        token="test-token",
        default_chat_ids_raw="1001,1002",
        today=date(2026, 3, 29),
        send_chart_func=_fake_send,
    )

    with session_factory() as session:
        chats = (
            session.execute(select(TelegramChat).order_by(TelegramChat.chat_id.asc()))
            .scalars()
            .all()
        )

    assert result.status == "no_chart"
    assert result.posted_count == 0
    assert result.failed_count == 0
    assert sends == []
    assert [chat.chat_id for chat in chats] == ["1001", "1002"]
    assert all(chat.last_posted_date is None for chat in chats)


def test_post_daily_regenerates_chart_when_file_missing_on_disk() -> None:
    session_factory = _session_factory()
    with session_factory() as session:
        snapshot = Snapshot(
            source_name="maximkatz",
            source_url="https://vpn.maximkatz.com/",
            fetched_at=datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc),
            content_hash="daily-regenerate",
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
                source_name="maximkatz",
                range_start_date=date(2026, 3, 1),
                range_end_date=date(2026, 3, 29),
                range_days=29,
                file_path="artifacts/charts/missing-chart.png",
            )
        )
        session.add(
            TelegramChat(chat_id="1001", chat_type="private", title=None, is_active=True)
        )
        session.commit()

    sends: list[Path] = []

    async def _fake_send(**kwargs: str | Path) -> None:
        sends.append(Path(kwargs["chart_path"]))

    result = run_daily_posting_job(
        session_factory=session_factory,
        token="test-token",
        default_chat_ids_raw=None,
        today=date(2026, 3, 29),
        send_chart_func=_fake_send,
    )

    assert result.status == "ok"
    assert result.posted_count == 1
    assert result.failed_count == 0
    assert len(sends) == 1
    assert not sends[0].exists()


def test_post_daily_disables_chat_when_send_forbidden(tmp_path: Path) -> None:
    from aiogram.exceptions import TelegramForbiddenError

    session_factory = _session_factory()
    chart_path = tmp_path / "chart.png"
    chart_path.write_bytes(b"png")

    with session_factory() as session:
        session.add(
            GeneratedChart(
                chart_date=date(2026, 3, 29),
                chart_type=LINE_CHART_TYPE,
                source_name="maximkatz",
                range_start_date=date(2026, 3, 29),
                range_end_date=date(2026, 3, 29),
                range_days=1,
                file_path=str(chart_path),
            )
        )
        session.add(
            TelegramChat(chat_id="-10042", chat_type="supergroup", title="VPN", is_active=True)
        )
        session.commit()

    async def _fake_send(**kwargs: str) -> None:
        raise TelegramForbiddenError(
            method="sendPhoto",
            message=f"chat {kwargs['chat_id']} blocked",
        )

    result = run_daily_posting_job(
        session_factory=session_factory,
        token="test-token",
        default_chat_ids_raw=None,
        today=date(2026, 3, 29),
        send_chart_func=_fake_send,
    )

    assert result.status == "ok"
    assert result.posted_count == 0
    assert result.failed_count == 1
    assert "cannot send messages" in result.message

    with session_factory() as session:
        chat = session.execute(
            select(TelegramChat).where(TelegramChat.chat_id == "-10042")
        ).scalar_one()
    assert chat.is_active is False
