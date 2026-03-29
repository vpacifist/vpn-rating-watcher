from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable

from vpn_rating_watcher.scraper.models import NormalizedRow

RESULT_RE = re.compile(r"(\d{1,3})\s*/\s*(\d{1,3})")
SPACE_RE = re.compile(r"\s+")


def normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    compact = SPACE_RE.sub(" ", value).strip()
    return compact or None


def parse_result(result_raw: str) -> tuple[int, int, float]:
    match = RESULT_RE.search(result_raw)
    if not match:
        raise ValueError(f"Could not parse score from: {result_raw}")

    score = int(match.group(1))
    score_max = int(match.group(2))
    score_pct = 0.0 if score_max == 0 else round(score / score_max, 6)
    return score, score_max, score_pct


def normalize_row_payload(row: dict) -> NormalizedRow:
    normalized: dict = {}
    for key, value in row.items():
        if key == "metadata":
            metadata = value or {}
            normalized["metadata"] = {
                str(k).strip().lower(): normalize_text(str(v)) or ""
                for k, v in sorted(metadata.items(), key=lambda item: str(item[0]).lower())
                if normalize_text(str(v))
            }
            continue

        if isinstance(value, str):
            normalized[key] = normalize_text(value)
        else:
            normalized[key] = value

    normalized["vpn_name"] = (normalized.get("vpn_name") or "").casefold()
    normalized["result_raw"] = normalize_text(normalized.get("result_raw"))
    if not normalized["result_raw"]:
        raise ValueError("result_raw is empty")

    score, score_max, score_pct = parse_result(normalized["result_raw"])
    normalized["score"] = score
    normalized["score_max"] = score_max
    normalized["score_pct"] = score_pct

    return NormalizedRow.model_validate(normalized)


def build_table_hash(rows: Iterable[NormalizedRow]) -> str:
    payload = [row.model_dump(mode="json", exclude_none=True) for row in rows]
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
