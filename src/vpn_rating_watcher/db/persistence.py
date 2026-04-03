from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from dateutil import parser as date_parser
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from vpn_rating_watcher.db.models import Snapshot, Vpn, VpnSnapshotResult
from vpn_rating_watcher.scraper.models import NormalizedRow, ScrapeResult


@dataclass(slots=True)
class PersistSnapshotResult:
    status: str
    message: str
    source_name: str
    content_hash: str
    snapshot_id: int | None
    inserted_vpn_count: int
    inserted_result_count: int
    checked_at_parsed_count: int = 0
    checked_at_missing_raw_count: int = 0
    checked_at_parse_failed_count: int = 0
    checked_at_parse_failed_samples: tuple[str, ...] = ()


@dataclass(slots=True)
class SnapshotSummary:
    snapshot_id: int
    source_name: str
    source_url: str
    fetched_at: datetime
    content_hash: str
    row_count: int


@dataclass(slots=True)
class CheckedAtRepairSummary:
    source_name: str
    dry_run: bool
    total_rows: int
    reparable_rows: int
    updated_rows: int
    unchanged_rows: int
    unreparable_rows: int


def _normalize_vpn_name(name: str) -> str:
    return " ".join(name.strip().casefold().split())


def _parse_checked_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = date_parser.parse(value, dayfirst=True)
    except (ValueError, TypeError, OverflowError):
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_checked_at_with_reason(value: str | None) -> tuple[datetime | None, str]:
    if not value:
        return None, "missing_raw"

    parsed = _parse_checked_at(value)
    if parsed is None:
        return None, "parse_failed"
    return parsed, "parsed"


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _artifacts(run_dir: str) -> tuple[str | None, str | None, str | None]:
    base = Path(run_dir)
    html_path = base / "rendered.html"
    screenshot_path = base / "screenshot.png"
    normalized_path = base / "normalized.json"
    return (
        str(html_path) if html_path.exists() else None,
        str(screenshot_path) if screenshot_path.exists() else None,
        str(normalized_path) if normalized_path.exists() else None,
    )


def _get_latest_snapshot(session: Session, source_name: str) -> Snapshot | None:
    stmt: Select[tuple[Snapshot]] = (
        select(Snapshot)
        .where(Snapshot.source_name == source_name)
        .order_by(Snapshot.fetched_at.desc(), Snapshot.id.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()

def _get_snapshot_by_hash(session: Session, source_name: str, content_hash: str) -> Snapshot | None:
    stmt: Select[tuple[Snapshot]] = select(Snapshot).where(
        Snapshot.source_name == source_name,
        Snapshot.content_hash == content_hash,
    )
    return session.execute(stmt).scalar_one_or_none()


def _get_or_create_vpn(session: Session, row: NormalizedRow) -> tuple[Vpn, bool]:
    normalized_name = _normalize_vpn_name(row.vpn_name)
    vpn = session.execute(
        select(Vpn).where(Vpn.normalized_name == normalized_name)
    ).scalar_one_or_none()
    if vpn:
        if vpn.name != row.vpn_name:
            vpn.name = row.vpn_name
        return vpn, False

    vpn = Vpn(name=row.vpn_name, normalized_name=normalized_name)
    session.add(vpn)
    session.flush()
    return vpn, True


def persist_scrape_result(
    session: Session,
    scrape_result: ScrapeResult,
    source_name: str = "maximkatz",
) -> PersistSnapshotResult:
    with session.begin():
        existing = _get_snapshot_by_hash(
            session=session,
            source_name=source_name,
            content_hash=scrape_result.table_hash,
        )
        if existing:
            return PersistSnapshotResult(
                status="no_change",
                message="Snapshot with this content hash already exists for source",
                source_name=source_name,
                content_hash=scrape_result.table_hash,
                snapshot_id=existing.id,
                inserted_vpn_count=0,
                inserted_result_count=0,
            )

        raw_html_path, screenshot_path, normalized_json_path = _artifacts(
            scrape_result.artifacts_dir
        )

        snapshot = Snapshot(
            source_name=source_name,
            source_url=str(scrape_result.source_url),
            fetched_at=datetime.fromisoformat(scrape_result.scraped_at_utc),
            content_hash=scrape_result.table_hash,
            raw_payload_json=scrape_result.model_dump(mode="json"),
            raw_html_path=raw_html_path,
            screenshot_path=screenshot_path,
            normalized_json_path=normalized_json_path,
        )
        session.add(snapshot)
        session.flush()

        inserted_vpn_count = 0
        checked_at_parsed_count = 0
        checked_at_missing_raw_count = 0
        checked_at_parse_failed_count = 0
        checked_at_parse_failed_samples: list[str] = []
        for row in scrape_result.rows:
            vpn, inserted = _get_or_create_vpn(session=session, row=row)
            if inserted:
                inserted_vpn_count += 1

            parsed_checked_at, parse_status = _parse_checked_at_with_reason(row.checked_at_raw)
            if parse_status == "parsed":
                checked_at_parsed_count += 1
            elif parse_status == "missing_raw":
                checked_at_missing_raw_count += 1
            else:
                checked_at_parse_failed_count += 1
                if len(checked_at_parse_failed_samples) < 5 and row.checked_at_raw:
                    checked_at_parse_failed_samples.append(row.checked_at_raw)

            session.add(
                VpnSnapshotResult(
                    snapshot_id=snapshot.id,
                    vpn_id=vpn.id,
                    rank_position=row.rank_position,
                    checked_at=parsed_checked_at,
                    checked_at_raw=row.checked_at_raw,
                    result_raw=row.result_raw,
                    score=row.score,
                    score_max=row.score_max,
                    score_pct=row.score_pct,
                    price_raw=row.price_raw,
                    traffic_raw=row.traffic_raw,
                    devices_raw=row.devices_raw,
                    details_url=str(row.details_url) if row.details_url else None,
                )
            )

        return PersistSnapshotResult(
            status="created",
            message="New snapshot saved",
            source_name=source_name,
            content_hash=scrape_result.table_hash,
            snapshot_id=snapshot.id,
            inserted_vpn_count=inserted_vpn_count,
            inserted_result_count=len(scrape_result.rows),
            checked_at_parsed_count=checked_at_parsed_count,
            checked_at_missing_raw_count=checked_at_missing_raw_count,
            checked_at_parse_failed_count=checked_at_parse_failed_count,
            checked_at_parse_failed_samples=tuple(checked_at_parse_failed_samples),
        )


def get_latest_snapshot_summary(
    session: Session, source_name: str = "maximkatz"
) -> SnapshotSummary | None:
    latest = _get_latest_snapshot(session=session, source_name=source_name)
    if not latest:
        return None

    row_count_stmt = select(func.count(VpnSnapshotResult.id)).where(
        VpnSnapshotResult.snapshot_id == latest.id
    )
    row_count = session.execute(row_count_stmt).scalar_one()

    return SnapshotSummary(
        snapshot_id=latest.id,
        source_name=latest.source_name,
        source_url=latest.source_url,
        fetched_at=_ensure_utc(latest.fetched_at),
        content_hash=latest.content_hash,
        row_count=int(row_count),
    )


def repair_checked_at_from_raw(
    session: Session,
    *,
    source_name: str = "maximkatz",
    dry_run: bool = False,
) -> CheckedAtRepairSummary:
    """Recompute checked_at values from checked_at_raw for existing rows."""
    stmt: Select[tuple[VpnSnapshotResult]] = (
        select(VpnSnapshotResult)
        .join(Snapshot, Snapshot.id == VpnSnapshotResult.snapshot_id)
        .where(Snapshot.source_name == source_name)
        .order_by(VpnSnapshotResult.id.asc())
    )
    rows = session.execute(stmt).scalars().all()

    reparable_rows = 0
    updated_rows = 0
    unreparable_rows = 0

    for row in rows:
        parsed_checked_at = _parse_checked_at(row.checked_at_raw)
        if parsed_checked_at is None:
            unreparable_rows += 1
            continue

        reparable_rows += 1
        current_checked_at = row.checked_at
        if current_checked_at is not None:
            current_checked_at = _ensure_utc(current_checked_at)

        if current_checked_at == parsed_checked_at:
            continue

        updated_rows += 1
        if not dry_run:
            row.checked_at = parsed_checked_at

    if not dry_run and updated_rows > 0:
        session.commit()

    return CheckedAtRepairSummary(
        source_name=source_name,
        dry_run=dry_run,
        total_rows=len(rows),
        reparable_rows=reparable_rows,
        updated_rows=updated_rows,
        unchanged_rows=reparable_rows - updated_rows,
        unreparable_rows=unreparable_rows,
    )
