from __future__ import annotations

import json

import typer

from vpn_rating_watcher.db.persistence import get_latest_snapshot_summary, persist_scrape_result
from vpn_rating_watcher.db.session import get_session_factory
from vpn_rating_watcher.importers.csv_backfill import (
    CSV_BACKFILL_SOURCE_NAME,
    CsvImportError,
    import_csv_backfill,
)
from vpn_rating_watcher.jobs import placeholders
from vpn_rating_watcher.scraper.service import scrape_once

app = typer.Typer(help="VPN rating watcher CLI")


@app.command("scrape")
def scrape_command(
    source_url: str = typer.Option("https://vpn.maximkatz.com/", help="Source URL to scrape."),
    artifacts_dir: str = typer.Option("artifacts", help="Directory for debug artifacts."),
    headless: bool = typer.Option(True, help="Run Chromium in headless mode."),
) -> None:
    """Run one-shot scraping from rendered DOM and print normalized payload."""
    result = scrape_once(
        source_url=source_url,
        artifacts_dir=artifacts_dir,
        headless=headless,
    )
    payload = result.model_dump(mode="json")
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


@app.command("scrape-save")
def scrape_and_save_command(
    source_name: str = typer.Option("maximkatz", help="Source identifier for DB dedupe."),
    source_url: str = typer.Option("https://vpn.maximkatz.com/", help="Source URL to scrape."),
    artifacts_dir: str = typer.Option("artifacts", help="Directory for debug artifacts."),
    headless: bool = typer.Option(True, help="Run Chromium in headless mode."),
) -> None:
    """Run scraping and persist results transactionally."""
    scrape_result = scrape_once(
        source_url=source_url,
        artifacts_dir=artifacts_dir,
        headless=headless,
    )
    session_factory = get_session_factory()
    with session_factory() as session:
        saved = persist_scrape_result(
            session=session, scrape_result=scrape_result, source_name=source_name
        )

    typer.echo(
        json.dumps(
            {
                "status": saved.status,
                "message": saved.message,
                "source_name": saved.source_name,
                "content_hash": saved.content_hash,
                "snapshot_id": saved.snapshot_id,
                "inserted_vpn_count": saved.inserted_vpn_count,
                "inserted_result_count": saved.inserted_result_count,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


@app.command("latest-snapshot")
def latest_snapshot_command(
    source_name: str = typer.Option("maximkatz", help="Source identifier to query."),
) -> None:
    """Print summary for the latest stored snapshot."""
    session_factory = get_session_factory()
    with session_factory() as session:
        summary = get_latest_snapshot_summary(session=session, source_name=source_name)

    if summary is None:
        typer.echo(json.dumps({"status": "empty", "source_name": source_name}, indent=2))
        raise typer.Exit(code=0)

    typer.echo(
        json.dumps(
            {
                "status": "ok",
                "snapshot_id": summary.snapshot_id,
                "source_name": summary.source_name,
                "source_url": summary.source_url,
                "fetched_at": summary.fetched_at.isoformat(),
                "content_hash": summary.content_hash,
                "row_count": summary.row_count,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


@app.command("import-csv")
def import_csv(
    path: str = typer.Option(..., "--path", help="Path to historical CSV file."),
    source_name: str = typer.Option(
        CSV_BACKFILL_SOURCE_NAME,
        "--source-name",
        help="Source identifier for imported historical snapshots.",
    ),
) -> None:
    """Import manually transcribed historical snapshots from CSV."""
    session_factory = get_session_factory()
    with session_factory() as session:
        try:
            summary = import_csv_backfill(session=session, path=path, source_name=source_name)
        except CsvImportError as exc:
            typer.echo(f"CSV validation error: {exc}")
            raise typer.Exit(code=2) from exc

    typer.echo(
        json.dumps(
            {
                "status": "ok",
                "path": summary.path,
                "source_name": summary.source_name,
                "total_snapshots": summary.total_snapshots,
                "created_snapshots": summary.created_snapshots,
                "skipped_snapshots": summary.skipped_snapshots,
                "total_rows": summary.total_rows,
                "results": [
                    {
                        "status": result.status,
                        "message": result.message,
                        "snapshot_id": result.snapshot_id,
                        "content_hash": result.content_hash,
                        "inserted_vpn_count": result.inserted_vpn_count,
                        "inserted_result_count": result.inserted_result_count,
                    }
                    for result in summary.persisted
                ],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


@app.command("chart")
def chart() -> None:
    """Phase placeholder for chart generation."""
    placeholders.not_implemented("chart")


@app.command("bot")
def run_bot() -> None:
    """Phase placeholder for Telegram bot polling/webhook runner."""
    placeholders.not_implemented("bot")


@app.command("post-daily")
def post_daily() -> None:
    """Phase placeholder for daily Telegram posting job."""
    placeholders.not_implemented("post-daily")
