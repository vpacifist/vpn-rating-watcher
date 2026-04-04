from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from vpn_rating_watcher.charts.service import LINE_CHART_TYPE, ChartGenerationResult
from vpn_rating_watcher.db.base import Base
from vpn_rating_watcher.db.models import GeneratedChart, TelegramChat
from vpn_rating_watcher.jobs.hourly_sync import run_hourly_sync_job
from vpn_rating_watcher.scraper.models import NormalizedRow, ScrapeResult


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(engine)


def _make_scrape_result(*, table_hash: str, score_a: int, score_b: int) -> ScrapeResult:
    rows = [
        NormalizedRow(
            rank_position=1,
            vpn_name="VPN A",
            checked_at_raw="29 Mar, 11:00",
            result_raw=f"{score_a}/36",
            score=score_a,
            score_max=36,
            score_pct=score_a / 36,
        ),
        NormalizedRow(
            rank_position=2,
            vpn_name="VPN B",
            checked_at_raw="29 Mar, 11:00",
            result_raw=f"{score_b}/36",
            score=score_b,
            score_max=36,
            score_pct=score_b / 36,
        ),
    ]
    return ScrapeResult(
        source_url="https://vpn.maximkatz.com/",
        scraped_at_utc=datetime(2026, 3, 29, 11, 0, tzinfo=timezone.utc).isoformat(),
        table_hash=table_hash,
        row_count=len(rows),
        rows=rows,
        artifacts_dir="artifacts/test",
    )


def test_hourly_sync_no_change_skips_chart_and_notify() -> None:
    session_factory = _session_factory()

    first_result = _make_scrape_result(table_hash="hash-1", score_a=30, score_b=20)
    same_result = _make_scrape_result(table_hash="hash-1", score_a=30, score_b=20)
    scrape_calls = [first_result, same_result]

    def _fake_scrape(**_: object) -> ScrapeResult:
        return scrape_calls.pop(0)

    sent: list[str] = []

    async def _fake_send(**kwargs: str) -> None:
        sent.append(kwargs["chat_id"])

    with session_factory() as session:
        session.add(TelegramChat(chat_id="1001", chat_type="private", title=None, is_active=True))
        session.commit()

    first = run_hourly_sync_job(
        session_factory=session_factory,
        source_name="maximkatz",
        source_url="https://vpn.maximkatz.com/",
        artifacts_dir="artifacts",
        headless=True,
        token="token",
        default_chat_ids_raw=None,
        scrape_func=_fake_scrape,
        chart_func=lambda **kwargs: _realistic_chart_result(kwargs["session"], Path("chart-1.png")),
        send_message_func=_fake_send,
    )

    second = run_hourly_sync_job(
        session_factory=session_factory,
        source_name="maximkatz",
        source_url="https://vpn.maximkatz.com/",
        artifacts_dir="artifacts",
        headless=True,
        token="token",
        default_chat_ids_raw=None,
        scrape_func=_fake_scrape,
        chart_func=lambda **kwargs: _realistic_chart_result(kwargs["session"], Path("chart-2.png")),
        send_message_func=_fake_send,
    )

    assert first.status == "updated"
    assert second.status == "no_change"
    assert second.chart_id is None
    assert sent == ["1001"]


def _realistic_chart_result(session: Session, chart_path: Path) -> ChartGenerationResult:
    chart_path.write_bytes(b"png")
    chart = GeneratedChart(
        chart_type=LINE_CHART_TYPE,
        chart_date=datetime(2026, 3, 29, tzinfo=timezone.utc).date(),
        source_name="maximkatz",
        range_start_date=datetime(2026, 3, 29, tzinfo=timezone.utc).date(),
        range_end_date=datetime(2026, 3, 29, tzinfo=timezone.utc).date(),
        range_days=1,
        file_path=str(chart_path),
    )
    session.add(chart)
    session.commit()
    session.refresh(chart)
    return ChartGenerationResult(
        output_path=str(chart_path),
        source_name="maximkatz",
        start_date=datetime(2026, 3, 29, tzinfo=timezone.utc).date(),
        end_date=datetime(2026, 3, 29, tzinfo=timezone.utc).date(),
        vpn_count=2,
        day_count=1,
        chart_id=chart.id,
    )


def test_hourly_sync_updated_sends_notifications_and_diff() -> None:
    session_factory = _session_factory()
    scrape_calls = [
        _make_scrape_result(table_hash="hash-1", score_a=30, score_b=20),
        _make_scrape_result(table_hash="hash-2", score_a=31, score_b=20),
    ]

    def _fake_scrape(**_: object) -> ScrapeResult:
        return scrape_calls.pop(0)

    sent_messages: list[str] = []

    async def _fake_send(**kwargs: str) -> None:
        sent_messages.append(kwargs["text"])

    with session_factory() as session:
        session.add(TelegramChat(chat_id="1001", chat_type="private", title=None, is_active=True))
        session.commit()

    run_hourly_sync_job(
        session_factory=session_factory,
        source_name="maximkatz",
        source_url="https://vpn.maximkatz.com/",
        artifacts_dir="artifacts",
        headless=True,
        token="token",
        default_chat_ids_raw=None,
        scrape_func=_fake_scrape,
        chart_func=lambda **kwargs: _realistic_chart_result(kwargs["session"], Path("chart-3.png")),
        send_message_func=_fake_send,
    )
    updated = run_hourly_sync_job(
        session_factory=session_factory,
        source_name="maximkatz",
        source_url="https://vpn.maximkatz.com/",
        artifacts_dir="artifacts",
        headless=True,
        token="token",
        default_chat_ids_raw=None,
        scrape_func=_fake_scrape,
        chart_func=lambda **kwargs: _realistic_chart_result(kwargs["session"], Path("chart-4.png")),
        send_message_func=_fake_send,
    )

    assert updated.status == "updated"
    assert updated.changed_count == 1
    assert updated.new_count == 0
    assert updated.removed_count == 0
    assert updated.notified_count == 1
    assert any("Изменения: changed=1, new=0, removed=0" in text for text in sent_messages)
