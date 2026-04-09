from __future__ import annotations

from datetime import date, datetime, timezone

from vpn_rating_watcher.charts.service import DailyScoreRow, select_chart_series


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

    selected_series = select_chart_series(rows=rows, dates=days, top_n=top_n)
    series = [
        {
            "name": item.name,
            "values": item.values,
            "color": item.color,
        }
        for item in selected_series
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
