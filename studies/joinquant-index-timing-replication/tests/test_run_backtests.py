import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd


MODULE_PATH = Path(__file__).resolve().parents[1] / "run_backtests.py"
SPEC = importlib.util.spec_from_file_location("joinquant_index_timing_study", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_weighted_rsrs_matches_direct_weighted_regression():
    dates = pd.date_range("2024-01-01", periods=6, freq="D")
    low = pd.Series([10.0, 11.0, 12.5, 11.8, 13.2, 14.1], index=dates)
    high = pd.Series([10.8, 12.0, 13.1, 12.9, 14.5, 15.2], index=dates)
    volume = pd.Series([1.0, 4.0, 2.0, 3.0, 6.0, 5.0], index=dates)

    beta, r_squared = MODULE.rolling_weighted_rsrs(high, low, volume, window=6)

    x = np.column_stack([np.ones(len(low)), low.to_numpy()])
    weights = volume.to_numpy() / volume.sum()
    xtwx = x.T @ (weights[:, None] * x)
    coefficients = np.linalg.solve(xtwx, x.T @ (weights * high.to_numpy()))
    fitted = x @ coefficients
    mean = np.average(high.to_numpy(), weights=weights)
    expected_r_squared = 1.0 - (
        np.sum(weights * (high.to_numpy() - fitted) ** 2)
        / np.sum(weights * (high.to_numpy() - mean) ** 2)
    )

    assert beta.iloc[-1] == pytest_approx(coefficients[1])
    assert r_squared.iloc[-1] == pytest_approx(expected_r_squared)


def test_threshold_position_is_lagged_to_next_trade_date():
    dates = pd.date_range("2024-01-01", periods=5, freq="B")
    signal = pd.Series([0.0, 0.8, 0.1, -0.9, 0.5], index=dates)

    target = MODULE.threshold_target(signal, buy=0.7, sell=-0.7)

    assert target.tolist() == [0.0, 0.0, 1.0, 1.0, 0.0]


def test_all_in_out_simulator_applies_open_execution_and_costs():
    dates = pd.date_range("2024-01-01", periods=3, freq="B")
    frame = pd.DataFrame(
        {
            "open": [10.0, 11.0, 12.0],
            "close": [10.0, 12.0, 12.0],
        },
        index=dates,
    )
    target = pd.Series([0.0, 1.0, 0.0], index=dates)
    costs = MODULE.TradingCosts(
        buy_commission=0.01,
        sell_commission=0.01,
        sell_tax=0.02,
        slippage=0.0,
    )

    equity, trades = MODULE.simulate_all_in_out(
        frame,
        target,
        initial_cash=1_000.0,
        costs=costs,
        execution_field="open",
    )

    expected_units = 1_000.0 / (11.0 * 1.01)
    expected_day_two = expected_units * 12.0
    expected_final = expected_units * 12.0 * (1.0 - 0.01 - 0.02)
    assert equity.loc[dates[1], "equity"] == pytest_approx(expected_day_two)
    assert equity.loc[dates[2], "equity"] == pytest_approx(expected_final)
    assert trades["side"].tolist() == ["buy", "sell"]


def test_performance_reports_drawdown_and_annualization():
    dates = pd.date_range("2024-01-01", periods=4, freq="B")
    equity = pd.DataFrame(
        {
            "equity": [100.0, 110.0, 88.0, 121.0],
            "cash": 0.0,
            "gross_traded": 0.0,
        },
        index=dates,
    )

    metrics = MODULE.calculate_performance(equity, initial_cash=100.0)

    assert metrics["total_return"] == pytest_approx(0.21)
    assert metrics["max_drawdown"] == pytest_approx(0.20)
    assert metrics["annualized_return"] == pytest_approx(1.21 ** (250.0 / 4.0) - 1.0)


def pytest_approx(value):
    import pytest

    return pytest.approx(value, rel=1e-10, abs=1e-12)
