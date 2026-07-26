import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd


MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "studies"
    / "joinquant-etf-rotation-replication"
    / "run_backtest.py"
)
SPEC = importlib.util.spec_from_file_location("etf_rotation_study", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_momentum_score_rewards_smooth_positive_trend():
    smooth_up = pd.Series(np.exp(np.linspace(0.0, 0.08, 25)))
    flat = pd.Series(np.ones(25))
    noisy = smooth_up.copy()
    noisy.iloc[::2] *= 0.97

    assert MODULE.momentum_score(smooth_up) > MODULE.momentum_score(noisy)
    assert np.isnan(MODULE.momentum_score(flat))


def test_daily_target_uses_next_day_and_stable_tie_break():
    dates = pd.date_range("2024-01-01", periods=27, freq="B")
    rows = []
    for symbol in MODULE.ETF_SYMBOLS:
        for index, date in enumerate(dates):
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": date,
                    "adjusted_close": 1.0 + index * 0.01,
                }
            )
    bars = pd.DataFrame(rows)

    targets, _ = MODULE.build_daily_targets(bars)

    assert pd.isna(targets.iloc[24])
    assert targets.iloc[25] == sorted(MODULE.ETF_SYMBOLS)[0]


def test_rotation_keeps_position_when_sell_day_has_no_quote():
    dates = pd.to_datetime(["2024-01-02", "2024-01-03"])
    bars = pd.DataFrame(
        [
            {
                "symbol": "SH510180",
                "trade_date": dates[0],
                "adjusted_open": 2.0,
                "adjusted_close": 2.1,
            },
            {
                "symbol": "SH518880",
                "trade_date": dates[1],
                "adjusted_open": 4.0,
                "adjusted_close": 4.1,
            },
        ]
    )
    targets = pd.Series(["SH510180", "SH518880"], index=dates, dtype="string")

    equity, trades = MODULE.simulate_rotation(bars, targets)

    assert trades["side"].tolist() == ["buy"]
    assert equity.loc[dates[1], "held_symbol"] == "SH510180"
