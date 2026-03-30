from __future__ import annotations

from datetime import date, datetime, timezone

import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from vpn_rating_watcher.charts.service import (
    DailyScoreRow,
    _compute_label_positions,
    _effective_chart_dates,
    _matrix_from_rows,
    query_daily_latest_scores,
)
from vpn_rating_watcher.db.base import Base
from vpn_rating_watcher.db.models import Snapshot, Vpn, VpnSnapshotResult


class _ExecuteResult:
    def all(self) -> list[tuple[str, str, int]]:
        return []


class _CapturingSession:
    def __init__(self) -> None:
        self.stmt = None

    def execute(self, stmt):  # noqa: ANN001
        self.stmt = stmt
        return _ExecuteResult()


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def test_query_daily_latest_scores_uses_latest_snapshot_per_day() -> None:
    with _session() as session:
        vpn = Vpn(name="VPN A", normalized_name="vpn a")
        session.add(vpn)
        session.flush()

        morning = Snapshot(
            source_name="maximkatz",
            source_url="https://vpn.maximkatz.com/",
            fetched_at=datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc),
            content_hash="hash-morning",
            raw_payload_json={},
        )
        evening = Snapshot(
            source_name="maximkatz",
            source_url="https://vpn.maximkatz.com/",
            fetched_at=datetime(2026, 3, 1, 20, 0, tzinfo=timezone.utc),
            content_hash="hash-evening",
            raw_payload_json={},
        )
        session.add_all([morning, evening])
        session.flush()

        session.add_all(
            [
                VpnSnapshotResult(
                    snapshot_id=morning.id,
                    vpn_id=vpn.id,
                    rank_position=1,
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
                ),
                VpnSnapshotResult(
                    snapshot_id=evening.id,
                    vpn_id=vpn.id,
                    rank_position=1,
                    checked_at=None,
                    checked_at_raw=None,
                    result_raw="35/36",
                    score=35,
                    score_max=36,
                    score_pct=35 / 36,
                    price_raw=None,
                    traffic_raw=None,
                    devices_raw=None,
                    details_url=None,
                ),
            ]
        )
        session.commit()

        rows = query_daily_latest_scores(
            session=session,
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 1),
            source_name="maximkatz",
        )

        assert len(rows) == 1
        assert rows[0].score == 35


def test_query_daily_latest_scores_filters_source_name() -> None:
    with _session() as session:
        vpn = Vpn(name="VPN A", normalized_name="vpn a")
        session.add(vpn)
        session.flush()

        live = Snapshot(
            source_name="maximkatz",
            source_url="https://vpn.maximkatz.com/",
            fetched_at=datetime(2026, 3, 2, 10, 0, tzinfo=timezone.utc),
            content_hash="live-hash",
            raw_payload_json={},
        )
        backfill = Snapshot(
            source_name="csv_backfill",
            source_url="https://local.import/csv-backfill",
            fetched_at=datetime(2026, 3, 2, 11, 0, tzinfo=timezone.utc),
            content_hash="csv-hash",
            raw_payload_json={},
        )
        session.add_all([live, backfill])
        session.flush()

        session.add_all(
            [
                VpnSnapshotResult(
                    snapshot_id=live.id,
                    vpn_id=vpn.id,
                    rank_position=1,
                    checked_at=None,
                    checked_at_raw=None,
                    result_raw="32/36",
                    score=32,
                    score_max=36,
                    score_pct=32 / 36,
                    price_raw=None,
                    traffic_raw=None,
                    devices_raw=None,
                    details_url=None,
                ),
                VpnSnapshotResult(
                    snapshot_id=backfill.id,
                    vpn_id=vpn.id,
                    rank_position=1,
                    checked_at=None,
                    checked_at_raw=None,
                    result_raw="36/36",
                    score=36,
                    score_max=36,
                    score_pct=1,
                    price_raw=None,
                    traffic_raw=None,
                    devices_raw=None,
                    details_url=None,
                ),
            ]
        )
        session.commit()

        live_rows = query_daily_latest_scores(
            session=session,
            start_date=date(2026, 3, 2),
            end_date=date(2026, 3, 2),
            source_name="maximkatz",
        )
        mixed_rows = query_daily_latest_scores(
            session=session,
            start_date=date(2026, 3, 2),
            end_date=date(2026, 3, 2),
            source_name="mixed",
        )

        assert live_rows[0].score == 32
        assert mixed_rows[0].score == 36


def test_query_daily_latest_scores_binds_date_params_for_postgresql() -> None:
    session = _CapturingSession()
    start = date(2026, 3, 1)
    end = date(2026, 3, 30)

    rows = query_daily_latest_scores(
        session=session,
        start_date=start,
        end_date=end,
        source_name="mixed",
    )
    assert rows == []
    assert session.stmt is not None

    compiled = session.stmt.compile(dialect=postgresql.dialect())
    date_params = [value for value in compiled.params.values() if isinstance(value, date)]

    assert start in date_params
    assert end in date_params
    assert start.isoformat() not in compiled.params.values()
    assert end.isoformat() not in compiled.params.values()


def test_effective_chart_dates_start_at_first_data_date() -> None:
    rows = [
        DailyScoreRow(vpn_name="VPN A", snapshot_date=date(2026, 3, 10), score=30),
        DailyScoreRow(vpn_name="VPN A", snapshot_date=date(2026, 3, 12), score=31),
    ]

    dates = _effective_chart_dates(
        rows=rows,
        fallback_start=date(2026, 3, 1),
        fallback_end=date(2026, 3, 30),
    )

    assert dates[0] == date(2026, 3, 10)
    assert dates[-1] == date(2026, 3, 12)


def test_matrix_from_rows_keeps_missing_dates_as_gaps() -> None:
    dates = [date(2026, 3, 10), date(2026, 3, 11), date(2026, 3, 12)]
    rows = [
        DailyScoreRow(vpn_name="VPN A", snapshot_date=date(2026, 3, 10), score=30),
        DailyScoreRow(vpn_name="VPN A", snapshot_date=date(2026, 3, 12), score=31),
        DailyScoreRow(vpn_name="VPN B", snapshot_date=date(2026, 3, 10), score=35),
        DailyScoreRow(vpn_name="VPN B", snapshot_date=date(2026, 3, 11), score=36),
        DailyScoreRow(vpn_name="VPN B", snapshot_date=date(2026, 3, 12), score=34),
    ]

    matrix, vpn_names = _matrix_from_rows(rows=rows, dates=dates, top_n=None)

    vpn_a_idx = vpn_names.index("VPN A")
    assert matrix[vpn_a_idx, 0] == 30
    assert np.isnan(matrix[vpn_a_idx, 1])
    assert matrix[vpn_a_idx, 2] == 31


def test_compute_label_positions_preserves_order_and_spacing() -> None:
    positions = _compute_label_positions(
        [30.0, 30.1, 30.2],
        lower=0.4,
        upper=36.6,
        min_gap=0.7,
    )

    assert positions[0] < positions[1] < positions[2]
    tolerance = 1e-9
    assert positions[1] - positions[0] >= 0.7 - tolerance
    assert positions[2] - positions[1] >= 0.7 - tolerance


def test_compute_label_positions_respects_bounds() -> None:
    positions = _compute_label_positions(
        [36.5, 36.8],
        lower=0.4,
        upper=36.6,
        min_gap=0.7,
    )

    assert positions[0] >= 0.4
    assert positions[1] <= 36.6
