# vpn-rating-watcher

MVP service scaffold for monitoring https://vpn.maximkatz.com/ from the **rendered browser DOM**.

Current implementation scope:
- ✅ Rendered DOM scraping with Playwright
- ✅ Deterministic normalization and content hash
- ✅ Database persistence layer for snapshots and VPN row results
- ✅ Idempotent save behavior (`no_change` on same latest hash)
- ✅ Historical backfill import from manual CSV transcription
- ✅ Historical multi-line score chart generation (PNG)
- ✅ Telegram bot polling commands (`/start`, `/help`, `/today`, `/chart`, `/last`)
- ✅ Daily Telegram posting job command (`vrw post-daily`)
- ✅ Railway-ready deployment and scheduler wiring documentation

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

Generate historical score line chart (default last 30 days from latest available snapshot):

```bash
vrw generate-chart --days 30
```

Generate chart using explicit date range:

```bash
vrw generate-chart --from 2026-03-01 --to 2026-03-29
```

Repair persisted `checked_at` timestamps from stored `checked_at_raw` values (for already-saved rows):

```bash
vrw repair-checked-at --source-name maximkatz
```

Preview repair counts without writing changes:

```bash
vrw repair-checked-at --source-name maximkatz --dry-run
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

Run daily Telegram posting job:

```bash
vrw post-daily
```

Behavior of `vrw post-daily`:
- Reads `TELEGRAM_BOT_TOKEN` from `.env` and fails clearly if it is missing.
- Checks for a chart in `generated_chart` with `chart_date=today` (UTC date).
- If today's chart is missing, exits cleanly without sending messages.
- Sends today's chart image with short caption (`Daily chart: YYYY-MM-DD`) to active chats only (`telegram_chat.is_active=true`).
- Is idempotent: only sends when `last_posted_date` is older than today, then updates `last_posted_date=today`.
- Safe to rerun multiple times a day without duplicate posts.
- Supports optional `TELEGRAM_DEFAULT_CHAT_IDS` env var (comma-separated chat IDs). On run, those IDs are upserted into `telegram_chat` as active chats so they can receive posts.

Run hourly sync job (scrape + conditional chart rebuild + Telegram update notification):

```bash
vrw sync-hourly
```

Behavior of `vrw sync-hourly`:
- Scrapes source page and persists snapshot (`scrape-save` behavior).
- If content hash is unchanged, exits with `no_change` and does not rebuild chart.
- If content changed, rebuilds chart (`generate-chart` behavior) and stores chart metadata.
- Sends a Telegram text update to active chats with a compact change summary (`changed/new/removed`).
- Emits structured logs (start/no_change/updated) for troubleshooting.


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

## Railway deployment

This repository includes a Railway-ready `Dockerfile` and `railway.json`.

### 1) Create services/jobs

Use one repo and create three Railway services:

1. **Bot service** (long-running worker)
   - Start command: `vrw bot`
2. **Sync cron job**
   - Start command: `vrw sync-hourly`
   - Schedule: `0 */6 * * *` (4 times/day, every 6 hours UTC)
3. **Daily posting cron job**
   - Start command: `vrw post-daily`
   - Schedule: `0 19 * * *` (1 time/day, 19:00 UTC)

Railway cron schedules are configured in the Railway UI per service/job.

### 2) Attach PostgreSQL

1. Add a Railway PostgreSQL service.
2. Reference its connection string in `DATABASE_URL` for each service.
3. Run migrations before first production run:

```bash
alembic upgrade head
```

### 3) Set environment variables

Set these in Railway for all services unless noted:

- `APP_ENV=production`
- `APP_LOG_LEVEL=INFO`
- `DATABASE_URL=<railway postgres url>`
- `SOURCE_URL=https://vpn.maximkatz.com/`
- `SOURCE_TIMEZONE=UTC`
- `TELEGRAM_BOT_TOKEN=<required for bot and post-daily>`
- `TELEGRAM_DEFAULT_CHAT_IDS=<optional comma-separated chat IDs>`

Optional scheduler metadata vars (informational defaults in app):

- `SCRAPE_TIMES_UTC=00:00,06:00,12:00,18:00`
- `DAILY_POST_TIME_UTC=19:00`

### 4) Playwright dependencies on Railway

The included Docker image installs Chromium and required system libraries with:

```bash
python -m playwright install --with-deps chromium
```

No extra apt packages are needed in Railway when using this Dockerfile.

### 5) Runtime behavior and env-var failure boundaries

- `vrw bot` requires `TELEGRAM_BOT_TOKEN` and `DATABASE_URL`.
- `vrw scrape-save` requires `DATABASE_URL` (and browser dependencies).
- `vrw post-daily` requires `DATABASE_URL` and `TELEGRAM_BOT_TOKEN`.
- `vrw scrape` can run without DB credentials.

## Repairing historical wrong checked-at dates (production / Railway)

Use this if chart points are shifted to the wrong day because older persisted rows had an incorrect `checked_at`.

1. Open a Railway shell for the service connected to production `DATABASE_URL`.
2. (Recommended) run a dry-run first:

```bash
vrw repair-checked-at --source-name maximkatz --dry-run
```

3. Run the actual repair:

```bash
vrw repair-checked-at --source-name maximkatz
```

4. Regenerate chart(s) from repaired DB data:

```bash
vrw generate-chart --source-name maximkatz --days 30
```

Notes:
- The repair updates existing `vpn_snapshot_result.checked_at` values in place; it does not insert snapshots or rows.
- Parsed values are recomputed from each row's stored `checked_at_raw`, so historical bad days (for example stale March 30 points) are corrected after the repair and chart regeneration.

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
- Use Railway cron jobs (documented above) to run `vrw sync-hourly` and `vrw post-daily`.
