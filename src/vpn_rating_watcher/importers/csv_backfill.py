from __future__ import annotations

import csv
import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from vpn_rating_watcher.db.persistence import PersistSnapshotResult, persist_scrape_result
from vpn_rating_watcher.scraper.models import NormalizedRow, ScrapeResult
from vpn_rating_watcher.scraper.normalize import normalize_row_payload

CSV_REQUIRED_COLUMNS = {
    "snapshot_date",
    "vpn_name",
    "checked_at_raw",
    "result_raw",
}
CSV_OPTIONAL_COLUMNS = {
    "price_raw",
    "traffic_raw",
    "devices_raw",
    "details_url",
}
CSV_ALLOWED_COLUMNS = CSV_REQUIRED_COLUMNS | CSV_OPTIONAL_COLUMNS
CSV_BACKFILL_SOURCE_NAME = "csv_backfill"
CSV_BACKFILL_SOURCE_URL = "https://local.import/csv-backfill"


class CsvImportError(ValueError):
    """Raised when CSV validation fails."""


@dataclass(slots=True)
class CsvImportSummary:
    path: str
    source_name: str
    total_snapshots: int
    created_snapshots: int
    skipped_snapshots: int
    total_rows: int
    persisted: list[PersistSnapshotResult]


def _validate_columns(fieldnames: list[str] | None) -> list[str]:
    if not fieldnames:
        raise CsvImportError("CSV file is empty or missing header row")

    normalized = [name.strip() for name in fieldnames]
    missing = sorted(CSV_REQUIRED_COLUMNS - set(normalized))
    if missing:
        raise CsvImportError(f"CSV is missing required columns: {', '.join(missing)}")

    unknown = sorted(set(normalized) - CSV_ALLOWED_COLUMNS)
    if unknown:
        raise CsvImportError(
            "CSV contains unsupported columns: "
            f"{', '.join(unknown)}. Allowed columns: {', '.join(sorted(CSV_ALLOWED_COLUMNS))}"
        )

    return normalized


def _require_value(raw: dict[str, str], key: str, line_no: int) -> str:
    value = (raw.get(key) or "").strip()
    if not value:
        raise CsvImportError(f"Row {line_no}: '{key}' is required and cannot be empty")
    return value


def _parse_snapshot_date(raw_value: str, line_no: int) -> date:
    try:
        return date.fromisoformat(raw_value)
    except ValueError as exc:
        raise CsvImportError(
            f"Row {line_no}: snapshot_date must be ISO format YYYY-MM-DD, got '{raw_value}'"
        ) from exc


def _csv_row_to_normalized(raw: dict[str, str], rank_position: int, line_no: int) -> NormalizedRow:
    vpn_name = _require_value(raw, "vpn_name", line_no)
    checked_at_raw = _require_value(raw, "checked_at_raw", line_no)
    result_raw = _require_value(raw, "result_raw", line_no)

    row_payload = {
        "rank_position": rank_position,
        "vpn_name": vpn_name,
        "checked_at_raw": checked_at_raw,
        "result_raw": result_raw,
        "price_raw": (raw.get("price_raw") or "").strip() or None,
        "traffic_raw": (raw.get("traffic_raw") or "").strip() or None,
        "devices_raw": (raw.get("devices_raw") or "").strip() or None,
        "details_url": (raw.get("details_url") or "").strip() or None,
        "metadata": {},
    }

    try:
        return normalize_row_payload(row_payload)
    except ValueError as exc:
        raise CsvImportError(f"Row {line_no}: invalid result_raw '{result_raw}' ({exc})") from exc


def _build_snapshot_hash(snapshot_date: date, rows: list[NormalizedRow]) -> str:
    payload = {
        "snapshot_date": snapshot_date.isoformat(),
        "rows": [row.model_dump(mode="json", exclude_none=True) for row in rows],
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def parse_csv_backfill(path: str | Path) -> list[ScrapeResult]:
    csv_path = Path(path)
    if not csv_path.exists():
        raise CsvImportError(f"CSV file does not exist: {csv_path}")

    grouped: OrderedDict[date, list[NormalizedRow]] = OrderedDict()
    per_date_counts: dict[date, int] = {}

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        _validate_columns(reader.fieldnames)

        for line_no, raw in enumerate(reader, start=2):
            snapshot_date_raw = _require_value(raw, "snapshot_date", line_no)
            snapshot_date = _parse_snapshot_date(snapshot_date_raw, line_no)
            next_rank = per_date_counts.get(snapshot_date, 0) + 1
            row = _csv_row_to_normalized(raw, rank_position=next_rank, line_no=line_no)
            grouped.setdefault(snapshot_date, []).append(row)
            per_date_counts[snapshot_date] = next_rank

    scrape_results: list[ScrapeResult] = []
    for snapshot_date, rows in grouped.items():
        fetched_at = datetime(snapshot_date.year, snapshot_date.month, snapshot_date.day, tzinfo=UTC)
        table_hash = _build_snapshot_hash(snapshot_date=snapshot_date, rows=rows)
        scrape_results.append(
            ScrapeResult(
                source_url=CSV_BACKFILL_SOURCE_URL,
                scraped_at_utc=fetched_at.isoformat(),
                table_hash=table_hash,
                row_count=len(rows),
                rows=rows,
                artifacts_dir=str(csv_path.parent),
            )
        )

    return scrape_results


def import_csv_backfill(
    session: Session,
    path: str | Path,
    source_name: str = CSV_BACKFILL_SOURCE_NAME,
) -> CsvImportSummary:
    scrape_results = parse_csv_backfill(path)

    persisted: list[PersistSnapshotResult] = []
    created = 0
    skipped = 0
    total_rows = 0

    for scrape_result in scrape_results:
        save_result = persist_scrape_result(
            session=session,
            scrape_result=scrape_result,
            source_name=source_name,
        )
        persisted.append(save_result)
        total_rows += scrape_result.row_count
        if save_result.status == "created":
            created += 1
        else:
            skipped += 1

    return CsvImportSummary(
        path=str(path),
        source_name=source_name,
        total_snapshots=len(scrape_results),
        created_snapshots=created,
        skipped_snapshots=skipped,
        total_rows=total_rows,
        persisted=persisted,
    )
