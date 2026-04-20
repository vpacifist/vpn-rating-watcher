from __future__ import annotations

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from vpn_rating_watcher.charts.service import (
    CHART_MODE_DAILY,
    MAIN_LIVE_SOURCE_NAME,
    query_chart_scores,
    resolve_date_range,
)
from vpn_rating_watcher.db.session import get_session_factory
from vpn_rating_watcher.web.payload import build_chart_payload

app = FastAPI(title="VPN Availability Watcher", version="1.0.0")
app.mount("/static", StaticFiles(directory="src/vpn_rating_watcher/web/static"), name="static")


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
  <title>VPN availability watcher</title>
  <script src='https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js'></script>
  <script>
    (() => {
      const systemThemeMedia = typeof window.matchMedia === 'function'
        ? window.matchMedia('(prefers-color-scheme: dark)')
        : null;
      const hasSystemThemePreference = Boolean(
        systemThemeMedia && systemThemeMedia.media !== 'not all'
      );
      const initialTheme = hasSystemThemePreference
        ? (systemThemeMedia.matches ? 'dark' : 'light')
        : 'dark';
      document.documentElement.dataset.theme = initialTheme;
      document.documentElement.style.colorScheme = initialTheme;
    })();
  </script>
  <style>
    :root {
      color-scheme: light;
      --bg: #f7f9fc;
      --surface: #ffffff;
      --panel: #f2f5fa;
      --panel-border: #d8e0ee;
      --text: #0f172a;
      --muted: #64748b;
      --accent: #2563eb;
      --accent-strong: #1d4ed8;
      --accent-contrast: #eff6ff;
      --control-bg: #eef3fb;
      --control-hover: #e3ebf8;
      --control-active: #d7e3f8;
      --control-disabled-bg: #f4f7fc;
      --control-disabled-text: #94a3b8;
      --chart-axis: #475569;
      --chart-grid: rgba(71, 85, 105, 0.2);
      --chart-label-bg: rgba(255, 255, 255, 0.96);
      --chart-label-stroke: rgba(191, 201, 216, 0.96);
      --chart-line-shadow: rgba(99, 116, 143, 0.18);
      --chart-export-bg: #f7f9fc;
      --focus-ring: rgba(37, 99, 235, 0.35);
    }
    :root[data-theme='dark'] {
      color-scheme: dark;
      --bg: #111523;
      --surface: #161b2a;
      --panel: #1a2030;
      --panel-border: #2b3348;
      --text: #f2f5ff;
      --muted: #a7b0c6;
      --accent: #5ba4ff;
      --accent-strong: #4189e2;
      --accent-contrast: #0e1728;
      --control-bg: #141a29;
      --control-hover: #1d2537;
      --control-active: #263048;
      --chart-axis: #c4cdea;
      --chart-grid: rgba(196, 205, 234, 0.3);
      --chart-label-bg: rgba(14, 19, 34, 0.82);
      --chart-label-stroke: rgba(9, 13, 23, 0.95);
      --chart-line-shadow: rgba(9, 13, 23, 0.45);
      --chart-export-bg: #111523;
      --focus-ring: rgba(91, 164, 255, 0.4);
    }
    body {
      margin: 0;
      font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      padding: 12px;
      overflow-y: auto;
      scrollbar-gutter: stable;
    }
    .wrap {
      max-width: 1200px;
      margin: 0 auto;
    }
    .card {
      background: var(--panel);
      border: 1px solid var(--panel-border);
      border-radius: 12px;
      padding: 12px;
    }
    .toolbar {
      display: flex;
      flex-wrap: wrap;
      column-gap: 16px;
      row-gap: 8px;
      align-items: center;
      margin-bottom: 10px;
    }
    .toolbar-spacer {
      margin-left: auto;
    }
    .control-group {
      display: inline-flex;
      align-items: center;
      gap: 5px;
    }
    .theme-control-group {
      flex-direction: column;
      align-items: flex-start;
      gap: 4px;
    }
    .group-label {
      font-size: 13px;
      color: var(--muted);
    }
    .control-note {
      min-height: 16px;
      font-size: 12px;
      color: var(--muted);
    }
    .segmented {
      display: inline-flex;
      border: 1px solid var(--panel-border);
      border-radius: 8px;
      overflow: hidden;
      background: var(--control-bg);
    }
    .segmented button {
      background: var(--control-bg);
      color: var(--muted);
      border: 0;
      border-right: 1px solid var(--panel-border);
      padding: 5px 8px;
      font-size: 13px;
      cursor: pointer;
      transition: background 0.15s ease-in-out, color 0.15s ease-in-out;
    }
    .segmented button:hover {
      background: var(--control-hover);
      color: var(--text);
    }
    .segmented button:disabled {
      background: var(--control-disabled-bg);
      color: var(--control-disabled-text);
      cursor: not-allowed;
    }
    .segmented button.system-unavailable {
      box-shadow: inset 0 0 0 1px rgba(245, 158, 11, 0.32);
    }
    .segmented button:last-child {
      border-right: 0;
    }
    .segmented button:focus-visible,
    .screenshot-button:focus-visible {
      outline: 2px solid var(--focus-ring);
      outline-offset: 2px;
    }
    .segmented button.active {
      background: var(--accent);
      color: var(--accent-contrast);
      font-weight: 600;
    }
    .screenshot-button {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 0 8px;
      min-height: 26px;
      border-radius: 7px;
      border: 1px solid var(--panel-border);
      background: var(--control-bg);
      color: var(--text);
      cursor: pointer;
      transition: background 0.15s ease-in-out;
      font-size: 13px;
      font-weight: 600;
      text-transform: lowercase;
    }
    .screenshot-button:hover {
      background: var(--control-hover);
    }
    .screenshot-button:disabled {
      background: var(--control-disabled-bg);
      color: var(--control-disabled-text);
      cursor: not-allowed;
    }
    .screenshot-button svg {
      width: 15px;
      height: 15px;
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
    input, select, textarea, button {
      font: inherit;
    }
    table {
      border-collapse: collapse;
      width: 100%;
      background: var(--surface);
      color: var(--text);
    }
    th, td {
      border: 1px solid var(--panel-border);
      padding: 8px;
    }
    .modal {
      background: var(--surface);
      border: 1px solid var(--panel-border);
      color: var(--text);
    }
  </style>
  <link rel='icon' type='image/png' href='/static/favicon-96x96.png' sizes='96x96' />
  <link rel='icon' type='image/svg+xml' href='/static/favicon.svg' />
  <link rel='shortcut icon' href='/static/favicon.ico' />
  <link rel='apple-touch-icon' sizes='180x180' href='/static/apple-touch-icon.png' />
  <link rel="manifest" href="/static/site.webmanifest">
</head>
<body>
  <div class='wrap'>
    <h2>Доступность VPN</h2>
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
        <div class='control-group theme-control-group'>
          <span class='group-label'>Тема:</span>
          <div id='themeButtons' class='segmented'>
            <button type='button' data-theme='light'>light</button>
            <button type='button' data-theme='dark'>dark</button>
            <button type='button' data-theme='system'>system</button>
          </div>
          <div id='themeHint' class='control-note' aria-live='polite'></div>
        </div>
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
              stroke='currentColor'
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
    const OVERLAP_SPREAD_STEP = 0.67;
    const LIGHT_THEME_SERIES_COLORS = {
      'blancvpn': '#2563EB',
      'vpn liberty': '#DC2626',
      'vpn red shield': '#EA580C',
      'plusone vpn': '#E11D48',
      'наружу': '#EAB308',
      'durev vpn': '#3B82F6',
      'papervpn': '#65A30D',
      'vpn generator': '#0891B2',
      'tunnelbear': '#92400E',
      'amneziavpn': '#FBB26A'
    };
    const state = {
      days: 30,
      topN: 10,
      mode: 'daily',
      theme: 'dark',
      selectedSeriesName: null
    };
    const THEME_STORAGE_KEY = 'vrw-theme-preference';
    const systemThemeMedia = typeof window.matchMedia === 'function'
      ? window.matchMedia('(prefers-color-scheme: dark)')
      : null;
    const hasSystemThemePreference = Boolean(
      systemThemeMedia && systemThemeMedia.media !== 'not all'
    );

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

    function cssVar(name) {
      return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    }

    function setActiveThemeButton(themeButtons, preference) {
      themeButtons.forEach((button) => {
        button.classList.toggle('active', button.dataset.theme === preference);
      });
    }

    function syncSystemThemeAvailability(systemButton, themeHint) {
      const themeUnavailableText = 'system недоступен: браузер не сообщает тему устройства';
      systemButton.disabled = !hasSystemThemePreference;
      systemButton.classList.toggle('system-unavailable', !hasSystemThemePreference);
      systemButton.title = hasSystemThemePreference ? '' : themeUnavailableText;
      systemButton.setAttribute('aria-disabled', String(!hasSystemThemePreference));
      themeHint.textContent = hasSystemThemePreference ? '' : themeUnavailableText;
    }

    function getInitialThemePreference(storedPreference) {
      if (hasSystemThemePreference) {
        return 'system';
      }
      return (
        storedPreference === 'light' || storedPreference === 'dark'
          ? storedPreference
          : 'dark'
      );
    }

    function resolveActiveTheme(preference) {
      if (preference === 'system' && hasSystemThemePreference) {
        return systemThemeMedia.matches ? 'dark' : 'light';
      }
      return preference === 'light' ? 'light' : 'dark';
    }

    function applyTheme(preference, shouldReloadChart = true) {
      const normalizedPreference =
        preference === 'system' && !hasSystemThemePreference
          ? 'dark'
          : preference;
      state.theme = normalizedPreference;
      localStorage.setItem(THEME_STORAGE_KEY, normalizedPreference);
      const activeTheme = resolveActiveTheme(normalizedPreference);
      document.documentElement.dataset.theme = activeTheme;
      document.documentElement.style.colorScheme = activeTheme;
      if (shouldReloadChart) {
        loadChart();
      }
    }

    function setupThemeButtons() {
      const themeContainer = document.getElementById('themeButtons');
      const themeButtons = Array.from(themeContainer.querySelectorAll('button'));
      const systemButton = themeContainer.querySelector("[data-theme='system']");
      const themeHint = document.getElementById('themeHint');
      const stored = localStorage.getItem(THEME_STORAGE_KEY);
      const initialPreference = getInitialThemePreference(stored);
      syncSystemThemeAvailability(systemButton, themeHint);
      applyTheme(initialPreference, false);
      setActiveThemeButton(themeButtons, initialPreference);

      themeButtons.forEach((button) => {
        button.addEventListener('click', () => {
          const nextTheme = button.dataset.theme || 'dark';
          if (nextTheme === 'system' && !hasSystemThemePreference) {
            syncSystemThemeAvailability(systemButton, themeHint);
            return;
          }
          setActiveThemeButton(themeButtons, nextTheme);
          applyTheme(nextTheme);
        });
      });

      if (systemThemeMedia && typeof systemThemeMedia.addEventListener === 'function') {
        systemThemeMedia.addEventListener('change', () => {
          if (state.theme === 'system') {
            applyTheme('system');
          }
        });
      }
    }

    function buildChartTheme() {
      return {
        axisColor: cssVar('--chart-axis'),
        gridColor: cssVar('--chart-grid'),
        labelBackground: cssVar('--chart-label-bg'),
        labelStroke: cssVar('--chart-label-stroke'),
        lineShadow: cssVar('--chart-line-shadow'),
        textColor: cssVar('--text')
      };
    }

    function normalizeVpnName(name) {
      return String(name || '').trim().toLowerCase();
    }

    function resolveSeriesColor(item) {
      const activeTheme = resolveActiveTheme(state.theme);
      if (activeTheme !== 'light') {
        return item.color || undefined;
      }
      const lightColor = LIGHT_THEME_SERIES_COLORS[normalizeVpnName(item.name)];
      return lightColor || item.color || undefined;
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
          backgroundColor: cssVar('--chart-export-bg')
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
          return Math.max(0, Math.min(100, adjusted));
        })
      }));
    }

    function compareSeriesByRawValue(seriesByName, aName, bName, index) {
      const aSeriesItem = seriesByName.get(aName);
      const bSeriesItem = seriesByName.get(bName);
      const aRawValue = aSeriesItem?.values?.[index];
      const bRawValue = bSeriesItem?.values?.[index];
      const aValue = aRawValue == null ? Number.NEGATIVE_INFINITY : aRawValue;
      const bValue = bRawValue == null ? Number.NEGATIVE_INFINITY : bRawValue;
      if (aValue !== bValue) {
        return bValue - aValue;
      }
      return aName.localeCompare(bName);
    }

    function textMeasureContext() {
      if (!textMeasureContext.cached) {
        textMeasureContext.cached = document.createElement('canvas').getContext('2d');
      }
      return textMeasureContext.cached;
    }

    function measureTextWidth(text, { fontSize = 13, fontWeight = 400 } = {}) {
      const context = textMeasureContext();
      context.font = `${fontWeight} ${fontSize}px Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif`;
      return Math.ceil(context.measureText(String(text ?? '')).width);
    }

    function computeChartLayout(series, { isMobile }) {
      const axisLabelFontSize = isMobile ? 11 : 12;
      const axisNameFontSize = isMobile ? 12 : 13;
      const endLabelFontSize = isMobile ? 12 : 13;
      const endLabelPadX = isMobile ? 5 : 6;
      const endLabelPadY = 3;
      const tickValues = [0, 20, 40, 60, 80, 100];
      const tickWidth = Math.max(...tickValues.map((value) => (
        measureTextWidth(`${value}`, { fontSize: axisLabelFontSize })
      )));
      const yAxisLabelMargin = isMobile ? 6 : 8;
      const yAxisNameGap = isMobile ? 6 : 8;
      const gridLeft = Math.ceil(tickWidth + yAxisLabelMargin + axisNameFontSize + yAxisNameGap + 4);

      const maxLabelTextWidth = Math.max(
        0,
        ...series.map((item) => measureTextWidth(item.name, { fontSize: endLabelFontSize }))
      );
      const endLabelWidth = Math.max(32, maxLabelTextWidth + (endLabelPadX * 2));
      const endLabelDistance = isMobile ? 6 : 8;
      const gridRight = endLabelWidth + endLabelDistance + 6;

      return {
        axisLabelFontSize,
        axisNameFontSize,
        endLabelDistance,
        endLabelFontSize,
        endLabelPadX,
        endLabelPadY,
        endLabelWidth,
        gridBottom: isMobile ? 58 : 50,
        gridLeft,
        gridRight,
        gridTop: isMobile ? 16 : 14,
        yAxisLabelMargin,
        yAxisNameGap,
      };
    }

    function computeEndLabelPositions(series, { layout, chartHeight }) {
      if (!Array.isArray(series) || series.length < 2) {
        return new Map();
      }

      const lastIndex = Math.max(0, ...series.map((item) => item.values.length - 1));
      const plotHeight = Math.max(1, chartHeight - layout.gridTop - layout.gridBottom);
      const labelHeight = Math.ceil(layout.endLabelFontSize + (layout.endLabelPadY * 2) + 2);
      const minCenterGap = labelHeight + 1;
      const upperCenter = layout.gridTop + (labelHeight / 2);
      const lowerCenter = chartHeight - layout.gridBottom - (labelHeight / 2);
      const valueToCenterY = (value) => layout.gridTop + ((100 - value) / 100) * plotHeight;
      const ranked = series
        .map((item) => {
          const rawValue = item.values[lastIndex];
          const plotValue = item.plotValues?.[lastIndex];
          if (rawValue == null || plotValue == null) {
            return null;
          }
          return {
            name: item.name,
            rawValue,
            plotValue,
            preferredCenter: valueToCenterY(plotValue),
          };
        })
        .filter(Boolean)
        .sort((a, b) => {
          if (a.plotValue !== b.plotValue) {
            return b.plotValue - a.plotValue;
          }
          if (a.rawValue !== b.rawValue) {
            return b.rawValue - a.rawValue;
          }
          return a.name.localeCompare(b.name);
        });

      if (ranked.length < 2) {
        return new Map();
      }

      const positioned = ranked.map((entry) => entry.preferredCenter);
      for (let i = 1; i < positioned.length; i += 1) {
        positioned[i] = Math.max(positioned[i], positioned[i - 1] + minCenterGap);
      }
      if (positioned[positioned.length - 1] > lowerCenter) {
        const shiftUp = positioned[positioned.length - 1] - lowerCenter;
        for (let i = 0; i < positioned.length; i += 1) {
          positioned[i] -= shiftUp;
        }
      }
      for (let i = positioned.length - 2; i >= 0; i -= 1) {
        positioned[i] = Math.min(positioned[i], positioned[i + 1] - minCenterGap);
      }
      if (positioned[0] < upperCenter) {
        const shiftDown = upperCenter - positioned[0];
        for (let i = 0; i < positioned.length; i += 1) {
          positioned[i] += shiftDown;
        }
      }

      return new Map(ranked.map((entry, idx) => [entry.name, positioned[idx]]));
    }

    function compareSeriesByVisibleValue(seriesByName, aName, bName, index) {
      const aSeriesItem = seriesByName.get(aName);
      const bSeriesItem = seriesByName.get(bName);
      const aPlotValue = aSeriesItem?.plotValues?.[index];
      const bPlotValue = bSeriesItem?.plotValues?.[index];
      const aVisibleValue = aPlotValue == null ? Number.NEGATIVE_INFINITY : aPlotValue;
      const bVisibleValue = bPlotValue == null ? Number.NEGATIVE_INFINITY : bPlotValue;
      if (aVisibleValue !== bVisibleValue) {
        return bVisibleValue - aVisibleValue;
      }
      return compareSeriesByRawValue(seriesByName, aName, bName, index);
    }

    function buildTooltipFormatter(series) {
      const escapeRichText = (value) => String(value ?? '').replace(/([{}|\\\\])/g, '\\\\$1');

      return (params) => {
        if (!Array.isArray(params) || params.length === 0) {
          return '';
        }
        const axisValue = params[0].axisValue;
        const index = params[0].dataIndex;
        const sorted = [...params].sort((a, b) => {
          const aSeriesItem = series.find((entry) => entry.name === a.seriesName);
          const bSeriesItem = series.find((entry) => entry.name === b.seriesName);
          const aRawValue = aSeriesItem?.values?.[index];
          const bRawValue = bSeriesItem?.values?.[index];
          const aValue = aRawValue == null ? Number.NEGATIVE_INFINITY : aRawValue;
          const bValue = bRawValue == null ? Number.NEGATIVE_INFINITY : bRawValue;
          if (aValue !== bValue) {
            return bValue - aValue;
          }
          return a.seriesName.localeCompare(b.seriesName);
        });
        const rows = sorted.map((item) => {
          const seriesItem = series.find((entry) => entry.name === item.seriesName);
          const rawValue = seriesItem?.values?.[index];
          const formattedValue = rawValue == null ? '—' : `${Math.round(rawValue)}%`;
          const safeName = escapeRichText(item.seriesName);
          const safeValue = escapeRichText(formattedValue);
          return `{name|${safeName}}{value|${safeValue}}`;
        }).join('\\n');
        return `{header|${escapeRichText(formatRuDate(axisValue))}}\\n${rows}`;
      };
    }

    function buildHtmlTooltipFormatter(series) {
      const escapeHtml = (value) => String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');

      const seriesByName = new Map(series.map((item) => [item.name, item]));

      return (params) => {
        if (!Array.isArray(params) || params.length === 0) {
          return '';
        }
        const axisValue = params[0].axisValue;
        const index = params[0].dataIndex;
        const sorted = [...params].sort((a, b) => (
          compareSeriesByVisibleValue(seriesByName, a.seriesName, b.seriesName, index)
        ));
        const rows = sorted.map((item) => {
          const seriesItem = seriesByName.get(item.seriesName);
          const rawValue = seriesItem?.values?.[index];
          const markerColor = escapeHtml(
            item.color || resolveSeriesColor(seriesItem || {}) || cssVar('--accent')
          );
          const formattedValue = rawValue == null ? '&mdash;' : escapeHtml(`${Math.round(rawValue)}%`);
          const markerStyle = [
            'width:8px',
            'height:8px',
            'border-radius:999px',
            'flex:0 0 8px',
            `background:${markerColor}`,
          ].join(';');
          const nameStyle = [
            'flex:1 1 auto',
            'min-width:0',
            'overflow:hidden',
            'text-overflow:ellipsis',
            'white-space:nowrap',
            `color:${cssVar('--text')}`,
          ].join(';');
          const valueStyle = [
            'flex:0 0 auto',
            'margin-left:12px',
            'font-weight:700',
            `color:${cssVar('--text')}`,
            'text-align:right',
          ].join(';');
          return (
            "<div style='display:flex;align-items:center;gap:10px;min-width:0;'>" +
              `<span style='${markerStyle}'></span>` +
              `<span style='${nameStyle}'>${escapeHtml(item.seriesName)}</span>` +
              `<span style='${valueStyle}'>${formattedValue}</span>` +
            "</div>"
          );
        }).join("<div style='height:8px;'></div>");
        const headerStyle = [
          'font-size:12px',
          'font-weight:700',
          'line-height:1.35',
          'margin-bottom:10px',
          `color:${cssVar('--text')}`,
        ].join(';');
        return (
          "<div style='min-width:200px;max-width:260px;padding:12px 14px;'>" +
            `<div style='${headerStyle}'>${escapeHtml(formatRuDate(axisValue))}</div>` +
            `<div style='display:flex;flex-direction:column;'>${rows}</div>` +
          "</div>"
        );
      };
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
        const chartTheme = buildChartTheme();
        const layout = computeChartLayout(payload.series, { isMobile });
        const spreadSeries = spreadOverlappingSeries(payload.series);
        const endLabelCenters = computeEndLabelPositions(
          spreadSeries,
          { layout, chartHeight: chart.getHeight() }
        );

        const option = {
          backgroundColor: 'transparent',
          tooltip: {
            trigger: 'axis',
            renderMode: 'html',
            confine: true,
            transitionDuration: 0,
            backgroundColor: chartTheme.labelBackground,
            borderColor: 'transparent',
            borderWidth: 0,
            textStyle: {
              color: chartTheme.textColor,
              fontSize: 12,
              lineHeight: 18
            },
            padding: 0,
            extraCssText: [
              'border-radius:12px',
              'box-shadow:0 12px 30px rgba(15, 23, 42, 0.18)',
              'backdrop-filter:blur(10px)',
              '-webkit-backdrop-filter:blur(10px)',
              'overflow:hidden'
            ].join(';'),
            formatter: buildHtmlTooltipFormatter(spreadSeries)
          },
          legend: { show: false },
          grid: {
            left: layout.gridLeft,
            right: layout.gridRight,
            top: layout.gridTop,
            bottom: layout.gridBottom,
            containLabel: false
          },
          xAxis: {
            type: 'category',
            data: payload.labels,
            axisLine: { lineStyle: { color: chartTheme.gridColor } },
            axisTick: { lineStyle: { color: chartTheme.gridColor } },
            axisLabel: {
              color: chartTheme.axisColor,
              fontSize: layout.axisLabelFontSize,
              rotate: isMobile ? 35 : 40
            }
          },
          yAxis: {
            type: 'value',
            min: 0,
            max: 100,
            name: 'Доступность',
            nameLocation: 'middle',
            nameRotate: 90,
            nameGap: layout.yAxisNameGap,
            nameTextStyle: {
              color: chartTheme.axisColor,
              fontSize: layout.axisNameFontSize,
              fontWeight: 600
            },
            axisLine: { lineStyle: { color: chartTheme.gridColor } },
            axisTick: { show: false },
            axisLabel: {
              color: chartTheme.axisColor,
              fontSize: layout.axisLabelFontSize,
              margin: layout.yAxisLabelMargin
            },
            splitLine: {
              lineStyle: {
                color: chartTheme.gridColor,
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
            clip: false,
            endLabel: {
              show: true,
              formatter: '{a}',
              color: resolveSeriesColor(item),
              textBorderWidth: 0,
              backgroundColor: chartTheme.labelBackground,
              borderColor: resolveSeriesColor(item),
              borderWidth: 1,
              borderRadius: 4,
              distance: layout.endLabelDistance,
              fontSize: layout.endLabelFontSize,
              padding: [layout.endLabelPadY, layout.endLabelPadX],
              width: layout.endLabelWidth
            },
            labelLayout: (params) => {
              const labelCenter = endLabelCenters.get(item.name);
              if (labelCenter == null || params?.labelRect == null) {
                return {
                  moveOverlap: 'none',
                  hideOverlap: false
                };
              }
              return {
                y: labelCenter - (params.labelRect.height / 2),
                moveOverlap: 'none',
                hideOverlap: false
              };
            },
            lineStyle: {
              width: window.devicePixelRatio >= 2 ? 2.6 : 3,
              shadowColor: chartTheme.lineShadow,
              shadowBlur: 3
            },
            emphasis: {
              focus: 'series',
              lineStyle: {
                width: window.devicePixelRatio >= 2 ? 2.6 : 3,
                shadowBlur: 0
              }
            },
            blur: {
              lineStyle: { opacity: 0.08 },
              itemStyle: { opacity: 0.08 },
              label: { opacity: 0.08 },
              endLabel: { opacity: 0.08 }
            },
            color: resolveSeriesColor(item),
            data: item.plotValues
          }))
        };
        chart.setOption(option, true);
        chart.off('click');
        chart.getZr().off('click');
        chart.on('click', (params) => {
          if (state.selectedSeriesName) {
            state.selectedSeriesName = null;
            chart.dispatchAction({ type: 'downplay', seriesIndex: 'all' });
            return;
          }
          if (params?.componentType === 'series' && params.seriesName) {
            state.selectedSeriesName = params.seriesName;
            const selectedIndex = spreadSeries.findIndex((item) => item.name === params.seriesName);
            chart.dispatchAction({ type: 'downplay', seriesIndex: 'all' });
            if (selectedIndex >= 0) {
              chart.dispatchAction({ type: 'highlight', seriesIndex: selectedIndex });
            }
          }
        });
        chart.getZr().on('click', (event) => {
          if (!state.selectedSeriesName || event.target) {
            return;
          }
          state.selectedSeriesName = null;
          chart.dispatchAction({ type: 'downplay', seriesIndex: 'all' });
        });

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
    setupThemeButtons();
    setupScreenshotButton();
    window.addEventListener('resize', () => chart.resize());

    loadChart();
    setInterval(loadChart, 60 * 60 * 1000);
  </script>
</body>
</html>
"""
