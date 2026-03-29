from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from vpn_rating_watcher.db.base import Base
from vpn_rating_watcher.db.models import Snapshot, VpnSnapshotResult
from vpn_rating_watcher.db.persistence import get_latest_snapshot_summary
from vpn_rating_watcher.importers.csv_backfill import (
    CSV_BACKFILL_SOURCE_NAME,
    CsvImportError,
    import_csv_backfill,
    parse_csv_backfill,
)


def _db_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def test_parse_csv_groups_rows_into_snapshot_per_date(tmp_path: Path) -> None:
    csv_file = tmp_path / "history.csv"
    csv_file.write_text(
        "\n".join(
            [
                "snapshot_date,vpn_name,checked_at_raw,result_raw,price_raw,traffic_raw,devices_raw,details_url",
                "2024-05-20,VPN Alpha,20.05.2024 12:00,34/36,€3.49/month,Unlimited,10,https://vpn.maximkatz.com/vpn/alpha",
                "2024-05-20,VPN Beta,20.05.2024 12:00,31 / 36,$4.99/month,100 GB,5,https://vpn.maximkatz.com/vpn/beta",
                "2024-06-03,VPN Alpha,03.06.2024 12:00,35/36,€3.49/month,Unlimited,10,https://vpn.maximkatz.com/vpn/alpha",
            ]
        ),
        encoding="utf-8",
    )

    scrape_results = parse_csv_backfill(csv_file)

    assert len(scrape_results) == 2
    assert scrape_results[0].row_count == 2
    assert scrape_results[0].rows[0].rank_position == 1
    assert scrape_results[0].rows[1].rank_position == 2
    assert scrape_results[0].rows[1].score == 31
    assert scrape_results[0].rows[1].score_max == 36
    assert scrape_results[0].rows[1].score_pct == pytest.approx(0.861111, rel=0, abs=1e-6)


def test_import_csv_is_idempotent_and_latest_snapshot_queryable(tmp_path: Path) -> None:
    csv_file = tmp_path / "history.csv"
    csv_file.write_text(
        "\n".join(
            [
                "snapshot_date,vpn_name,checked_at_raw,result_raw,price_raw,traffic_raw,devices_raw,details_url",
                "2024-05-20,VPN Alpha,20.05.2024 12:00,34/36,€3.49/month,Unlimited,10,https://vpn.maximkatz.com/vpn/alpha",
                "2024-06-03,VPN Alpha,03.06.2024 12:00,35/36,€3.49/month,Unlimited,10,https://vpn.maximkatz.com/vpn/alpha",
            ]
        ),
        encoding="utf-8",
    )

    with _db_session() as session:
        first = import_csv_backfill(session=session, path=csv_file)
        second = import_csv_backfill(session=session, path=csv_file)

        assert first.created_snapshots == 2
        assert first.skipped_snapshots == 0
        assert second.created_snapshots == 0
        assert second.skipped_snapshots == 2

        snapshot_count = session.execute(select(func.count(Snapshot.id))).scalar_one()
        row_count = session.execute(select(func.count(VpnSnapshotResult.id))).scalar_one()
        assert snapshot_count == 2
        assert row_count == 2

        latest = get_latest_snapshot_summary(session=session, source_name=CSV_BACKFILL_SOURCE_NAME)
        assert latest is not None
        assert latest.row_count == 1


def test_import_csv_returns_friendly_validation_error(tmp_path: Path) -> None:
    csv_file = tmp_path / "bad.csv"
    csv_file.write_text(
        "\n".join(
            [
                "snapshot_date,vpn_name,checked_at_raw,result_raw",
                "2024-05-20,VPN Alpha,20.05.2024 12:00,bad-value",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(CsvImportError, match="Row 2"):
        parse_csv_backfill(csv_file)
