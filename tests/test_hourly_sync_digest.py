from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from vpn_rating_watcher.bot.service import TelegramBotService
from vpn_rating_watcher.charts.service import ChartGenerationResult
from vpn_rating_watcher.db.base import Base
from vpn_rating_watcher.db.models import TelegramChat
from vpn_rating_watcher.jobs.hourly_sync import run_hourly_sync_job
from vpn_rating_watcher.scraper.models import NormalizedRow, ScrapeResult


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def _scrape_result(*, scraped_at: datetime, table_hash: str, score: int) -> ScrapeResult:
    return ScrapeResult(
        source_url="https://vpn.maximkatz.com/",
        scraped_at_utc=scraped_at.isoformat(),
        table_hash=table_hash,
        row_count=1,
        artifacts_dir="artifacts/test",
        rows=[
            NormalizedRow(
                rank_position=1,
                vpn_name="AlphaVPN",
                checked_at_raw=scraped_at.strftime("%Y-%m-%d %H:%M"),
                result_raw=f"{score}/36",
                score=score,
                score_max=36,
                score_pct=score / 36,
                price_raw=None,
                traffic_raw=None,
                devices_raw=None,
                details_url=None,
            )
        ],
    )


def _chart_result() -> ChartGenerationResult:
    return ChartGenerationResult(
        output_path="artifacts/charts/test.png",
        source_name="maximkatz",
        start_date=date(2026, 4, 24),
        end_date=date(2026, 4, 24),
        vpn_count=1,
        day_count=1,
        chart_id=99,
    )


@dataclass
class _ScrapeSequence:
    values: list[ScrapeResult]

    def __post_init__(self) -> None:
        self._iterator: Iterator[ScrapeResult] = iter(self.values)

    def __call__(self, **_: object) -> ScrapeResult:
        return next(self._iterator)


async def _capture_send(
    *,
    token: str,
    chat_id: str,
    text: str,
) -> None:
    _ = token
    _ = chat_id
    MESSAGES.append(text)


MESSAGES: list[str] = []


def test_hourly_sync_sends_immediately_for_hourly_chat() -> None:
    session_factory = _session_factory()
    service = TelegramBotService(session_factory=session_factory)
    service.set_chat_subscription(
        chat_id="100",
        chat_type="private",
        title=None,
        is_active=True,
    )

    start = datetime(2026, 4, 24, 10, 0, tzinfo=timezone.utc)
    scrape_sequence = _ScrapeSequence(
        [_scrape_result(scraped_at=start, table_hash="hash-1", score=30)]
    )
    MESSAGES.clear()

    result = run_hourly_sync_job(
        session_factory=session_factory,
        source_name="maximkatz",
        source_url="https://vpn.maximkatz.com/",
        artifacts_dir="artifacts",
        headless=True,
        token="token",
        default_chat_ids_raw=None,
        scrape_func=scrape_sequence,
        chart_func=lambda **_: _chart_result(),
        send_message_func=_capture_send,
    )

    assert result.notified_count == 1
    assert len(MESSAGES) == 1
    assert "последний 1 час" in MESSAGES[0]


def test_hourly_sync_accumulates_digest_for_four_hour_chat() -> None:
    session_factory = _session_factory()
    service = TelegramBotService(session_factory=session_factory)
    service.set_chat_subscription(
        chat_id="200",
        chat_type="private",
        title=None,
        is_active=True,
    )
    service.set_chat_update_interval(
        chat_id="200",
        chat_type="private",
        title=None,
        update_interval_hours=4,
    )

    start = datetime(2026, 4, 24, 10, 0, tzinfo=timezone.utc)
    scrape_sequence = _ScrapeSequence(
        [
            _scrape_result(scraped_at=start, table_hash="hash-1", score=30),
            _scrape_result(scraped_at=start + timedelta(hours=1), table_hash="hash-2", score=31),
            _scrape_result(scraped_at=start + timedelta(hours=2), table_hash="hash-3", score=32),
            _scrape_result(scraped_at=start + timedelta(hours=4), table_hash="hash-4", score=33),
        ]
    )
    MESSAGES.clear()

    for _ in range(4):
        run_hourly_sync_job(
            session_factory=session_factory,
            source_name="maximkatz",
            source_url="https://vpn.maximkatz.com/",
            artifacts_dir="artifacts",
            headless=True,
            token="token",
            default_chat_ids_raw=None,
            scrape_func=scrape_sequence,
            chart_func=lambda **_: _chart_result(),
            send_message_func=_capture_send,
        )

    with session_factory() as session:
        chat = session.query(TelegramChat).filter(TelegramChat.chat_id == "200").one()
        assert chat.last_notified_at is not None

    assert len(MESSAGES) == 1
    assert "последние 4ч" in MESSAGES[0]
    assert "Новых snapshot в обзоре: 4" in MESSAGES[0]
    assert "changed=1" in MESSAGES[0]
