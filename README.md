# vpn-rating-watcher

MVP service scaffold for monitoring https://vpn.maximkatz.com/ from the **rendered browser DOM**.

Current implementation scope:
- ✅ Rendered DOM scraping with Playwright
- ✅ Deterministic normalization and content hash
- ✅ Database persistence layer for snapshots and VPN row results
- ✅ Idempotent save behavior (`no_change` on same latest hash)
- ⛔ No chart generation yet
- ⛔ No Telegram posting yet

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
