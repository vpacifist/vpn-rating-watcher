from __future__ import annotations

from datetime import timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from vpn_rating_watcher.db.base import Base
from vpn_rating_watcher.db.models import Snapshot, Vpn, VpnSnapshotResult
from vpn_rating_watcher.db.persistence import get_latest_snapshot_summary, persist_scrape_result
from vpn_rating_watcher.scraper.models import NormalizedRow, ScrapeResult


def _sample_scrape_result(content_hash: str, score: int = 35) -> ScrapeResult:
    return ScrapeResult(
        source_url="https://vpn.maximkatz.com/",
        scraped_at_utc="2026-03-29T10:00:00+00:00",
        table_hash=content_hash,
        row_count=1,
        rows=[
            NormalizedRow(
                rank_position=1,
                vpn_name="vpn one",
                checked_at_raw="28.03.2026 15:00",
                result_raw=f"{score}/36",
                score=score,
                score_max=36,
                score_pct=round(score / 36, 6),
                details_url="https://vpn.maximkatz.com/vpn/one",
                metadata={},
            )
        ],
        artifacts_dir="artifacts/20260329T100000Z",
    )


def _db_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def test_persist_creates_snapshot_and_rows() -> None:
    with _db_session() as session:
        result = persist_scrape_result(
            session=session, scrape_result=_sample_scrape_result("hash-1")
        )

        assert result.status == "created"
        assert result.snapshot_id is not None
        assert result.inserted_vpn_count == 1
        assert result.inserted_result_count == 1

        assert len(session.scalars(select(Snapshot)).all()) == 1
        assert len(session.scalars(select(Vpn)).all()) == 1
        assert len(session.scalars(select(VpnSnapshotResult)).all()) == 1


def test_persist_is_idempotent_for_same_latest_hash() -> None:
    with _db_session() as session:
        first = persist_scrape_result(
            session=session, scrape_result=_sample_scrape_result("same-hash")
        )
        second = persist_scrape_result(
            session=session, scrape_result=_sample_scrape_result("same-hash")
        )

        assert first.status == "created"
        assert second.status == "no_change"

        snapshots = session.scalars(select(Snapshot)).all()
        results = session.scalars(select(VpnSnapshotResult)).all()
        vpns = session.scalars(select(Vpn)).all()

        assert len(snapshots) == 1
        assert len(results) == 1
        assert len(vpns) == 1


def test_latest_snapshot_summary_returns_latest_data() -> None:
    with _db_session() as session:
        persist_scrape_result(
            session=session, scrape_result=_sample_scrape_result("hash-1", score=35)
        )
        persist_scrape_result(
            session=session, scrape_result=_sample_scrape_result("hash-2", score=34)
        )

        summary = get_latest_snapshot_summary(session=session)
        assert summary is not None
        assert summary.content_hash == "hash-2"
        assert summary.row_count == 1
        assert summary.fetched_at.tzinfo == timezone.utc
