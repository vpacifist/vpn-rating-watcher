from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from vpn_rating_watcher.charts.service import (
    CHART_MODE_MEDIAN_3D,
    ChartRegenerationMetadata,
    DailyScoreRow,
    _apply_rolling_median_3d,
    _compute_label_positions,
    _effective_chart_dates,
    _matrix_from_rows,
    get_max_point_date,
    query_daily_aggregated_scores,
    query_chart_scores,
    regenerate_chart_to_temp_file,
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


def test_query_daily_aggregated_scores_uses_daily_average_for_two_values() -> None:
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

        rows = query_daily_aggregated_scores(
            session=session,
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 1),
            source_name="maximkatz",
        )

        assert len(rows) == 1
        assert rows[0].score == 32.5


def test_apply_rolling_median_3d_window_with_single_value() -> None:
    rows = [
        DailyScoreRow(vpn_name="VPN A", point_date=date(2026, 3, 1), score=30.0),
    ]

    smoothed = _apply_rolling_median_3d(rows)

    assert len(smoothed) == 1
    assert smoothed[0].score == 30.0


def test_apply_rolling_median_3d_window_with_two_values_uses_average() -> None:
    rows = [
        DailyScoreRow(vpn_name="VPN A", point_date=date(2026, 3, 1), score=30.0),
        DailyScoreRow(vpn_name="VPN A", point_date=date(2026, 3, 2), score=36.0),
    ]

    smoothed = _apply_rolling_median_3d(rows)

    assert [row.score for row in smoothed] == [30.0, 33.0]


def test_apply_rolling_median_3d_window_with_three_values_uses_median() -> None:
    rows = [
        DailyScoreRow(vpn_name="VPN A", point_date=date(2026, 3, 1), score=30.0),
        DailyScoreRow(vpn_name="VPN A", point_date=date(2026, 3, 2), score=10.0),
        DailyScoreRow(vpn_name="VPN A", point_date=date(2026, 3, 3), score=35.0),
    ]

    smoothed = _apply_rolling_median_3d(rows)

    assert [row.score for row in smoothed] == [30.0, 20.0, 30.0]


def test_query_daily_aggregated_scores_groups_by_checked_at_date() -> None:
    with _session() as session:
        vpn = Vpn(name="VPN A", normalized_name="vpn a")
        session.add(vpn)
        session.flush()

        snapshot = Snapshot(
            source_name="maximkatz",
            source_url="https://vpn.maximkatz.com/",
            fetched_at=datetime(2026, 3, 30, 8, 0, tzinfo=timezone.utc),
            content_hash="hash-checked",
            raw_payload_json={},
        )
        session.add(snapshot)
        session.flush()

        session.add(
            VpnSnapshotResult(
                snapshot_id=snapshot.id,
                vpn_id=vpn.id,
                rank_position=1,
                checked_at=datetime(2026, 3, 29, 23, 30, tzinfo=timezone.utc),
                checked_at_raw="29.03.2026 23:30",
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

        rows = query_daily_aggregated_scores(
            session=session,
            start_date=date(2026, 3, 29),
            end_date=date(2026, 3, 29),
            source_name="maximkatz",
        )

        assert len(rows) == 1
        assert rows[0].point_date == date(2026, 3, 29)


def test_query_daily_aggregated_scores_falls_back_to_fetched_at_when_checked_at_missing() -> None:
    with _session() as session:
        vpn = Vpn(name="VPN A", normalized_name="vpn a")
        session.add(vpn)
        session.flush()

        snapshot = Snapshot(
            source_name="maximkatz",
            source_url="https://vpn.maximkatz.com/",
            fetched_at=datetime(2026, 3, 30, 8, 0, tzinfo=timezone.utc),
            content_hash="hash-fallback",
            raw_payload_json={},
        )
        session.add(snapshot)
        session.flush()

        session.add(
            VpnSnapshotResult(
                snapshot_id=snapshot.id,
                vpn_id=vpn.id,
                rank_position=1,
                checked_at=None,
                checked_at_raw=None,
                result_raw="33/36",
                score=33,
                score_max=36,
                score_pct=33 / 36,
                price_raw=None,
                traffic_raw=None,
                devices_raw=None,
                details_url=None,
            )
        )
        session.commit()

        rows = query_daily_aggregated_scores(
            session=session,
            start_date=date(2026, 3, 30),
            end_date=date(2026, 3, 30),
            source_name="maximkatz",
        )

        assert len(rows) == 1
        assert rows[0].point_date == date(2026, 3, 30)


def test_query_daily_aggregated_scores_filters_source_name() -> None:
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

        live_rows = query_daily_aggregated_scores(
            session=session,
            start_date=date(2026, 3, 2),
            end_date=date(2026, 3, 2),
            source_name="maximkatz",
        )
        mixed_rows = query_daily_aggregated_scores(
            session=session,
            start_date=date(2026, 3, 2),
            end_date=date(2026, 3, 2),
            source_name="mixed",
        )

        assert live_rows[0].score == 34
        assert mixed_rows[0].score == 34


def test_main_source_chart_range_includes_csv_backfill_and_live_history() -> None:
    with _session() as session:
        vpn = Vpn(name="VPN A", normalized_name="vpn a")
        session.add(vpn)
        session.flush()

        backfill = Snapshot(
            source_name="csv_backfill",
            source_url="https://local.import/csv-backfill",
            fetched_at=datetime(2026, 1, 10, 8, 0, tzinfo=timezone.utc),
            content_hash="csv-hash-old",
            raw_payload_json={},
        )
        live = Snapshot(
            source_name="maximkatz",
            source_url="https://vpn.maximkatz.com/",
            fetched_at=datetime(2026, 3, 20, 8, 0, tzinfo=timezone.utc),
            content_hash="live-hash-new",
            raw_payload_json={},
        )
        session.add_all([backfill, live])
        session.flush()

        session.add_all(
            [
                VpnSnapshotResult(
                    snapshot_id=backfill.id,
                    vpn_id=vpn.id,
                    rank_position=1,
                    checked_at=datetime(2026, 1, 10, 8, 0, tzinfo=timezone.utc),
                    checked_at_raw="10.01.2026 08:00",
                    result_raw="28/36",
                    score=28,
                    score_max=36,
                    score_pct=28 / 36,
                    price_raw=None,
                    traffic_raw=None,
                    devices_raw=None,
                    details_url=None,
                ),
                VpnSnapshotResult(
                    snapshot_id=live.id,
                    vpn_id=vpn.id,
                    rank_position=1,
                    checked_at=datetime(2026, 3, 20, 8, 0, tzinfo=timezone.utc),
                    checked_at_raw="20.03.2026 08:00",
                    result_raw="33/36",
                    score=33,
                    score_max=36,
                    score_pct=33 / 36,
                    price_raw=None,
                    traffic_raw=None,
                    devices_raw=None,
                    details_url=None,
                ),
            ]
        )
        session.commit()

        rows = query_daily_aggregated_scores(
            session=session,
            start_date=date(2026, 1, 10),
            end_date=date(2026, 3, 20),
            source_name="maximkatz",
        )
        dates = _effective_chart_dates(
            rows=rows,
            fallback_start=date(2026, 1, 10),
            fallback_end=date(2026, 3, 20),
        )

        assert rows[0].point_date == date(2026, 1, 10)
        assert rows[-1].point_date == date(2026, 3, 20)
        assert [row.point_date for row in rows] == [
            date(2026, 1, 10),
            date(2026, 1, 11),
            date(2026, 1, 12),
            date(2026, 1, 13),
            date(2026, 3, 20),
        ]
        assert dates[0] == date(2026, 1, 10)
        assert dates[-1] == date(2026, 3, 20)


def test_query_daily_aggregated_scores_uses_median_for_three_or_more_values() -> None:
    with _session() as session:
        vpn = Vpn(name="VPN A", normalized_name="vpn a")
        session.add(vpn)
        session.flush()

        snapshots = [
            Snapshot(
                source_name="maximkatz",
                source_url="https://vpn.maximkatz.com/",
                fetched_at=datetime(2026, 3, 5, hour, 0, tzinfo=timezone.utc),
                content_hash=f"hash-{hour}",
                raw_payload_json={},
            )
            for hour in (8, 12, 16, 20)
        ]
        session.add_all(snapshots)
        session.flush()

        for snapshot, score in zip(snapshots, [10, 36, 20, 30], strict=True):
            session.add(
                VpnSnapshotResult(
                    snapshot_id=snapshot.id,
                    vpn_id=vpn.id,
                    rank_position=1,
                    checked_at=None,
                    checked_at_raw=None,
                    result_raw=f"{score}/36",
                    score=score,
                    score_max=36,
                    score_pct=score / 36,
                    price_raw=None,
                    traffic_raw=None,
                    devices_raw=None,
                    details_url=None,
                )
            )
        session.commit()

        rows = query_daily_aggregated_scores(
            session=session,
            start_date=date(2026, 3, 5),
            end_date=date(2026, 3, 5),
            source_name="maximkatz",
        )

        assert len(rows) == 1
        assert rows[0].score == 25


def test_query_daily_aggregated_scores_carries_value_for_up_to_three_days() -> None:
    with _session() as session:
        vpn = Vpn(name="VPN A", normalized_name="vpn a")
        session.add(vpn)
        session.flush()

        snapshot = Snapshot(
            source_name="maximkatz",
            source_url="https://vpn.maximkatz.com/",
            fetched_at=datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc),
            content_hash="hash-only",
            raw_payload_json={},
        )
        session.add(snapshot)
        session.flush()

        session.add(
            VpnSnapshotResult(
                snapshot_id=snapshot.id,
                vpn_id=vpn.id,
                rank_position=1,
                checked_at=None,
                checked_at_raw=None,
                result_raw="10/36",
                score=10,
                score_max=36,
                score_pct=10 / 36,
                price_raw=None,
                traffic_raw=None,
                devices_raw=None,
                details_url=None,
            )
        )
        session.commit()

        rows = query_daily_aggregated_scores(
            session=session,
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 4),
            source_name="maximkatz",
        )

        assert [row.point_date for row in rows] == [
            date(2026, 3, 1),
            date(2026, 3, 2),
            date(2026, 3, 3),
            date(2026, 3, 4),
        ]
        assert [row.score for row in rows] == [10, 10, 10, 10]


def test_query_daily_aggregated_scores_does_not_carry_value_on_fourth_day() -> None:
    with _session() as session:
        vpn = Vpn(name="VPN A", normalized_name="vpn a")
        session.add(vpn)
        session.flush()

        snapshot = Snapshot(
            source_name="maximkatz",
            source_url="https://vpn.maximkatz.com/",
            fetched_at=datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc),
            content_hash="hash-only",
            raw_payload_json={},
        )
        session.add(snapshot)
        session.flush()

        session.add(
            VpnSnapshotResult(
                snapshot_id=snapshot.id,
                vpn_id=vpn.id,
                rank_position=1,
                checked_at=None,
                checked_at_raw=None,
                result_raw="10/36",
                score=10,
                score_max=36,
                score_pct=10 / 36,
                price_raw=None,
                traffic_raw=None,
                devices_raw=None,
                details_url=None,
            )
        )
        session.commit()

        rows = query_daily_aggregated_scores(
            session=session,
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 5),
            source_name="maximkatz",
        )

        assert [row.point_date for row in rows] == [
            date(2026, 3, 1),
            date(2026, 3, 2),
            date(2026, 3, 3),
            date(2026, 3, 4),
        ]
        assert all(row.point_date != date(2026, 3, 5) for row in rows)


def test_query_chart_scores_median_3d_uses_only_current_and_past_days() -> None:
    with _session() as session:
        vpn = Vpn(name="VPN A", normalized_name="vpn a")
        session.add(vpn)
        session.flush()

        for day, score in (
            (date(2026, 3, 1), 9),
            (date(2026, 3, 2), 36),
            (date(2026, 3, 3), 3),
        ):
            snapshot = Snapshot(
                source_name="maximkatz",
                source_url="https://vpn.maximkatz.com/",
                fetched_at=datetime(day.year, day.month, day.day, 8, 0, tzinfo=timezone.utc),
                content_hash=f"hash-{day.isoformat()}",
                raw_payload_json={},
            )
            session.add(snapshot)
            session.flush()
            session.add(
                VpnSnapshotResult(
                    snapshot_id=snapshot.id,
                    vpn_id=vpn.id,
                    rank_position=1,
                    checked_at=None,
                    checked_at_raw=None,
                    result_raw=f"{score}/36",
                    score=score,
                    score_max=36,
                    score_pct=score / 36,
                    price_raw=None,
                    traffic_raw=None,
                    devices_raw=None,
                    details_url=None,
                )
            )
        session.commit()

        rows = query_chart_scores(
            session=session,
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 3),
            source_name="maximkatz",
            mode=CHART_MODE_MEDIAN_3D,
        )

        assert [row.score for row in rows] == [9.0, 22.5, 9.0]


def test_query_daily_aggregated_scores_binds_date_params_for_postgresql() -> None:
    session = _CapturingSession()
    start = date(2026, 3, 1)
    end = date(2026, 3, 30)

    rows = query_daily_aggregated_scores(
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


def test_get_max_point_date_uses_checked_at_date() -> None:
    with _session() as session:
        vpn = Vpn(name="VPN A", normalized_name="vpn a")
        session.add(vpn)
        session.flush()

        snapshot = Snapshot(
            source_name="maximkatz",
            source_url="https://vpn.maximkatz.com/",
            fetched_at=datetime(2026, 3, 30, 8, 0, tzinfo=timezone.utc),
            content_hash="hash-max-date",
            raw_payload_json={},
        )
        session.add(snapshot)
        session.flush()

        session.add(
            VpnSnapshotResult(
                snapshot_id=snapshot.id,
                vpn_id=vpn.id,
                rank_position=1,
                checked_at=datetime(2026, 3, 29, 23, 30, tzinfo=timezone.utc),
                checked_at_raw="29.03.2026 23:30",
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

        assert get_max_point_date(session=session) == date(2026, 3, 29)


def test_effective_chart_dates_start_at_first_data_date() -> None:
    rows = [
        DailyScoreRow(vpn_name="VPN A", point_date=date(2026, 3, 10), score=30),
        DailyScoreRow(vpn_name="VPN A", point_date=date(2026, 3, 12), score=31),
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
        DailyScoreRow(vpn_name="VPN A", point_date=date(2026, 3, 10), score=30),
        DailyScoreRow(vpn_name="VPN A", point_date=date(2026, 3, 12), score=31),
        DailyScoreRow(vpn_name="VPN B", point_date=date(2026, 3, 10), score=35),
        DailyScoreRow(vpn_name="VPN B", point_date=date(2026, 3, 11), score=36),
        DailyScoreRow(vpn_name="VPN B", point_date=date(2026, 3, 12), score=34),
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


def test_regenerate_chart_to_temp_file_uses_metadata_range_and_source() -> None:
    with (
        _session() as session,
        patch("vpn_rating_watcher.charts.service.query_daily_aggregated_scores") as query_rows,
        patch("vpn_rating_watcher.charts.service._render_line_chart") as render_chart,
    ):
        query_rows.return_value = []
        output = regenerate_chart_to_temp_file(
            session=session,
            metadata=ChartRegenerationMetadata(
                chart_type="historical_line_chart",
                source_name="mixed",
                range_start_date=date(2026, 3, 10),
                range_end_date=date(2026, 3, 15),
                range_days=6,
                chart_date=date(2026, 3, 15),
                file_path=Path("artifacts/charts/linechart_mixed_2026-03-10_2026-03-15.png"),
            ),
        )

    assert output.exists()
    assert query_rows.call_args is not None
    assert query_rows.call_args.kwargs["source_name"] == "mixed"
    assert query_rows.call_args.kwargs["start_date"] == date(2026, 3, 10)
    assert query_rows.call_args.kwargs["end_date"] == date(2026, 3, 15)
    render_chart.assert_called_once()
    output.unlink(missing_ok=True)
