from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import colormaps
from sqlalchemy import Select, and_, desc, func, select
from sqlalchemy.orm import Session

from vpn_rating_watcher.db.models import GeneratedChart, Snapshot, Vpn, VpnSnapshotResult

matplotlib.use("Agg")

MAIN_LIVE_SOURCE_NAME = "maximkatz"
MIXED_SOURCE_NAME = "mixed"
HEATMAP_CHART_TYPE = "historical_heatmap"


@dataclass(slots=True)
class DailyScoreRow:
    vpn_name: str
    snapshot_date: date
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


def _source_filter(source_name: str) -> bool:
    return source_name != MIXED_SOURCE_NAME


def get_max_snapshot_date(
    session: Session, source_name: str = MAIN_LIVE_SOURCE_NAME
) -> date | None:
    stmt = select(func.max(func.date(Snapshot.fetched_at)))
    if _source_filter(source_name):
        stmt = stmt.where(Snapshot.source_name == source_name)
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
        end_date = get_max_snapshot_date(
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
    snapshot_day = func.date(Snapshot.fetched_at)
    ranked = (
        select(
            Vpn.name.label("vpn_name"),
            snapshot_day.label("snapshot_date"),
            VpnSnapshotResult.score.label("score"),
            func.row_number()
            .over(
                partition_by=(VpnSnapshotResult.vpn_id, snapshot_day),
                order_by=(desc(Snapshot.fetched_at), desc(Snapshot.id), desc(VpnSnapshotResult.id)),
            )
            .label("row_num"),
        )
        .select_from(VpnSnapshotResult)
        .join(Snapshot, Snapshot.id == VpnSnapshotResult.snapshot_id)
        .join(Vpn, Vpn.id == VpnSnapshotResult.vpn_id)
        .where(and_(snapshot_day >= start_date, snapshot_day <= end_date))
    )

    if _source_filter(source_name):
        ranked = ranked.where(Snapshot.source_name == source_name)

    ranked_subq = ranked.subquery()
    stmt: Select[tuple[str, str, int]] = (
        select(
            ranked_subq.c.vpn_name,
            ranked_subq.c.snapshot_date,
            ranked_subq.c.score,
        )
        .where(ranked_subq.c.row_num == 1)
        .order_by(ranked_subq.c.vpn_name.asc(), ranked_subq.c.snapshot_date.asc())
    )

    return [
        DailyScoreRow(
            vpn_name=vpn_name,
            snapshot_date=(
                snapshot_date
                if isinstance(snapshot_date, date)
                else date.fromisoformat(str(snapshot_date))
            ),
            score=score,
        )
        for vpn_name, snapshot_date, score in session.execute(stmt).all()
    ]


def _build_dates(start_date: date, end_date: date) -> list[date]:
    dates: list[date] = []
    current = start_date
    while current <= end_date:
        dates.append(current)
        current += timedelta(days=1)
    return dates


def _output_path(
    output: str | None,
    source_name: str,
    start_date: date,
    end_date: date,
) -> Path:
    if output:
        path = Path(output)
    else:
        filename = f"heatmap_{source_name}_{start_date.isoformat()}_{end_date.isoformat()}.png"
        path = Path("artifacts/charts") / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _matrix_from_rows(
    rows: list[DailyScoreRow], dates: list[date], top_n: int | None
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
        date_idx = date_to_idx.get(row.snapshot_date)
        if vpn_idx is None or date_idx is None:
            continue
        matrix[vpn_idx, date_idx] = row.score

    return matrix, vpn_names


def _render_heatmap(
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

    cmap = colormaps["viridis"].copy()
    cmap.set_bad(color="#2f3542")

    im = ax.imshow(matrix, aspect="auto", interpolation="nearest", cmap=cmap)

    ax.set_xticks(np.arange(len(dates)))
    ax.set_xticklabels([day.isoformat() for day in dates], rotation=45, ha="right", color="white")
    ax.set_yticks(np.arange(len(vpn_names)))
    ax.set_yticklabels(vpn_names, color="white")

    ax.set_xlabel("Date", color="white")
    ax.set_ylabel("VPN", color="white")

    generated_at = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    ax.set_title(
        f"VPN Historical Scores Heatmap ({source_name})\nGenerated: {generated_at}",
        color="white",
        fontsize=12,
        pad=14,
    )

    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("Score (numerator from result_raw)", color="white")
    cbar.ax.yaxis.set_tick_params(color="white")
    plt.setp(cbar.ax.get_yticklabels(), color="white")

    for spine in ax.spines.values():
        spine.set_color("#7f8c8d")

    ax.tick_params(colors="white")
    fig.tight_layout()
    fig.savefig(output_path, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)


def generate_historical_heatmap(
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
    dates = _build_dates(start_date=date_range.start_date, end_date=date_range.end_date)
    rows = query_daily_latest_scores(
        session=session,
        start_date=date_range.start_date,
        end_date=date_range.end_date,
        source_name=source_name,
    )

    matrix, vpn_names = _matrix_from_rows(rows=rows, dates=dates, top_n=top_n)
    output_path = _output_path(
        output=output,
        source_name=source_name,
        start_date=date_range.start_date,
        end_date=date_range.end_date,
    )

    _render_heatmap(
        matrix=matrix,
        vpn_names=vpn_names,
        dates=dates,
        source_name=source_name,
        output_path=output_path,
    )

    chart = GeneratedChart(
        chart_date=date_range.end_date,
        chart_type=HEATMAP_CHART_TYPE,
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
