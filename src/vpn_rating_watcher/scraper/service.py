from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import Page, TimeoutError, sync_playwright

from vpn_rating_watcher.scraper.models import NormalizedRow, ScrapeResult
from vpn_rating_watcher.scraper.normalize import (
    RESULT_RE,
    build_table_hash,
    normalize_row_payload,
    normalize_text,
)

UTC = timezone.utc


def _pick_table_rows(page: Page) -> list:
    candidate_rows: list = []
    for table in page.locator("table").all():
        rows = table.locator("tbody tr").all()
        if not rows:
            rows = table.locator("tr").all()

        row_payloads = []
        for row in rows:
            visible = row.is_visible()
            row_text = normalize_text(row.inner_text())
            if not visible or not row_text:
                continue
            if RESULT_RE.search(row_text):
                row_payloads.append(row)

        if len(row_payloads) > len(candidate_rows):
            candidate_rows = row_payloads

    return candidate_rows


def _extract_row(row, rank_position: int, source_url: str) -> NormalizedRow:
    cells = [normalize_text(cell.inner_text()) for cell in row.locator("td").all()]
    cells = [value for value in cells if value]
    row_text = normalize_text(row.inner_text()) or ""

    result_match = RESULT_RE.search(row_text)
    if not result_match:
        raise ValueError(f"Could not find result in row #{rank_position}: {row_text}")
    result_raw = f"{result_match.group(1)}/{result_match.group(2)}"

    anchors = row.locator("a").all()
    details_url = None
    vpn_name = None
    if anchors:
        vpn_name = normalize_text(anchors[0].inner_text())
        href = anchors[0].get_attribute("href")
        if href:
            details_url = urljoin(source_url, href)

    if not vpn_name and cells:
        vpn_name = cells[0]

    checked_at_raw = next(
        (
            value
            for value in cells
            if value != result_raw
            and any(char.isdigit() for char in value)
            and (":" in value or "." in value)
        ),
        None,
    )

    metadata: dict[str, str] = {}
    for value in cells:
        if value in {vpn_name, checked_at_raw, result_raw}:
            continue
        low = value.casefold()
        if "₽" in value or "$" in value or "€" in value:
            metadata.setdefault("price_raw", value)
        elif "gb" in low or "tb" in low or "mb" in low or "траф" in low:
            metadata.setdefault("traffic_raw", value)
        elif "device" in low or "устрой" in low:
            metadata.setdefault("devices_raw", value)
        else:
            metadata[f"extra_{len(metadata) + 1}"] = value

    payload = {
        "rank_position": rank_position,
        "vpn_name": vpn_name,
        "checked_at_raw": checked_at_raw,
        "result_raw": result_raw,
        "price_raw": metadata.pop("price_raw", None),
        "traffic_raw": metadata.pop("traffic_raw", None),
        "devices_raw": metadata.pop("devices_raw", None),
        "details_url": details_url,
        "metadata": metadata,
    }

    return normalize_row_payload(payload)


def scrape_once(
    source_url: str,
    artifacts_dir: str = "artifacts",
    headless: bool = True,
) -> ScrapeResult:
    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(artifacts_dir) / ts
    run_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        page = browser.new_page(viewport={"width": 1600, "height": 1200})
        try:
            page.goto(source_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_load_state("networkidle", timeout=30_000)
            page.wait_for_selector("table", state="visible", timeout=30_000)
        except TimeoutError as exc:
            browser.close()
            raise RuntimeError(f"Could not load visible table on {source_url}") from exc

        html = page.content()
        (run_dir / "rendered.html").write_text(html, encoding="utf-8")
        page.screenshot(path=str(run_dir / "screenshot.png"), full_page=True)

        rows = _pick_table_rows(page)
        parsed_rows: list[NormalizedRow] = []
        for idx, row in enumerate(rows, start=1):
            parsed_rows.append(_extract_row(row, rank_position=idx, source_url=source_url))

        table_hash = build_table_hash(parsed_rows)

        payload = {
            "source_url": source_url,
            "scraped_at_utc": datetime.now(tz=UTC).isoformat(),
            "table_hash": table_hash,
            "row_count": len(parsed_rows),
            "rows": [row.model_dump(mode="json", exclude_none=True) for row in parsed_rows],
            "artifacts_dir": str(run_dir),
        }
        (run_dir / "normalized.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        browser.close()

    return ScrapeResult.model_validate(payload)
