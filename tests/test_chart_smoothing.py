from __future__ import annotations

import numpy as np

from vpn_rating_watcher.charts.service import _catmull_rom_segment, _smooth_curve_points


def test_smooth_curve_points_returns_original_for_short_series() -> None:
    x_values = np.array([0, 1], dtype=float)
    y_values = np.array([21, 22], dtype=float)

    smooth_x, smooth_y = _smooth_curve_points(x_values, y_values)

    assert np.array_equal(smooth_x, x_values)
    assert np.array_equal(smooth_y, y_values)


def test_smooth_curve_points_keeps_endpoints_for_long_series() -> None:
    x_values = np.array([0, 1, 2, 3], dtype=float)
    y_values = np.array([22, 24, 23, 25], dtype=float)

    smooth_x, smooth_y = _smooth_curve_points(x_values, y_values, steps_per_segment=5)

    assert smooth_x[0] == x_values[0]
    assert smooth_y[0] == y_values[0]
    assert smooth_x[-1] == x_values[-1]
    assert smooth_y[-1] == y_values[-1]
    assert smooth_x.size > x_values.size
    assert smooth_y.size > y_values.size
    assert np.all(np.diff(smooth_x) > 0)


def test_catmull_rom_segment_matches_segment_endpoints() -> None:
    t_values = np.array([0.0, 1.0], dtype=float)
    values = _catmull_rom_segment(10.0, 20.0, 30.0, 40.0, t_values)

    assert values[0] == 20.0
    assert values[1] == 30.0
