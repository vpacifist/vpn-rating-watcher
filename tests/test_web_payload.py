from __future__ import annotations

from datetime import date

from vpn_rating_watcher.charts.service import DailyScoreRow
from vpn_rating_watcher.web.payload import build_chart_payload


def test_build_chart_payload_builds_dense_date_grid_with_nulls() -> None:
    rows = [
        DailyScoreRow(vpn_name="VPN A", point_date=date(2026, 3, 1), score=30),
        DailyScoreRow(vpn_name="VPN A", point_date=date(2026, 3, 3), score=32),
        DailyScoreRow(vpn_name="VPN B", point_date=date(2026, 3, 2), score=28),
    ]

    payload = build_chart_payload(
        rows=rows,
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 3),
        source_name="maximkatz",
        source_timezone="UTC",
        top_n=None,
    )

    assert payload["labels"] == ["2026-03-01", "2026-03-02", "2026-03-03"]
    vpn_a = next(item for item in payload["series"] if item["name"] == "VPN A")
    vpn_b = next(item for item in payload["series"] if item["name"] == "VPN B")

    assert vpn_a["values"] == [30, None, 32]
    assert vpn_b["values"] == [None, 28, None]


def test_build_chart_payload_trims_leading_empty_dates() -> None:
    rows = [
        DailyScoreRow(vpn_name="VPN A", point_date=date(2026, 3, 3), score=30),
        DailyScoreRow(vpn_name="VPN B", point_date=date(2026, 3, 4), score=28),
    ]

    payload = build_chart_payload(
        rows=rows,
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 4),
        source_name="maximkatz",
        source_timezone="UTC",
        top_n=None,
    )

    assert payload["labels"] == ["2026-03-03", "2026-03-04"]
    assert payload["date_range"]["from"] == "2026-03-03"
    assert payload["date_range"]["days"] == 2


def test_build_chart_payload_applies_top_n() -> None:
    rows = [
        DailyScoreRow(vpn_name="VPN A", point_date=date(2026, 3, 2), score=20),
        DailyScoreRow(vpn_name="VPN B", point_date=date(2026, 3, 2), score=35),
        DailyScoreRow(vpn_name="VPN C", point_date=date(2026, 3, 2), score=10),
    ]

    payload = build_chart_payload(
        rows=rows,
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 2),
        source_name="maximkatz",
        source_timezone="UTC",
        top_n=2,
    )

    assert [item["name"] for item in payload["series"]] == ["VPN B", "VPN A"]


def test_build_chart_payload_includes_brand_color() -> None:
    rows = [
        DailyScoreRow(vpn_name="VPN Liberty", point_date=date(2026, 3, 2), score=30),
    ]

    payload = build_chart_payload(
        rows=rows,
        start_date=date(2026, 3, 2),
        end_date=date(2026, 3, 2),
        source_name="maximkatz",
        source_timezone="UTC",
        top_n=None,
    )

    assert payload["series"][0]["color"] == "#ba0300"
    assert payload["source_timezone"] == "UTC"
