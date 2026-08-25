import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


STUDY_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = STUDY_DIR / "run_csi300_volume_rsrs.py"
SPEC = importlib.util.spec_from_file_location(
    "live_readiness_run_csi300_volume_rsrs", MODULE_PATH
)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_weighted_regression_recovers_exact_slope_and_r_squared():
    low = np.arange(1.0, 19.0)
    high = 2.5 * low + 3.0
    volume = np.arange(10.0, 28.0)

    beta, r_squared = MODULE.weighted_slope_r_squared(low, high, volume)

    assert beta == pytest.approx(2.5)
    assert r_squared == pytest.approx(1.0)


def test_score_uses_only_observation_date_and_prior_history():
    dates = pd.date_range("2023-01-02", periods=260, freq="B")
    bars = pd.DataFrame(
        {
            "trade_date": dates,
            "low": np.linspace(10.0, 20.0, len(dates)),
            "high": np.linspace(11.0, 23.0, len(dates)),
            "close": np.linspace(10.5, 21.0, len(dates)),
            "volume": np.linspace(1e8, 2e8, len(dates)),
        }
    )
    observation = dates[-2]
    first = MODULE.build_rsrs_features(bars)
    bars.loc[bars["trade_date"] == dates[-1], ["high", "volume"]] *= 100.0
    second = MODULE.build_rsrs_features(bars)

    first_score = first.set_index("trade_date").loc[observation, "score"]
    second_score = second.set_index("trade_date").loc[observation, "score"]

    assert first_score == pytest.approx(second_score)


def test_hysteresis_keeps_position_between_thresholds():
    scores = pd.Series([1.0, 0.2, -0.2, -1.0, 0.1], index=pd.date_range("2024-01-02", periods=5))

    positions = MODULE.hysteresis_positions(scores)

    assert positions.tolist() == [1, 1, 1, 0, 0]


def test_protocol_locks_public_calibration_before_oos():
    protocol = MODULE.load_protocol()

    assert protocol["source"]["oos_integrity_grade"] == "B"
    assert protocol["source"]["author_overfit_warning"] is True
    assert protocol["public_calibration"]["must_run_before_oos"] is True
    assert protocol["post_publication_window_if_unlocked"][
        "parameter_selection_used_window"
    ] is False
    assert protocol["frozen_parameters"]["buy_threshold"] == 0.85


def test_calibration_requires_return_and_sharpe():
    local = {
        "annualized_return": 0.22,
        "maximum_drawdown": 0.15,
        "sharpe": 1.10,
        "completed_positions": 12,
    }

    decision = MODULE.evaluate_calibration(local)

    assert decision["unlocked"] is True
    assert decision["pass_count"] == 4
