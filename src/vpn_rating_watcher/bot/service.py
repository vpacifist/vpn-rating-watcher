from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from dateutil import parser as date_parser
from sqlalchemy import Select, desc, select
from sqlalchemy.orm import Session, sessionmaker

from vpn_rating_watcher.charts.service import (
    CHART_MODE_DAILY,
    CHART_THEME_DARK,
    CHART_THEMES,
    LINE_CHART_TYPE,
    ChartRegenerationMetadata,
    regenerate_chart_to_temp_file,
)
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
    chart_type: str
    chart_date: date | None
    source_name: str | None
    range_start_date: date | None
    range_end_date: date | None
    range_days: int | None
    is_temporary: bool = False


@dataclass(slots=True)
class LastSnapshotRow:
    rank_position: int
    vpn_name: str
    score: int
    score_max: int
    score_pct: float
    checked_at: datetime | None
    checked_at_raw: str | None


@dataclass(slots=True)
class LastSnapshotSummary:
    source_name: str
    fetched_at: datetime
    top_rows: list[LastSnapshotRow]


def _format_checked_at_for_outlier(row: LastSnapshotRow) -> str:
    if row.checked_at_raw:
        return row.checked_at_raw

    if row.checked_at is None:
        return "unknown"

    checked_at = row.checked_at
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=timezone.utc)
    return checked_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _score_emoji(score_pct: float) -> str:
    pct = score_pct * 100
    if pct >= 80:
        return "🟢"
    if pct >= 50:
        return "🟡"
    return "🔴"


def _checked_at_utc(row: LastSnapshotRow) -> datetime | None:
    if row.checked_at is not None:
        checked_at = row.checked_at
        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=timezone.utc)
        return checked_at.astimezone(timezone.utc)

    if not row.checked_at_raw:
        return None

    normalized = row.checked_at_raw.strip().lower()
    month_aliases = {
        "янв": "jan",
        "фев": "feb",
        "мар": "mar",
        "апр": "apr",
        "мая": "may",
        "май": "may",
        "июн": "jun",
        "июл": "jul",
        "авг": "aug",
        "сен": "sep",
        "сент": "sep",
        "окт": "oct",
        "ноя": "nov",
        "дек": "dec",
    }
    for ru_month, en_month in month_aliases.items():
        normalized = normalized.replace(ru_month, en_month)

    try:
        parsed = date_parser.parse(normalized, dayfirst=True)
    except (ValueError, TypeError, OverflowError):
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def upsert_telegram_chat(
    session: Session,
    *,
    chat_id: str,
    chat_type: str | None,
    title: str | None,
    chart_theme: str | None = None,
    is_active: bool = True,
) -> TelegramChat:
    if chart_theme is not None and chart_theme not in CHART_THEMES:
        raise ValueError(f"Unsupported chart theme: {chart_theme}")

    stmt: Select[tuple[TelegramChat]] = select(TelegramChat).where(
        TelegramChat.chat_id == chat_id
    )
    existing = session.execute(stmt).scalar_one_or_none()
    if existing:
        existing.chat_type = chat_type
        existing.title = title
        if chart_theme is not None:
            existing.chart_theme = chart_theme
        existing.is_active = is_active
        session.commit()
        session.refresh(existing)
        return existing

    chat = TelegramChat(
        chat_id=chat_id,
        chat_type=chat_type,
        title=title,
        chart_theme=chart_theme,
        is_active=is_active,
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
        chart_type=chart.chart_type,
        chart_date=chart.chart_date,
        source_name=chart.source_name,
        range_start_date=chart.range_start_date,
        range_end_date=chart.range_end_date,
        range_days=chart.range_days,
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
        chart_type=chart.chart_type,
        chart_date=chart.chart_date,
        source_name=chart.source_name,
        range_start_date=chart.range_start_date,
        range_end_date=chart.range_end_date,
        range_days=chart.range_days,
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
            VpnSnapshotResult.checked_at,
            VpnSnapshotResult.checked_at_raw,
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
            checked_at=checked_at,
            checked_at_raw=checked_at_raw,
        )
        for rank, vpn_name, score, score_max, score_pct, checked_at, checked_at_raw in rows
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
    fetched_utc = summary.fetched_at.astimezone(timezone.utc)
    lines = [
        f"🏆 Top VPN — snapshot {fetched_utc.strftime('%Y-%m-%d %H:%M UTC')}",
        "",
    ]

    outlier_names: list[str] = []
    checked_times = [checked_at for row in summary.top_rows if (checked_at := _checked_at_utc(row))]
    stale_cutoff = fetched_utc.timestamp() - 12 * 60 * 60

    for row in summary.top_rows:
        pct = row.score_pct * 100
        stale_suffix = ""
        checked_at = _checked_at_utc(row)
        if checked_at is not None and checked_at.timestamp() < stale_cutoff:
            stale_suffix = " · stale"
            outlier_names.append(
                f"{row.vpn_name} ({_format_checked_at_for_outlier(row)})"
            )

        lines.append(
            f"{_score_emoji(row.score_pct)} "
            f"#{row.rank_position} {row.vpn_name} — "
            f"{pct:.1f}% ({row.score}/{row.score_max})"
            f"{stale_suffix}"
        )

    if not summary.top_rows:
        lines.append("No VPN rows found in the latest snapshot.")
        lines.append("")
        lines.append(f"ℹ️ Source: {summary.source_name}")
        return "\n".join(lines)

    lines.append("")
    provider_size = summary.top_rows[0].score_max if summary.top_rows else "unknown"
    lines.append(f"ℹ️ Source: {summary.source_name} · {provider_size} checks/provider")

    if checked_times:
        sorted_times = sorted(checked_times)
        start_time = sorted_times[0]
        end_time = sorted_times[-1]
        if start_time.date() == end_time.date():
            freshness = (
                f"{start_time.strftime('%-d %b, %H:%M')}–"
                f"{end_time.strftime('%H:%M')} UTC"
            )
        else:
            freshness = (
                f"{start_time.strftime('%-d %b, %H:%M')}–"
                f"{end_time.strftime('%-d %b, %H:%M')} UTC"
            )
        if outlier_names:
            outlier_text = ", ".join(outlier_names)
            lines.append(f"🕒 Freshness: {freshness} · outliers: {outlier_text}")
        else:
            lines.append(f"🕒 Freshness: {freshness}")
    elif outlier_names:
        outlier_text = ", ".join(outlier_names)
        lines.append(f"🕒 Freshness: unknown · outliers: {outlier_text}")
    else:
        lines.append("🕒 Freshness: unknown")

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
        is_active: bool = True,
    ) -> None:
        with self._session_factory() as session:
            upsert_telegram_chat(
                session=session,
                chat_id=chat_id,
                chat_type=chat_type,
                title=title,
                chart_theme=None,
                is_active=is_active,
            )

    def set_chat_subscription(
        self,
        *,
        chat_id: str,
        chat_type: str | None,
        title: str | None,
        is_active: bool,
    ) -> None:
        with self._session_factory() as session:
            upsert_telegram_chat(
                session=session,
                chat_id=chat_id,
                chat_type=chat_type,
                title=title,
                chart_theme=None,
                is_active=is_active,
            )

    def is_chat_subscribed(self, *, chat_id: str) -> bool:
        with self._session_factory() as session:
            chat = session.execute(
                select(TelegramChat).where(TelegramChat.chat_id == chat_id)
            ).scalar_one_or_none()
            return bool(chat and chat.is_active)

    def set_chat_theme(
        self,
        *,
        chat_id: str,
        chat_type: str | None,
        title: str | None,
        chart_theme: str,
    ) -> None:
        with self._session_factory() as session:
            existing = session.execute(
                select(TelegramChat).where(TelegramChat.chat_id == chat_id)
            ).scalar_one_or_none()
            is_active = existing.is_active if existing is not None else chat_type == "private"
            upsert_telegram_chat(
                session=session,
                chat_id=chat_id,
                chat_type=chat_type,
                title=title,
                chart_theme=chart_theme,
                is_active=is_active,
            )

    def get_chat_theme(self, *, chat_id: str) -> str | None:
        with self._session_factory() as session:
            chat = session.execute(
                select(TelegramChat).where(TelegramChat.chat_id == chat_id)
            ).scalar_one_or_none()
            return chat.chart_theme if chat is not None else None

    def load_today_or_latest_chart(
        self, *, mode: str = CHART_MODE_DAILY, theme: str = CHART_THEME_DARK
    ) -> tuple[ChartLookupResult | None, str | None]:
        with self._session_factory() as session:
            chart = get_today_or_latest_chart(session=session)
            if chart is None:
                return None, "No charts found yet. Run `vrw generate-chart` first."
            original_path = chart.file_path
            chart_path, error = _resolve_chart_path(
                session=session,
                chart=chart,
                mode=mode,
                theme=theme,
            )

        if error:
            return None, error

        assert chart_path is not None
        chart.file_path = chart_path
        chart.is_temporary = chart_path != original_path
        return chart, None

    def load_latest_chart(
        self, *, mode: str = CHART_MODE_DAILY, theme: str = CHART_THEME_DARK
    ) -> tuple[ChartLookupResult | None, str | None]:
        with self._session_factory() as session:
            chart = get_latest_chart(session=session)
            if chart is None:
                return None, "No charts found yet. Run `vrw generate-chart` first."
            original_path = chart.file_path
            chart_path, error = _resolve_chart_path(
                session=session,
                chart=chart,
                mode=mode,
                theme=theme,
            )

        if error:
            return None, error

        assert chart_path is not None
        chart.file_path = chart_path
        chart.is_temporary = chart_path != original_path
        return chart, None

    def load_last_snapshot_text(self) -> str:
        with self._session_factory() as session:
            summary = get_last_snapshot_summary(session=session)

        if summary is None:
            return "No snapshots found yet. Run `vrw scrape-save` first."

        return format_last_snapshot_summary(summary)


def _resolve_chart_path(
    *,
    session: Session,
    chart: ChartLookupResult,
    mode: str = CHART_MODE_DAILY,
    theme: str = CHART_THEME_DARK,
) -> tuple[Path | None, str | None]:
    if mode == CHART_MODE_DAILY and theme == CHART_THEME_DARK and chart.file_path.exists():
        return chart.file_path, None

    try:
        regenerated_path = regenerate_chart_to_temp_file(
            session=session,
            metadata=ChartRegenerationMetadata(
                chart_type=chart.chart_type,
                source_name=chart.source_name,
                range_start_date=chart.range_start_date,
                range_end_date=chart.range_end_date,
                range_days=chart.range_days,
                chart_date=chart.chart_date,
                file_path=chart.file_path,
            ),
            mode=mode,
            theme=theme,
        )
    except ValueError as exc:
        return None, f"Failed to regenerate chart from DB data: {exc}"

    if not regenerated_path.exists():
        return None, (
            "Failed to regenerate chart from DB data; file is still missing: "
            f"{regenerated_path}"
        )
    return regenerated_path, None


def cleanup_temporary_chart_file(chart: ChartLookupResult) -> None:
    if not chart.is_temporary:
        return
    chart.file_path.unlink(missing_ok=True)
