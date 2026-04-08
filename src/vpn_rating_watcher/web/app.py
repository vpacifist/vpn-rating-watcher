from __future__ import annotations

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

from vpn_rating_watcher.charts.service import (
    CHART_MODE_DAILY,
    MAIN_LIVE_SOURCE_NAME,
    query_chart_scores,
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
    mode: str = Query(default=CHART_MODE_DAILY, pattern="^(daily|median_3d)$"),
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
        rows = query_chart_scores(
            session=session,
            start_date=date_range.start_date,
            end_date=date_range.end_date,
            source_name=source_name,
            mode=mode,
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
    mode: str = Query(default=CHART_MODE_DAILY, pattern="^(daily|median_3d)$"),
) -> dict:
    """Backward-compatible alias for older clients."""
    return api_chart_data(days=days, source_name=source_name, top_n=top_n, mode=mode)


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
    .toolbar-spacer {
      margin-left: auto;
    }
    .control-group {
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }
    .group-label {
      font-size: 14px;
      color: var(--text);
    }
    .segmented {
      display: inline-flex;
      border: 1px solid #2c3348;
      border-radius: 8px;
      overflow: hidden;
      background: #10131d;
    }
    .segmented button {
      background: #10131d;
      color: var(--text);
      border: 0;
      border-right: 1px solid #2c3348;
      padding: 8px 10px;
      font-size: 14px;
      cursor: pointer;
    }
    .segmented button:last-child {
      border-right: 0;
    }
    .segmented button.active {
      background: var(--accent);
      color: #09101f;
      font-weight: 600;
    }
    .screenshot-button {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 0 12px;
      min-height: 38px;
      border-radius: 8px;
      border: 1px solid #2c3348;
      background: #10131d;
      color: var(--text);
      cursor: pointer;
      transition: background 0.15s ease-in-out;
      font-size: 14px;
      font-weight: 600;
      text-transform: lowercase;
    }
    .screenshot-button:hover {
      background: #1a2030;
    }
    .screenshot-button svg {
      width: 18px;
      height: 18px;
      display: block;
    }
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
    .meta a {
      color: inherit;
    }
  </style>
</head>
<body>
  <div class='wrap'>
    <h2>Рейтинг VPN</h2>
    <div class='card'>
      <div class='toolbar'>
        <div class='control-group'>
          <span class='group-label'>Период:</span>
          <div id='daysButtons' class='segmented'>
            <button type='button' data-days='7'>7d</button>
            <button type='button' data-days='14'>14d</button>
            <button type='button' data-days='30' class='active'>30d</button>
            <button type='button' data-days='90'>90d</button>
          </div>
        </div>
        <div class='control-group'>
          <span class='group-label'>Топ:</span>
          <div id='topButtons' class='segmented'>
            <button type='button' data-top-n='5'>5</button>
            <button type='button' data-top-n='10' class='active'>10</button>
          </div>
        </div>
        <div class='control-group'>
          <span class='group-label'>Режим:</span>
          <div id='modeButtons' class='segmented'>
            <button type='button' data-mode='daily' class='active'>daily</button>
            <button type='button' data-mode='median_3d'>median 3d</button>
          </div>
        </div>
        <div class='toolbar-spacer'></div>
        <button
          id='saveChartButton'
          class='screenshot-button'
          type='button'
          aria-label='Сохранить скриншот графика'
          title='Сохранить скриншот'
        >
          <span>скриншот</span>
          <svg viewBox='0 0 24 24' aria-hidden='true'>
            <path
              d='M12 3v12m0 0 4-4m-4 4-4-4M5 14v3a3 3 0 0 0 3 3h8a3 3 0 0 0 3-3v-3'
              fill='none'
              stroke='#ffffff'
              stroke-width='2.2'
              stroke-linecap='round'
              stroke-linejoin='round'
            />
          </svg>
        </button>
      </div>
      <div id='chart'></div>
      <div class='meta' id='meta'>Загрузка...</div>
    </div>
  </div>
  <script>
    const chart = echarts.init(document.getElementById('chart'));
    const OVERLAP_SPREAD_STEP = 0.24;
    const state = {
      days: 30,
      topN: 10,
      mode: 'daily'
    };

    function setupSegmentedButtons(containerId, valueAttribute, stateKey) {
      const container = document.getElementById(containerId);
      const buttons = Array.from(container.querySelectorAll('button'));

      const activateValue = (rawValue) => {
        const value = Number.isNaN(Number(rawValue)) ? rawValue : Number(rawValue);
        state[stateKey] = value;
        buttons.forEach((button) => {
          const buttonValue = button.dataset[valueAttribute];
          button.classList.toggle('active', String(buttonValue) === String(rawValue));
        });
        loadChart();
      };

      buttons.forEach((button) => {
        button.addEventListener('click', () => activateValue(button.dataset[valueAttribute]));
      });
    }

    const RU_MONTHS_SHORT = [
      'янв', 'фев', 'мар', 'апр', 'май', 'июн',
      'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'
    ];

    function formatRuDate(isoDate) {
      const date = new Date(`${isoDate}T00:00:00Z`);
      const day = date.getUTCDate();
      const month = RU_MONTHS_SHORT[date.getUTCMonth()];
      const year = date.getUTCFullYear();
      return `${day} ${month} ${year}`;
    }

    function formatRuDateTime(isoDateTime) {
      const date = new Date(isoDateTime);
      const day = date.getUTCDate();
      const month = RU_MONTHS_SHORT[date.getUTCMonth()];
      const year = date.getUTCFullYear();
      const datePart = `${day} ${month} ${year}`;
      const timePart = new Intl.DateTimeFormat('ru-RU', {
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
        timeZone: 'UTC'
      }).format(date);
      return `${datePart} ${timePart} UTC`;
    }

    function setupScreenshotButton() {
      const saveButton = document.getElementById('saveChartButton');
      saveButton.addEventListener('click', () => {
        const dataUrl = chart.getDataURL({
          type: 'png',
          pixelRatio: 2,
          backgroundColor: '#0f111a'
        });
        const link = document.createElement('a');
        const timestamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
        link.href = dataUrl;
        link.download = `vpn-rating-${timestamp}.png`;
        document.body.appendChild(link);
        link.click();
        link.remove();
      });
    }

    function sourceHtml(sourceName) {
      if (sourceName === 'maximkatz') {
        return (
          "Источник: <a href='https://vpn.maximkatz.com/' " +
          "target='_blank' rel='noopener noreferrer'>maximkatz</a>"
        );
      }
      return `Источник: ${sourceName}`;
    }

    function spreadOverlappingSeries(series) {
      if (!Array.isArray(series) || series.length < 2) {
        return series;
      }

      const maxLen = Math.max(...series.map((item) => item.values.length));
      const offsetMaps = Array.from({ length: series.length }, () => new Map());

      for (let index = 0; index < maxLen; index += 1) {
        const sameValueGroups = new Map();
        series.forEach((item, seriesIndex) => {
          const value = item.values[index];
          if (value == null) return;
          const bucket = sameValueGroups.get(value) || [];
          bucket.push({ seriesIndex, name: item.name });
          sameValueGroups.set(value, bucket);
        });

        sameValueGroups.forEach((members) => {
          if (members.length < 2) return;
          members.sort((a, b) => a.name.localeCompare(b.name));
          const center = (members.length - 1) / 2;
          members.forEach((member, order) => {
            const offset = (order - center) * OVERLAP_SPREAD_STEP;
            offsetMaps[member.seriesIndex].set(index, offset);
          });
        });
      }

      return series.map((item, seriesIndex) => ({
        ...item,
        plotValues: item.values.map((value, index) => {
          if (value == null) return null;
          const adjusted = value + (offsetMaps[seriesIndex].get(index) || 0);
          return Math.max(0, Math.min(36, adjusted));
        })
      }));
    }

    async function loadChart() {
      try {
        const isMobile = window.matchMedia('(max-width: 768px)').matches;
        const query = `/api/chart-data?days=${state.days}&top_n=${state.topN}&mode=${state.mode}`;
        const res = await fetch(query);
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
        const spreadSeries = spreadOverlappingSeries(payload.series);

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
            axisLabel: { color: '#c9d2ef' },
            splitLine: {
              lineStyle: {
                color: 'rgba(201, 210, 239, 0.28)',
                width: 1
              }
            }
          },
          series: spreadSeries.map((item, index) => ({
            name: item.name,
            type: 'line',
            smooth: true,
            connectNulls: true,
            showSymbol: false,
            z: 10 + index,
            endLabel: {
              show: true,
              formatter: '{a}',
              color: item.color || '#dce4ff',
              textBorderColor: 'rgba(11, 14, 25, 0.95)',
              textBorderWidth: 2,
              backgroundColor: 'rgba(11, 14, 25, 0.78)',
              borderRadius: 4,
              padding: [2, 6],
              width: isMobile ? 108 : 124,
              overflow: 'break'
            },
            labelLayout: {
              moveOverlap: 'shiftY'
            },
            lineStyle: {
              width: 3,
              shadowColor: 'rgba(11, 14, 25, 0.4)',
              shadowBlur: 3
            },
            color: item.color || undefined,
            data: item.plotValues
          }))
        };
        chart.setOption(option, true);

        document.getElementById('meta').innerHTML =
          `${sourceHtml(payload.source_name)} · ` +
          `Режим: ${state.mode === 'median_3d' ? 'median 3d' : 'daily'} · ` +
          `Диапазон: ${formatRuDate(payload.date_range.from)} ` +
          `– ${formatRuDate(payload.date_range.to)} · ` +
          `Обновлено: ${formatRuDateTime(payload.updated_at_utc)}`;
      } catch (error) {
        chart.clear();
        document.getElementById('meta').textContent =
          `Не удалось загрузить график: ${error}. Попробуйте позже.`;
      }
    }

    setupSegmentedButtons('daysButtons', 'days', 'days');
    setupSegmentedButtons('topButtons', 'topN', 'topN');
    setupSegmentedButtons('modeButtons', 'mode', 'mode');
    setupScreenshotButton();
    window.addEventListener('resize', () => chart.resize());

    loadChart();
    setInterval(loadChart, 60 * 60 * 1000);
  </script>
</body>
</html>
"""
