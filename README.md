# vpn-rating-watcher

Каркас MVP-сервиса для мониторинга https://vpn.maximkatz.com/ на основе **рендеренного DOM в браузере**.

Текущий функциональный объём:
- ✅ Скрапинг рендеренного DOM через Playwright
- ✅ Детерминированная нормализация и content hash
- ✅ Слой сохранения в БД для снапшотов и строк результатов VPN
- ✅ Идемпотентное сохранение (`no_change`, если хэш совпадает с последним)
- ✅ Импорт исторических данных из вручную подготовленного CSV
- ✅ Генерация исторических multi-line графиков (PNG)
- ✅ Команды Telegram-бота в polling-режиме (`/start`, `/help`, `/today`, `/chart`, `/last`)
- ✅ Команда ежедневной публикации в Telegram (`vrw post-daily`)
- ✅ Документация по деплою в Railway и настройке расписаний

## Локальная установка

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
playwright install chromium
cp .env.example .env
```

## Настройка базы данных

1. Убедитесь, что PostgreSQL запущен и `DATABASE_URL` задан в `.env`.
2. Примените миграции:

```bash
alembic upgrade head
```

## CLI-команды

Только скрапинг (без записи в БД):

```bash
vrw scrape
```

Скрапинг и транзакционное сохранение:

```bash
vrw scrape-save --source-name maximkatz
```

Сводка по последнему снапшоту:

```bash
vrw latest-snapshot --source-name maximkatz
```

Если у последнего снапшота источника такой же content hash, `scrape-save` возвращает `status: "no_change"` и не дублирует строки.

Импорт исторических данных из CSV:

```bash
vrw import-csv --path examples/history_import.csv
```

Генерация исторического графика оценок (по умолчанию — последние 30 дней от наиболее свежего доступного снапшота):

```bash
vrw generate-chart --days 30
```

Генерация графика для явного диапазона дат:

```bash
vrw generate-chart --from 2026-03-01 --to 2026-03-29
```

Исправление сохранённых `checked_at` по значениям из `checked_at_raw` (для уже записанных строк):

```bash
vrw repair-checked-at --source-name maximkatz
```

Предпросмотр количества исправлений без записи в БД:

```bash
vrw repair-checked-at --source-name maximkatz --dry-run
```

Полезные опции:
- `--top-n 20` — оставить только топ-20 строк VPN (сортировка по убыванию актуального score)
- `--source-name csv_backfill` — строить график только по импортированным историческим снапшотам
- `--source-name mixed` — объединить все доступные источники
- `--output artifacts/charts/custom.png` — задать путь сохранения

Команда печатает структурированную JSON-сводку и сохраняет метаданные графика в `generated_chart`.

Запуск polling-бота Telegram:

```bash
vrw bot
```

Бот читает `TELEGRAM_BOT_TOKEN` из `.env`. Если переменная не задана, `vrw bot` завершится с понятной ошибкой.

Запуск ежедневной публикации в Telegram:

```bash
vrw post-daily
```

Поведение `vrw post-daily`:
- Читает `TELEGRAM_BOT_TOKEN` из `.env` и явно падает, если переменная отсутствует.
- Ищет график в `generated_chart` с `chart_date=today` (дата UTC).
- Если графика за сегодня нет, корректно завершается без отправки сообщений.
- Отправляет изображение графика за сегодня с короткой подписью (`Daily chart: YYYY-MM-DD`) только активным чатам (`telegram_chat.is_active=true`).
- Идемпотентна: отправляет только если `last_posted_date` меньше сегодняшней даты, затем обновляет `last_posted_date=today`.
- Безопасна для повторных запусков в течение дня — дубликатов не будет.
- Поддерживает необязательную переменную `TELEGRAM_DEFAULT_CHAT_IDS` (список chat ID через запятую). Во время запуска эти ID upsert-ятся в `telegram_chat` как активные чаты для получения постов.

Запуск почасовой синхронизации (скрапинг + условная пересборка графика + уведомление в Telegram):

```bash
vrw sync-hourly
```

Поведение `vrw sync-hourly`:
- Скрапит страницу-источник и сохраняет снапшот (поведение `scrape-save`).
- Если content hash не изменился, завершает работу с `no_change` и не пересобирает график.
- Если контент изменился, пересобирает график (поведение `generate-chart`) и сохраняет метаданные графика.
- Отправляет текстовое уведомление в Telegram активным чатам с компактной сводкой изменений (`changed/new/removed`).
- Пишет структурированные логи (`start/no_change/updated`) для диагностики.

## Формат исторического CSV для backfill

Используйте CSV в UTF-8 с заголовком.

Обязательные столбцы:
- `snapshot_date` (ISO-дата, `YYYY-MM-DD`)
- `vpn_name`
- `checked_at_raw`
- `result_raw` (например, `34/36` или `34 / 36`)

Необязательные столбцы:
- `price_raw`
- `traffic_raw`
- `devices_raw`
- `details_url`

Поведение импорта:
- Строки группируются в один логический снапшот на каждый `snapshot_date`.
- Импортированные снапшоты по умолчанию используют source name `csv_backfill`.
- `result_raw` парсится в `score`, `score_max` и `score_pct`.
- Content hash снапшота детерминированный и строится из нормализованных импортированных строк.
- Импорт идемпотентен: повторный запуск с тем же CSV не создаёт дубликаты снапшотов и строк.

Пример файла: `examples/history_import.csv`.

## Схема хранения данных

Реализованные таблицы:
- `vpn`
- `snapshot`
- `vpn_snapshot_result`
- `generated_chart`
- `telegram_chat`

## CI

GitHub Actions запускается на каждый `push` и `pull_request`:
- Python 3.12
- `pip install -e '.[dev]'`
- `python -m playwright install --with-deps chromium`
- `ruff check .`
- `pytest`

Smoke-тест скрапера в CI детерминированный: используется статический HTML через Playwright `page.set_content(...)`, а не live-сайт.

## Деплой в Railway

В репозитории уже есть готовые `Dockerfile` и `railway.json` для Railway.

### 1) Создайте сервисы/джобы

Используйте один репозиторий и создайте три Railway-сервиса:

1. **Сервис бота** (долгоживущий worker)
   - Команда запуска: `vrw bot`
2. **Cron-джоба синхронизации**
   - Команда запуска: `vrw sync-hourly`
   - Расписание: `0 * * * *` (каждый час, UTC)
3. **Cron-джоба ежедневной публикации**
   - Команда запуска: `vrw post-daily`
   - Расписание: `0 19 * * *` (1 раз в день, 19:00 UTC)

Cron-расписания Railway задаются в UI Railway для каждого сервиса/джобы.

### 2) Подключите PostgreSQL

1. Добавьте сервис PostgreSQL в Railway.
2. Передайте его connection string в `DATABASE_URL` для каждого сервиса.
3. Перед первым прод-запуском примените миграции:

```bash
alembic upgrade head
```

### 3) Задайте переменные окружения

Задайте эти переменные в Railway для всех сервисов (если не указано иное):

- `APP_ENV=production`
- `APP_LOG_LEVEL=INFO`
- `DATABASE_URL=<railway postgres url>`
- `SOURCE_URL=https://vpn.maximkatz.com/`
- `SOURCE_TIMEZONE=UTC`
- `TELEGRAM_BOT_TOKEN=<обязательно для bot и post-daily>`
- `TELEGRAM_DEFAULT_CHAT_IDS=<необязательно, chat ID через запятую>`

Необязательные переменные с метаданными расписания (информационные дефолты в приложении):

- `SCRAPE_TIMES_UTC=every hour (0 * * * *)`
- `DAILY_POST_TIME_UTC=19:00`

### 4) Зависимости Playwright в Railway

Включённый Docker-образ устанавливает Chromium и нужные системные библиотеки командой:

```bash
python -m playwright install --with-deps chromium
```

При использовании этого Dockerfile дополнительные apt-пакеты в Railway не нужны.

### 5) Поведение на рантайме и границы обязательных env-переменных

- `vrw bot` требует `TELEGRAM_BOT_TOKEN` и `DATABASE_URL`.
- `vrw scrape-save` требует `DATABASE_URL` (и browser-зависимости).
- `vrw post-daily` требует `DATABASE_URL` и `TELEGRAM_BOT_TOKEN`.
- `vrw scrape` может запускаться без реквизитов БД.

## Исправление исторически неверных checked-at дат (production / Railway)

Используйте это, если точки на графике сдвинуты на неверный день из-за ошибочных `checked_at` в ранее сохранённых строках.

1. Откройте Railway shell для сервиса, подключённого к production `DATABASE_URL`.
2. (Рекомендуется) сначала dry-run:

```bash
vrw repair-checked-at --source-name maximkatz --dry-run
```

3. Запустите фактическое исправление:

```bash
vrw repair-checked-at --source-name maximkatz
```

4. Перегенерируйте график(и) на основе исправленных данных из БД:

```bash
vrw generate-chart --source-name maximkatz --days 30
```

Примечания:
- Команда обновляет существующие значения `vpn_snapshot_result.checked_at` in-place; новые снапшоты/строки не вставляются.
- Значения пересчитываются из сохранённого `checked_at_raw` каждой строки, поэтому исторические ошибки дат (например, «зависшие» точки за 30 марта) исправляются после запуска repair и повторной генерации графика.

## Команды Telegram-бота

Задайте в `.env`:

```env
TELEGRAM_BOT_TOKEN=123456:your_token
```

Доступные команды бота:
- `/start` и `/help`: краткая справка
- `/today`: отправляет график за сегодня, если он есть, иначе последний доступный график
- `/chart`: отправляет последний доступный график
- `/last`: отправляет сводку по последнему снапшоту (имя источника, время получения и топ-10 оценок VPN)

Примечания:
- Чаты с входящими командами upsert-ятся в `telegram_chat` (`chat_id`, `chat_type`, `title`, `is_active`, `last_posted_date`).
- Обработка команд бота работает в polling-режиме (`vrw bot`).
- Если метаданные графика есть, но PNG отсутствует на диске, бот возвращает понятное сообщение об ошибке.
- Для запуска `vrw sync-hourly` и `vrw post-daily` используйте Railway cron jobs (см. раздел выше).
