from __future__ import annotations

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

from vpn_rating_watcher.charts.service import (
    MAIN_LIVE_SOURCE_NAME,
    query_daily_latest_scores,
    resolve_date_range,
)
from vpn_rating_watcher.db.session import get_session_factory
from vpn_rating_watcher.web.payload import build_chart_payload

app = FastAPI(title="VPN Rating Watcher", version="1.0.0")



@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/chart-data")
def api_chart_data(
    days: int | None = Query(default=30, ge=1, le=365),
    source_name: str = Query(default=MAIN_LIVE_SOURCE_NAME),
    top_n: int | None = Query(default=10, ge=1, le=50),
) -> dict:
    session_factory = get_session_factory()
    with session_factory() as session:
        date_range = resolve_date_range(
            session=session,
            days=days,
            from_date=None,
            to_date=None,
            source_name=source_name,
        )
        rows = query_daily_latest_scores(
            session=session,
            start_date=date_range.start_date,
            end_date=date_range.end_date,
            source_name=source_name,
        )

    return build_chart_payload(
        rows=rows,
        start_date=date_range.start_date,
        end_date=date_range.end_date,
        source_name=source_name,
        top_n=top_n,
    )




@app.get("/api/chart")
def api_chart_legacy(
    days: int | None = Query(default=30, ge=1, le=365),
    source_name: str = Query(default=MAIN_LIVE_SOURCE_NAME),
    top_n: int | None = Query(default=10, ge=1, le=50),
) -> dict:
    """Backward-compatible alias for older clients."""
    return api_chart_data(days=days, source_name=source_name, top_n=top_n)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return """<!doctype html>
<html lang='ru'>
<head>
  <meta charset='utf-8' />
  <meta name='viewport' content='width=device-width,initial-scale=1' />
  <title>VPN rating watcher</title>
  <script src='https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js'></script>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0f111a;
      --panel: #171a26;
      --text: #f5f7ff;
      --muted: #a8b0c7;
      --accent: #4ea1ff;
    }
    body {
      margin: 0;
      font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      padding: 12px;
    }
    .wrap {
      max-width: 1200px;
      margin: 0 auto;
    }
    .card {
      background: var(--panel);
      border-radius: 12px;
      padding: 12px;
    }
    .toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      margin-bottom: 10px;
    }
    .toolbar select, .toolbar button {
      background: #10131d;
      color: var(--text);
      border: 1px solid #2c3348;
      border-radius: 8px;
      padding: 8px 10px;
      font-size: 14px;
    }
    .toolbar button { cursor: pointer; }
    #chart {
      width: 100%;
      min-height: 52vh;
      height: 70vh;
    }
    .meta {
      color: var(--muted);
      font-size: 13px;
      margin-top: 8px;
    }
  </style>
</head>
<body>
  <div class='wrap'>
    <h2>VPN ratings (interactive)</h2>
    <div class='card'>
      <div class='toolbar'>
        <label>Период:
          <select id='days'>
            <option value='14'>14 дней</option>
            <option value='30' selected>30 дней</option>
            <option value='60'>60 дней</option>
            <option value='90'>90 дней</option>
          </select>
        </label>
        <label>Топ:
          <select id='topN'>
            <option value='5'>5</option>
            <option value='10' selected>10</option>
            <option value='15'>15</option>
            <option value='20'>20</option>
          </select>
        </label>
        <button id='refreshBtn'>Обновить</button>
      </div>
      <div id='chart'></div>
      <div class='meta' id='meta'>Загрузка...</div>
    </div>
  </div>
  <script>
    const chart = echarts.init(document.getElementById('chart'));

    async function loadChart() {
      try {
        const isMobile = window.matchMedia('(max-width: 768px)').matches;
        const days = document.getElementById('days').value;
        const topN = document.getElementById('topN').value;
        const res = await fetch(`/api/chart-data?days=${days}&top_n=${topN}`);
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }

        const payload = await res.json();
        if (!payload.series || payload.series.length === 0) {
          chart.clear();
          document.getElementById('meta').textContent =
            "Данные пока отсутствуют. Проверьте, что sync-hourly уже запускался.";
          return;
        }

        const option = {
          backgroundColor: 'transparent',
          tooltip: { trigger: 'axis' },
          legend: { show: false },
          grid: {
            left: 10,
            right: isMobile ? 82 : 102,
            top: 48,
            bottom: isMobile ? 72 : 60,
            containLabel: true
          },
          xAxis: {
            type: 'category',
            data: payload.labels,
            axisLabel: { color: '#c9d2ef', rotate: isMobile ? 35 : 40 }
          },
          yAxis: {
            type: 'value',
            min: 0,
            max: 36,
            axisLabel: { color: '#c9d2ef' }
          },
          series: payload.series.map((item) => ({
            name: item.name,
            type: 'line',
            smooth: true,
            connectNulls: true,
            showSymbol: false,
            endLabel: {
              show: true,
              formatter: '{a}',
              color: item.color || '#dce4ff',
              width: isMobile ? 108 : 124,
              overflow: 'break'
            },
            labelLayout: {
              moveOverlap: 'shiftY'
            },
            lineStyle: {
              width: 2
            },
            color: item.color || undefined,
            data: item.values
          }))
        };
        chart.setOption(option, true);

        document.getElementById('meta').textContent =
          `Источник: ${payload.source_name} · ` +
          `Диапазон: ${payload.date_range.from}..${payload.date_range.to} · ` +
          `Обновлено: ${payload.updated_at_utc}`;
      } catch (error) {
        chart.clear();
        document.getElementById('meta').textContent =
          `Не удалось загрузить график: ${error}. Попробуйте позже.`;
      }
    }

    document.getElementById('refreshBtn').addEventListener('click', loadChart);
    document.getElementById('days').addEventListener('change', loadChart);
    document.getElementById('topN').addEventListener('change', loadChart);
    window.addEventListener('resize', () => chart.resize());

    loadChart();
    setInterval(loadChart, 60 * 60 * 1000);
  </script>
</body>
</html>
"""
