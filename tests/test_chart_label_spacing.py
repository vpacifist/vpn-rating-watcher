from __future__ import annotations

import matplotlib.pyplot as plt

from vpn_rating_watcher.charts.service import (
    _compute_label_positions,
    _estimate_label_margin_x_units,
    _label_min_gap_data_units,
)


def test_label_margin_does_not_keep_old_minimum_date_gap() -> None:
    margin = _estimate_label_margin_x_units(
        date_count=28,
        plot_width_inches=11.2,
        label_text_width_inches=0.0,
    )

    assert margin < 1.0


def test_label_margin_grows_with_label_width() -> None:
    short_margin = _estimate_label_margin_x_units(
        date_count=28,
        plot_width_inches=11.2,
        label_text_width_inches=0.4,
    )
    long_margin = _estimate_label_margin_x_units(
        date_count=28,
        plot_width_inches=11.2,
        label_text_width_inches=1.4,
    )

    assert long_margin > short_margin


def test_label_positioning_keeps_requested_minimum_gap() -> None:
    positioned = _compute_label_positions(
        [64.0, 64.2, 64.4],
        lower=1.2,
        upper=100.8,
        min_gap=2.5,
    )

    ordered = sorted(positioned)
    assert ordered[1] - ordered[0] >= 2.5
    assert ordered[2] - ordered[1] >= 2.5


def test_label_min_gap_uses_rendered_text_height_plus_pixel_gap() -> None:
    fig, ax = plt.subplots(figsize=(6, 4), dpi=180)
    try:
        ax.set_ylim(0, 100)
        min_gap = _label_min_gap_data_units(ax, fontsize=8, pixel_gap=1)
    finally:
        plt.close(fig)

    assert min_gap > 1.2
