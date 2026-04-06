from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from sqlalchemy import Select, and_, desc, func, select
from sqlalchemy.orm import Session

from vpn_rating_watcher.db.models import GeneratedChart, Snapshot, Vpn, VpnSnapshotResult

matplotlib.use("Agg")

MAIN_LIVE_SOURCE_NAME = "maximkatz"
CSV_BACKFILL_SOURCE_NAME = "csv_backfill"
MIXED_SOURCE_NAME = "mixed"
LINE_CHART_TYPE = "historical_line_chart"

VPN_LINE_COLORS: dict[str, str] = {
    "vpn red shield": "#ff5b27",
    "papervpn": "#A0F249",
    "vpn liberty": "#ba0300",
    "blancvpn": "#3183ff",
    "vpn generator": "#A3D9F9",
    "amneziavpn": "#FBB26A",
    "durev vpn": "#00FF00",
    "наружу": "#FFD600",
    "tunnelbear": "#C08D4A",
}


@dataclass(slots=True)
class DailyScoreRow:
    vpn_name: str
    point_date: date
    score: int


@dataclass(slots=True)
class DateRange:
    start_date: date
    end_date: date


@dataclass(slots=True)
class ChartGenerationResult:
    output_path: str
    source_name: str
    start_date: date
    end_date: date
    vpn_count: int
    day_count: int
    chart_id: int


@dataclass(slots=True)
class ChartRegenerationMetadata:
    chart_type: str
    source_name: str | None
    range_start_date: date | None
    range_end_date: date | None
    range_days: int | None
    chart_date: date | None
    file_path: Path


def _source_names_for_chart(source_name: str) -> tuple[str, ...] | None:
    if source_name == MIXED_SOURCE_NAME:
        return None
    if source_name == MAIN_LIVE_SOURCE_NAME:
        return (MAIN_LIVE_SOURCE_NAME, CSV_BACKFILL_SOURCE_NAME)
    return (source_name,)


def _apply_source_filter(stmt: Select, *, source_name: str) -> Select:
    source_names = _source_names_for_chart(source_name)
    if source_names is None:
        return stmt
    if len(source_names) == 1:
        return stmt.where(Snapshot.source_name == source_names[0])
    return stmt.where(Snapshot.source_name.in_(source_names))


def _effective_row_date():
    """Return the chart grouping date for a row.

    Fallback behavior: when row-level checked_at is missing, fallback to Snapshot.fetched_at.
    """
    return func.coalesce(func.date(VpnSnapshotResult.checked_at), func.date(Snapshot.fetched_at))


def get_max_point_date(
    session: Session, source_name: str = MAIN_LIVE_SOURCE_NAME
) -> date | None:
    effective_row_date = _effective_row_date()
    stmt = select(func.max(effective_row_date)).select_from(VpnSnapshotResult).join(Snapshot)
    stmt = _apply_source_filter(stmt, source_name=source_name)
    raw_max = session.execute(stmt).scalar_one_or_none()
    if not raw_max:
        return None
    if isinstance(raw_max, date):
        return raw_max
    return date.fromisoformat(str(raw_max))


def resolve_date_range(
    session: Session,
    *,
    days: int | None,
    from_date: date | None,
    to_date: date | None,
    source_name: str,
) -> DateRange:
    if days is not None and (from_date is not None or to_date is not None):
        raise ValueError("Use either --days or --from/--to, not both")

    if days is not None:
        if days <= 0:
            raise ValueError("--days must be greater than zero")
        end_date = get_max_point_date(
            session=session, source_name=source_name
        ) or datetime.now(tz=timezone.utc).date()
        start_date = end_date - timedelta(days=days - 1)
        return DateRange(start_date=start_date, end_date=end_date)

    if from_date and to_date and from_date > to_date:
        raise ValueError("--from cannot be after --to")

    if from_date is None and to_date is None:
        return resolve_date_range(
            session=session,
            days=30,
            from_date=None,
            to_date=None,
            source_name=source_name,
        )

    if from_date is None:
        from_date = to_date
    if to_date is None:
        to_date = from_date

    return DateRange(start_date=from_date, end_date=to_date)


def query_daily_latest_scores(
    session: Session,
    *,
    start_date: date,
    end_date: date,
    source_name: str,
) -> list[DailyScoreRow]:
    effective_row_date = _effective_row_date()
    ranked = (
        select(
            Vpn.name.label("vpn_name"),
            effective_row_date.label("point_date"),
            VpnSnapshotResult.score.label("score"),
            func.row_number()
            .over(
                partition_by=(VpnSnapshotResult.vpn_id, effective_row_date),
                order_by=(desc(Snapshot.fetched_at), desc(Snapshot.id), desc(VpnSnapshotResult.id)),
            )
            .label("row_num"),
        )
        .select_from(VpnSnapshotResult)
        .join(Snapshot, Snapshot.id == VpnSnapshotResult.snapshot_id)
        .join(Vpn, Vpn.id == VpnSnapshotResult.vpn_id)
        .where(and_(effective_row_date >= start_date, effective_row_date <= end_date))
    )

    ranked = _apply_source_filter(ranked, source_name=source_name)

    ranked_subq = ranked.subquery()
    stmt: Select[tuple[str, str, int]] = (
        select(
            ranked_subq.c.vpn_name,
            ranked_subq.c.point_date,
            ranked_subq.c.score,
        )
        .where(ranked_subq.c.row_num == 1)
        .order_by(ranked_subq.c.vpn_name.asc(), ranked_subq.c.point_date.asc())
    )

    return [
        DailyScoreRow(
            vpn_name=vpn_name,
            point_date=(
                point_date
                if isinstance(point_date, date)
                else date.fromisoformat(str(point_date))
            ),
            score=score,
        )
        for vpn_name, point_date, score in session.execute(stmt).all()
    ]


def _build_dates(start_date: date, end_date: date) -> list[date]:
    dates: list[date] = []
    current = start_date
    while current <= end_date:
        dates.append(current)
        current += timedelta(days=1)
    return dates


def _output_path(output: str | None, source_name: str, start_date: date, end_date: date) -> Path:
    if output:
        path = Path(output)
    else:
        filename = f"linechart_{source_name}_{start_date.isoformat()}_{end_date.isoformat()}.png"
        path = Path("artifacts/charts") / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _matrix_from_rows(
    rows: list[DailyScoreRow],
    dates: list[date],
    top_n: int | None,
) -> tuple[np.ndarray, list[str]]:
    if top_n is not None and top_n <= 0:
        raise ValueError("--top-n must be greater than zero")

    date_to_idx = {day: idx for idx, day in enumerate(dates)}
    latest_score: dict[str, int] = {}
    for row in rows:
        latest_score[row.vpn_name] = row.score

    vpn_names = sorted(latest_score, key=lambda name: latest_score[name], reverse=True)
    if top_n is not None:
        vpn_names = vpn_names[:top_n]

    vpn_to_idx = {name: idx for idx, name in enumerate(vpn_names)}
    matrix = np.full((len(vpn_names), len(dates)), np.nan)

    for row in rows:
        vpn_idx = vpn_to_idx.get(row.vpn_name)
        date_idx = date_to_idx.get(row.point_date)
        if vpn_idx is None or date_idx is None:
            continue
        matrix[vpn_idx, date_idx] = row.score

    return matrix, vpn_names


def _effective_chart_dates(
    rows: list[DailyScoreRow], *, fallback_start: date, fallback_end: date
) -> list[date]:
    if not rows:
        return _build_dates(start_date=fallback_start, end_date=fallback_end)

    first_data_date = min(row.point_date for row in rows)
    last_data_date = max(row.point_date for row in rows)
    return _build_dates(start_date=first_data_date, end_date=last_data_date)


def _render_line_chart(
    *,
    matrix: np.ndarray,
    vpn_names: list[str],
    dates: list[date],
    source_name: str,
    output_path: Path,
) -> None:
    width = max(10, len(dates) * 0.4)
    height = max(6, len(vpn_names) * 0.35)

    fig, ax = plt.subplots(figsize=(width, height), dpi=180)
    fig.patch.set_facecolor("#0f111a")
    ax.set_facecolor("#0f111a")

    ax.set_xticks(np.arange(len(dates)))
    ax.set_xticklabels(
        [day.isoformat() for day in dates], rotation=45, ha="right", color="white"
    )

    x_values = np.arange(len(dates))
    endpoints: list[tuple[str, float, float, str]] = []
    for idx, vpn_name in enumerate(vpn_names):
        series = matrix[idx]
        present = ~np.isnan(series)
        observed_x = x_values[present]
        observed_y = series[present]
        if observed_x.size == 0:
            continue
        line_color = _color_for_vpn(vpn_name)
        plot_kwargs: dict[str, str | float] = {
            "marker": "o",
            "linewidth": 1.8,
            "markersize": 3,
        }
        if line_color:
            plot_kwargs["color"] = line_color
        (line,) = ax.plot(observed_x, observed_y, **plot_kwargs)
        endpoints.append(
            (
                vpn_name,
                float(observed_x[-1]),
                float(observed_y[-1]),
                line.get_color(),
            )
        )

    ax.set_xlabel("Date", color="white")
    ax.set_ylabel("Score", color="white")
    ax.set_ylim(0, 37)
    ax.set_xlim(-0.5, max(0.0, float(len(dates) - 1)) + 2.5)

    generated_at = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    ax.set_title(
        f"VPN Historical Scores ({source_name})\nGenerated: {generated_at}",
        color="white",
        fontsize=12,
        pad=14,
    )

    for spine in ax.spines.values():
        spine.set_color("#7f8c8d")

    _add_end_labels(ax=ax, endpoints=endpoints)

    ax.grid(True, color="#3b3f4a", alpha=0.4, linewidth=0.7)
    ax.tick_params(colors="white")
    fig.tight_layout()
    fig.savefig(output_path, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)


def _compute_label_positions(
    y_values: list[float], *, lower: float, upper: float, min_gap: float
) -> list[float]:
    if not y_values:
        return []

    sorted_indices = sorted(range(len(y_values)), key=lambda index: y_values[index])
    adjusted = [y_values[index] for index in sorted_indices]

    for idx in range(1, len(adjusted)):
        adjusted[idx] = max(adjusted[idx], adjusted[idx - 1] + min_gap)

    if adjusted[-1] > upper:
        shift_down = adjusted[-1] - upper
        adjusted = [value - shift_down for value in adjusted]

    for idx in range(len(adjusted) - 2, -1, -1):
        adjusted[idx] = min(adjusted[idx], adjusted[idx + 1] - min_gap)

    if adjusted[0] < lower:
        shift_up = lower - adjusted[0]
        adjusted = [value + shift_up for value in adjusted]

    positioned = [0.0] * len(y_values)
    for sorted_idx, original_idx in enumerate(sorted_indices):
        positioned[original_idx] = adjusted[sorted_idx]
    return positioned


def color_for_vpn(vpn_name: str) -> str | None:
    normalized_name = " ".join(vpn_name.split()).casefold()
    return VPN_LINE_COLORS.get(normalized_name)


def _color_for_vpn(vpn_name: str) -> str | None:
    return color_for_vpn(vpn_name)


def _add_end_labels(
    ax: matplotlib.axes.Axes,
    endpoints: list[tuple[str, float, float, str]],
) -> None:
    if not endpoints:
        return

    ymax = ax.get_ylim()[1] - 0.4
    y_values = [endpoint[2] for endpoint in endpoints]
    label_ys = _compute_label_positions(y_values, lower=0.4, upper=ymax, min_gap=0.7)
    label_x = max(endpoint[1] for endpoint in endpoints) + 0.55

    for (vpn_name, x_end, y_end, color), y_label in zip(endpoints, label_ys, strict=True):
        ax.plot([x_end, label_x - 0.08], [y_end, y_label], color=color, linewidth=0.9, alpha=0.85)
        ax.text(label_x, y_label, vpn_name, color=color, fontsize=8, va="center", ha="left")


def generate_historical_line_chart(
    session: Session,
    *,
    source_name: str = MAIN_LIVE_SOURCE_NAME,
    days: int | None = 30,
    from_date: date | None = None,
    to_date: date | None = None,
    top_n: int | None = None,
    output: str | None = None,
) -> ChartGenerationResult:
    date_range = resolve_date_range(
        session=session,
        days=days,
        from_date=from_date,
        to_date=to_date,
        source_name=source_name,
    )
    rows = query_daily_latest_scores(
        session=session,
        start_date=date_range.start_date,
        end_date=date_range.end_date,
        source_name=source_name,
    )
    dates = _effective_chart_dates(
        rows,
        fallback_start=date_range.start_date,
        fallback_end=date_range.end_date,
    )

    matrix, vpn_names = _matrix_from_rows(rows=rows, dates=dates, top_n=top_n)
    output_path = _output_path(
        output=output,
        source_name=source_name,
        start_date=date_range.start_date,
        end_date=date_range.end_date,
    )

    _render_line_chart(
        matrix=matrix,
        vpn_names=vpn_names,
        dates=dates,
        source_name=source_name,
        output_path=output_path,
    )

    chart = GeneratedChart(
        chart_date=date_range.end_date,
        chart_type=LINE_CHART_TYPE,
        source_name=source_name,
        range_start_date=date_range.start_date,
        range_end_date=date_range.end_date,
        range_days=(date_range.end_date - date_range.start_date).days + 1,
        file_path=str(output_path),
    )
    session.add(chart)
    session.commit()
    session.refresh(chart)

    return ChartGenerationResult(
        output_path=str(output_path),
        source_name=source_name,
        start_date=date_range.start_date,
        end_date=date_range.end_date,
        vpn_count=len(vpn_names),
        day_count=len(dates),
        chart_id=chart.id,
    )


generate_historical_heatmap = generate_historical_line_chart


def _metadata_from_legacy_chart_filename(path: Path) -> tuple[str | None, date | None, date | None]:
    match = re.match(
        r"^linechart_(?P<source>.+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.png$",
        path.name,
    )
    if not match:
        return None, None, None
    return (
        match.group("source"),
        date.fromisoformat(match.group("start")),
        date.fromisoformat(match.group("end")),
    )


def regenerate_chart_to_temp_file(
    session: Session,
    *,
    metadata: ChartRegenerationMetadata,
) -> Path:
    if metadata.chart_type != LINE_CHART_TYPE:
        raise ValueError(f"Unsupported chart type for regeneration: {metadata.chart_type}")

    source_name = metadata.source_name
    start_date = metadata.range_start_date
    end_date = metadata.range_end_date or metadata.chart_date

    if start_date is None or end_date is None or source_name is None:
        legacy_source, legacy_start, legacy_end = _metadata_from_legacy_chart_filename(
            metadata.file_path
        )
        source_name = source_name or legacy_source
        start_date = start_date or legacy_start
        end_date = end_date or legacy_end

    if end_date is None and metadata.chart_date is not None:
        end_date = metadata.chart_date
    if start_date is None and metadata.range_days and end_date is not None:
        start_date = end_date - timedelta(days=metadata.range_days - 1)

    if start_date is None or end_date is None or source_name is None:
        raise ValueError("Missing chart metadata (source/date range) for regeneration.")

    with NamedTemporaryFile(prefix="vrw_chart_", suffix=".png", delete=False) as tmp_file:
        output_path = tmp_file.name

    date_range = DateRange(start_date=start_date, end_date=end_date)
    rows = query_daily_latest_scores(
        session=session,
        start_date=date_range.start_date,
        end_date=date_range.end_date,
        source_name=source_name,
    )
    dates = _effective_chart_dates(
        rows,
        fallback_start=date_range.start_date,
        fallback_end=date_range.end_date,
    )
    matrix, vpn_names = _matrix_from_rows(rows=rows, dates=dates, top_n=None)

    _render_line_chart(
        matrix=matrix,
        vpn_names=vpn_names,
        dates=dates,
        source_name=source_name,
        output_path=Path(output_path),
    )
    return Path(output_path)
