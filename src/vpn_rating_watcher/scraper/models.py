from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl


class NormalizedRow(BaseModel):
    rank_position: int
    vpn_name: str
    checked_at_raw: str | None = None
    result_raw: str
    score: int
    score_max: int
    score_pct: float
    price_raw: str | None = None
    traffic_raw: str | None = None
    devices_raw: str | None = None
    details_url: HttpUrl | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class ScrapeResult(BaseModel):
    source_url: HttpUrl
    scraped_at_utc: str
    table_hash: str
    row_count: int
    rows: list[NormalizedRow]
    artifacts_dir: str
