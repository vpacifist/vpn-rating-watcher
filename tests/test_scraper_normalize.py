from vpn_rating_watcher.scraper.normalize import (
    build_table_hash,
    normalize_row_payload,
    normalize_text,
    parse_result,
)


def test_parse_result() -> None:
    score, score_max, score_pct = parse_result(" 35 / 36 ")
    assert score == 35
    assert score_max == 36
    assert score_pct == 0.972222


def test_normalize_text_compacts_whitespace() -> None:
    assert normalize_text("  a   b\n c ") == "a b c"


def test_normalized_payload_semantic_stability() -> None:
    row_1 = normalize_row_payload(
        {
            "rank_position": 1,
            "vpn_name": "VPN Name",
            "checked_at_raw": "28.03.2026 15:00",
            "result_raw": "35 / 36",
            "metadata": {"Z": "x", "a": "  y "},
        }
    )
    row_2 = normalize_row_payload(
        {
            "rank_position": 1,
            "vpn_name": " vpn name ",
            "checked_at_raw": "28.03.2026   15:00",
            "result_raw": "35/36",
            "metadata": {"a": "y", "z": "x"},
        }
    )

    assert row_1.model_dump(exclude_none=True) == row_2.model_dump(exclude_none=True)


def test_table_hash_is_deterministic() -> None:
    row = normalize_row_payload(
        {
            "rank_position": 1,
            "vpn_name": "vpn a",
            "checked_at_raw": "28.03.2026 15:00",
            "result_raw": "35/36",
            "metadata": {},
        }
    )
    hash_1 = build_table_hash([row])
    hash_2 = build_table_hash([row])
    assert hash_1 == hash_2
