from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import Select, desc, select
from sqlalchemy.orm import Session, sessionmaker

from vpn_rating_watcher.charts.service import LINE_CHART_TYPE
from vpn_rating_watcher.db.models import (
    GeneratedChart,
    Snapshot,
    TelegramChat,
    Vpn,
    VpnSnapshotResult,
)


@dataclass(slots=True)
class ChartLookupResult:
    chart_id: int
    file_path: Path
    chart_date: date | None


@dataclass(slots=True)
class LastSnapshotRow:
    rank_position: int
    vpn_name: str
    score: int
    score_max: int
    score_pct: float


@dataclass(slots=True)
class LastSnapshotSummary:
    source_name: str
    fetched_at: datetime
    top_rows: list[LastSnapshotRow]


def upsert_telegram_chat(
    session: Session,
    *,
    chat_id: str,
    chat_type: str | None,
    title: str | None,
) -> TelegramChat:
    stmt: Select[tuple[TelegramChat]] = select(TelegramChat).where(
        TelegramChat.chat_id == chat_id
    )
    existing = session.execute(stmt).scalar_one_or_none()
    if existing:
        existing.chat_type = chat_type
        existing.title = title
        existing.is_active = True
        session.commit()
        session.refresh(existing)
        return existing

    chat = TelegramChat(
        chat_id=chat_id,
        chat_type=chat_type,
        title=title,
        is_active=True,
    )
    session.add(chat)
    session.commit()
    session.refresh(chat)
    return chat


def _latest_chart_query() -> Select[tuple[GeneratedChart]]:
    return (
        select(GeneratedChart)
        .where(GeneratedChart.chart_type == LINE_CHART_TYPE)
        .order_by(
            desc(GeneratedChart.chart_date),
            desc(GeneratedChart.created_at),
            desc(GeneratedChart.id),
        )
    )


def get_latest_chart(session: Session) -> ChartLookupResult | None:
    chart = session.execute(_latest_chart_query().limit(1)).scalar_one_or_none()
    if not chart:
        return None
    return ChartLookupResult(
        chart_id=chart.id,
        file_path=Path(chart.file_path),
        chart_date=chart.chart_date,
    )


def get_latest_chart_for_date(
    session: Session,
    chart_date: date,
) -> ChartLookupResult | None:
    chart = session.execute(
        _latest_chart_query().where(GeneratedChart.chart_date == chart_date).limit(1)
    ).scalar_one_or_none()
    if not chart:
        return None
    return ChartLookupResult(
        chart_id=chart.id,
        file_path=Path(chart.file_path),
        chart_date=chart.chart_date,
    )


def get_today_or_latest_chart(
    session: Session,
    *,
    today: date | None = None,
) -> ChartLookupResult | None:
    resolved_today = today or datetime.now(tz=timezone.utc).date()
    return get_latest_chart_for_date(
        session=session,
        chart_date=resolved_today,
    ) or get_latest_chart(session=session)


def get_last_snapshot_summary(session: Session) -> LastSnapshotSummary | None:
    latest_snapshot = session.execute(
        select(Snapshot).order_by(desc(Snapshot.fetched_at), desc(Snapshot.id)).limit(1)
    ).scalar_one_or_none()
    if not latest_snapshot:
        return None

    rows = session.execute(
        select(
            VpnSnapshotResult.rank_position,
            Vpn.name,
            VpnSnapshotResult.score,
            VpnSnapshotResult.score_max,
            VpnSnapshotResult.score_pct,
        )
        .join(Vpn, Vpn.id == VpnSnapshotResult.vpn_id)
        .where(VpnSnapshotResult.snapshot_id == latest_snapshot.id)
        .order_by(VpnSnapshotResult.rank_position.asc(), VpnSnapshotResult.id.asc())
        .limit(10)
    ).all()

    top_rows = [
        LastSnapshotRow(
            rank_position=rank,
            vpn_name=vpn_name,
            score=score,
            score_max=score_max,
            score_pct=score_pct,
        )
        for rank, vpn_name, score, score_max, score_pct in rows
    ]

    fetched_at = latest_snapshot.fetched_at
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)

    return LastSnapshotSummary(
        source_name=latest_snapshot.source_name,
        fetched_at=fetched_at,
        top_rows=top_rows,
    )


def format_last_snapshot_summary(summary: LastSnapshotSummary) -> str:
    lines = [
        "Latest snapshot:",
        f"Source: {summary.source_name}",
        (
            "Fetched: "
            f"{summary.fetched_at.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        ),
        "Top 10:",
    ]

    for row in summary.top_rows:
        pct = row.score_pct * 100
        lines.append(
            f"{row.rank_position}. {row.vpn_name} — {row.score}/{row.score_max} ({pct:.1f}%)"
        )

    if not summary.top_rows:
        lines.append("No VPN rows found in the latest snapshot.")

    return "\n".join(lines)


class TelegramBotService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def upsert_chat(
        self,
        *,
        chat_id: str,
        chat_type: str | None,
        title: str | None,
    ) -> None:
        with self._session_factory() as session:
            upsert_telegram_chat(
                session=session,
                chat_id=chat_id,
                chat_type=chat_type,
                title=title,
            )

    def load_today_or_latest_chart(self) -> tuple[ChartLookupResult | None, str | None]:
        with self._session_factory() as session:
            chart = get_today_or_latest_chart(session=session)

        if chart is None:
            return None, "No charts found yet. Run `vrw generate-chart` first."

        if not chart.file_path.exists():
            return None, (
                "Chart metadata exists, but the file is missing on disk: "
                f"{chart.file_path}"
            )

        return chart, None

    def load_latest_chart(self) -> tuple[ChartLookupResult | None, str | None]:
        with self._session_factory() as session:
            chart = get_latest_chart(session=session)

        if chart is None:
            return None, "No charts found yet. Run `vrw generate-chart` first."

        if not chart.file_path.exists():
            return None, (
                "Chart metadata exists, but the file is missing on disk: "
                f"{chart.file_path}"
            )

        return chart, None

    def load_last_snapshot_text(self) -> str:
        with self._session_factory() as session:
            summary = get_last_snapshot_summary(session=session)

        if summary is None:
            return "No snapshots found yet. Run `vrw scrape-save` first."

        return format_last_snapshot_summary(summary)
