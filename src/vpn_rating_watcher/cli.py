from __future__ import annotations

import asyncio
import json
from datetime import date

import typer

from vpn_rating_watcher.bot.runner import run_polling
from vpn_rating_watcher.charts.service import MAIN_LIVE_SOURCE_NAME, generate_historical_heatmap
from vpn_rating_watcher.core.settings import get_settings
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


def _parse_iso_date(value: str | None, flag_name: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{flag_name} must be in YYYY-MM-DD format") from exc


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


@app.command("generate-chart")
def generate_chart_command(
    days: int | None = typer.Option(
        30, "--days", help="Number of days ending at latest available date."
    ),
    from_date_raw: str | None = typer.Option(
        None, "--from", help="Start date (YYYY-MM-DD)."
    ),
    to_date_raw: str | None = typer.Option(
        None, "--to", help="End date (YYYY-MM-DD)."
    ),
    top_n: int | None = typer.Option(
        None, "--top-n", help="Only include top N VPNs by latest score."
    ),
    source_name: str = typer.Option(
        MAIN_LIVE_SOURCE_NAME,
        "--source-name",
        help='Snapshot source name. Use "mixed" to combine all sources.',
    ),
    output: str | None = typer.Option(
        None, "--output", help="Custom output file path for PNG."
    ),
) -> None:
    """Generate historical heatmap PNG and persist chart metadata."""
    try:
        from_date = _parse_iso_date(from_date_raw, "--from")
        to_date = _parse_iso_date(to_date_raw, "--to")
    except ValueError as exc:
        typer.echo(f"Chart generation error: {exc}")
        raise typer.Exit(code=2) from exc

    session_factory = get_session_factory()
    with session_factory() as session:
        try:
            result = generate_historical_heatmap(
                session=session,
                source_name=source_name,
                days=days,
                from_date=from_date,
                to_date=to_date,
                top_n=top_n,
                output=output,
            )
        except ValueError as exc:
            typer.echo(f"Chart generation error: {exc}")
            raise typer.Exit(code=2) from exc

    typer.echo(
        json.dumps(
            {
                "status": "ok",
                "output_path": result.output_path,
                "source_name": result.source_name,
                "date_range": {
                    "from": result.start_date.isoformat(),
                    "to": result.end_date.isoformat(),
                },
                "vpn_count": result.vpn_count,
                "day_count": result.day_count,
                "chart_id": result.chart_id,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


@app.command("bot")
def run_bot() -> None:
    """Run Telegram bot in polling mode."""
    token = get_settings().telegram_bot_token
    if not token:
        typer.echo("Bot startup error: TELEGRAM_BOT_TOKEN is not set.")
        raise typer.Exit(code=2)

    session_factory = get_session_factory()
    asyncio.run(run_polling(token=token, session_factory=session_factory))


@app.command("post-daily")
def post_daily() -> None:
    """Phase placeholder for daily Telegram posting job."""
    placeholders.not_implemented("post-daily")
