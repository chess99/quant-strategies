from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "run_study.py"


def load_module():
    spec = importlib.util.spec_from_file_location("star50_single_asset_study", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_execution_target_uses_previous_observation_only():
    module = load_module()
    dates = pd.date_range("2024-01-02", periods=6, freq="B")
    observation = pd.Series([0, 0, 1, 1, 0, 1], index=dates, dtype=float)

    target = module.execution_target(observation, delay=1)

    assert target.tolist() == [0, 0, 0, 1, 1, 0]


def test_macd_cross_is_diff_above_dea_not_diff_above_zero():
    module = load_module()
    close = pd.Series(
        [10, 9, 8, 7, 6, 6.2, 6.4, 6.6, 6.8, 7.0, 7.2, 7.4],
        index=pd.date_range("2024-01-02", periods=12, freq="B"),
        dtype=float,
    )

    cross = module.macd_cross_position(close, fast=3, slow=6, signal=3)
    zero = module.macd_zero_position(close, fast=3, slow=6)

    assert ((cross == 1.0) & (zero == 0.0)).any()


def test_donchian_breakout_excludes_current_bar_from_channel():
    module = load_module()
    dates = pd.date_range("2024-01-02", periods=7, freq="B")
    frame = pd.DataFrame(
        {
            "adjusted_high": [10, 11, 12, 13, 14, 13, 12],
            "adjusted_low": [9, 10, 11, 12, 13, 10, 8],
            "adjusted_close": [9.5, 10.5, 11.5, 13.0, 13.5, 10.0, 8.0],
        },
        index=dates,
    )

    position = module.donchian_position(frame, entry_window=3, exit_window=2)

    assert position.loc[dates[3]] == 1.0
    assert position.loc[dates[6]] == 0.0


def test_weekly_mapping_does_not_use_unfinished_week():
    module = load_module()
    dates = pd.to_datetime(
        ["2024-01-05", "2024-01-08", "2024-01-11", "2024-01-12"]
    )
    weekly = pd.Series(
        [1.0, 2.0],
        index=pd.to_datetime(["2024-01-05", "2024-01-12"]),
    )

    mapped = module.completed_weekly_values(weekly, dates)

    assert mapped.loc[pd.Timestamp("2024-01-08")] == 1.0
    assert mapped.loc[pd.Timestamp("2024-01-11")] == 1.0
    assert mapped.loc[pd.Timestamp("2024-01-12")] == 2.0


def test_holm_adjustment_is_monotone_in_sorted_order():
    module = load_module()
    adjusted = module.holm_adjusted_pvalues(
        {"a": 0.01, "b": 0.04, "c": 0.03, "d": 0.20}
    )

    assert adjusted["a"] == pytest.approx(0.04)
    assert adjusted["c"] == pytest.approx(0.09)
    assert adjusted["b"] == pytest.approx(0.09)
    assert adjusted["d"] == pytest.approx(0.20)


def test_moving_block_bootstrap_is_deterministic_and_finite():
    module = load_module()
    differences = np.linspace(-0.01, 0.02, 80)

    first = module.bootstrap_mean_difference(
        differences,
        block_length=10,
        repetitions=100,
        seed=7,
    )
    second = module.bootstrap_mean_difference(
        differences,
        block_length=10,
        repetitions=100,
        seed=7,
    )

    assert first == second
    assert np.isfinite(first["ci_low"])
    assert np.isfinite(first["ci_high"])
    assert 0.0 <= first["p_value"] <= 1.0
