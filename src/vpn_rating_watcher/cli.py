from __future__ import annotations

import json

import typer

from vpn_rating_watcher.db.persistence import get_latest_snapshot_summary, persist_scrape_result
from vpn_rating_watcher.db.session import SessionLocal
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
    with SessionLocal() as session:
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
    with SessionLocal() as session:
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
def import_csv(path: str) -> None:
    """Phase placeholder for CSV backfill import job."""
    placeholders.not_implemented(f"import-csv ({path})")


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
