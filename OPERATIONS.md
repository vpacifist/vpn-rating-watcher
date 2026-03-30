# OPERATIONS

## Scraper flow

1. Run `vrw scrape-save`.
2. The scraper loads the rendered source page with Playwright Chromium.
3. Parsed rows are normalized and hashed.
4. Snapshot + result rows are written to PostgreSQL transactionally.
5. If the latest hash is unchanged, the run returns `no_change` and avoids duplicates.

## Chart generation flow

1. Run `vrw generate-chart` (explicitly or from an operator workflow).
2. Historical snapshot results are aggregated by day.
3. A PNG heatmap is written to `artifacts/charts/...`.
4. Chart metadata is stored in `generated_chart` for bot/posting retrieval.

## Bot flow

1. Run `vrw bot` as a long-running process.
2. Bot polls Telegram for commands.
3. Incoming chats are upserted to `telegram_chat` and marked active.
4. Commands send chart/snapshot responses from DB-backed data.

## Daily posting flow

1. Run `vrw post-daily` once per day.
2. Command verifies today's chart exists.
3. Active chats are resolved from `telegram_chat` plus optional
   `TELEGRAM_DEFAULT_CHAT_IDS` bootstrap values.
4. Chart is posted once per chat per UTC day (`last_posted_date` guarded).

## Recommended Railway setup

Create three Railway services from the same repository/image:

1. **vrw-bot** (worker)
   - Command: `vrw bot`
   - Schedule: none (always on)
2. **vrw-scrape** (cron)
   - Command: `vrw scrape-save`
   - Schedule: `0 */6 * * *`
3. **vrw-post-daily** (cron)
   - Command: `vrw post-daily`
   - Schedule: `0 19 * * *`

Shared config:

- Attach Railway PostgreSQL and set `DATABASE_URL` for all services.
- Set `SOURCE_URL` and `SOURCE_TIMEZONE`.
- Set `TELEGRAM_BOT_TOKEN` for bot and daily posting jobs.
- Optionally set `TELEGRAM_DEFAULT_CHAT_IDS` to seed chat targets.
- Use included Dockerfile so Playwright Chromium + deps are preinstalled.
