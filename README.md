# vpn-rating-watcher

MVP service scaffold for monitoring https://vpn.maximkatz.com/ from the **rendered browser DOM**.

Current implementation scope:
- ✅ Rendered DOM scraping with Playwright
- ✅ Deterministic normalization and content hash
- ✅ Database persistence layer for snapshots and VPN row results
- ✅ Idempotent save behavior (`no_change` on same latest hash)
- ✅ Historical backfill import from manual CSV transcription
- ✅ Historical heatmap chart generation (PNG)
- ✅ Telegram bot polling commands (`/start`, `/help`, `/today`, `/chart`, `/last`)
- ⛔ No scheduled Telegram posting yet

## Local setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
playwright install chromium
cp .env.example .env
```

## Database setup

1. Ensure PostgreSQL is running and `DATABASE_URL` is set in `.env`.
2. Run migrations:

```bash
alembic upgrade head
```

## CLI commands

Scrape only (no DB write):

```bash
vrw scrape
```

Scrape and save transactionally:

```bash
vrw scrape-save --source-name maximkatz
```

Latest snapshot summary:

```bash
vrw latest-snapshot --source-name maximkatz
```

If the latest snapshot for a source has the same content hash, `scrape-save` returns `status: "no_change"` and does not duplicate rows.

Import historical data from CSV:

```bash
vrw import-csv --path examples/history_import.csv
```

Generate historical heatmap chart (default last 30 days from latest available snapshot):

```bash
vrw generate-chart --days 30
```

Generate chart using explicit date range:

```bash
vrw generate-chart --from 2026-03-01 --to 2026-03-29
```

Useful options:
- `--top-n 20` to keep only the top 20 VPN rows (sorted by latest score descending)
- `--source-name csv_backfill` to chart only imported historical snapshots
- `--source-name mixed` to combine all available sources
- `--output artifacts/charts/custom.png` to customize destination path

The command prints a structured JSON summary and persists chart metadata in `generated_chart`.

Run Telegram bot polling:

```bash
vrw bot
```

The bot reads `TELEGRAM_BOT_TOKEN` from `.env`. If missing, `vrw bot` exits with a clear error.


## Historical CSV backfill format

Use UTF-8 CSV with a header row.

Required columns:
- `snapshot_date` (ISO date, `YYYY-MM-DD`)
- `vpn_name`
- `checked_at_raw`
- `result_raw` (for example `34/36` or `34 / 36`)

Optional columns:
- `price_raw`
- `traffic_raw`
- `devices_raw`
- `details_url`

Import behavior:
- Rows are grouped into one logical snapshot per `snapshot_date`.
- Imported snapshots use source name `csv_backfill` by default.
- `result_raw` is parsed into `score`, `score_max`, and `score_pct`.
- Snapshot content hash is deterministic and based on normalized imported rows.
- Import is idempotent: rerunning the same CSV does not duplicate snapshots or rows.

See sample file: `examples/history_import.csv`.

## Persistence schema

Implemented tables:
- `vpn`
- `snapshot`
- `vpn_snapshot_result`
- `generated_chart`
- `telegram_chat`

## CI

GitHub Actions runs on every `push` and `pull_request`:
- Python 3.12
- `pip install -e '.[dev]'`
- `python -m playwright install --with-deps chromium`
- `ruff check .`
- `pytest`

CI scraper smoke test is deterministic: it uses static HTML with Playwright `page.set_content(...)` rather than the live site.

## Telegram bot commands

Set in `.env`:

```env
TELEGRAM_BOT_TOKEN=123456:your_token
```

Available bot commands:
- `/start` and `/help`: short help text
- `/today`: sends today's chart if available, otherwise latest chart overall
- `/chart`: sends latest chart overall
- `/last`: sends latest snapshot summary with source name, fetched time, and top 10 VPN scores

Notes:
- Incoming command chats are upserted into `telegram_chat` (`chat_id`, `chat_type`, `title`, `is_active`, `last_posted_date`).
- Bot command handling is polling-based (`vrw bot`).
- If chart metadata exists but the PNG is missing on disk, the bot replies with a clear error message.
- Daily posting scheduler is intentionally not implemented yet.

