from __future__ import annotations

from datetime import date, datetime, timezone

from vpn_rating_watcher.charts.service import DailyScoreRow, color_for_vpn


def build_dates(start_date: date, end_date: date) -> list[date]:
    days: list[date] = []
    current = start_date
    while current <= end_date:
        days.append(current)
        current = date.fromordinal(current.toordinal() + 1)
    return days


def build_chart_payload(
    *,
    rows: list[DailyScoreRow],
    start_date: date,
    end_date: date,
    source_name: str,
    top_n: int | None,
) -> dict:
    if rows:
        first_data_date = min(row.point_date for row in rows)
        if first_data_date > start_date:
            start_date = first_data_date

    days = build_dates(start_date=start_date, end_date=end_date)
    labels = [day.isoformat() for day in days]

    points_by_vpn: dict[str, dict[date, int]] = {}
    for row in rows:
        vpn_points = points_by_vpn.setdefault(row.vpn_name, {})
        vpn_points[row.point_date] = row.score

    ordered_vpns = sorted(
        points_by_vpn,
        key=lambda vpn_name: points_by_vpn[vpn_name].get(days[-1], -1),
        reverse=True,
    )
    if top_n is not None:
        ordered_vpns = ordered_vpns[:top_n]

    series = [
        {
            "name": vpn_name,
            "values": [points_by_vpn[vpn_name].get(day) for day in days],
            "color": color_for_vpn(vpn_name),
        }
        for vpn_name in ordered_vpns
    ]

    return {
        "source_name": source_name,
        "date_range": {
            "from": start_date.isoformat(),
            "to": end_date.isoformat(),
            "days": len(days),
        },
        "labels": labels,
        "series": series,
        "updated_at_utc": datetime.now(tz=timezone.utc).isoformat(),
    }
