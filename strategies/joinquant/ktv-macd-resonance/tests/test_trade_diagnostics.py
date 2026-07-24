from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "trade_diagnostics.py"


def load_module():
    spec = importlib.util.spec_from_file_location(
        "ktv_trade_diagnostics",
        MODULE_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakePortal:
    def __init__(self, frame):
        self.frame = frame
        self.calendar = frame.index

    def load_symbol_frame(self, symbol, start_date, end_date):
        return self.frame.loc[start_date:end_date].copy()


class FakeLogic:
    @staticmethod
    def build_indicator_frame(frame):
        result = frame.copy()
        result["k"] = 60.0
        result["t"] = 55.0
        result["diff"] = 1.2
        result["dea"] = 1.0
        result["ma20"] = 10.0
        result["ma60"] = 9.5
        result["ma120"] = 9.0
        return result


def test_trade_path_metrics_respect_open_execution_boundaries():
    diagnostics = load_module()
    dates = pd.bdate_range("2025-01-01", periods=12)
    frame = pd.DataFrame(
        {
            "open": np.arange(10.0, 22.0),
            "high": np.arange(11.0, 23.0),
            "low": np.arange(9.0, 21.0),
            "close": np.arange(10.5, 22.5),
            "money": 100_000_000.0,
            "raw_open": np.arange(10.0, 22.0),
        },
        index=dates,
    )
    entry_date = dates[2]
    exit_date = dates[5]
    round_trips = pd.DataFrame(
        [
            {
                "symbol": "SZ000001",
                "entry_date": entry_date,
                "exit_date": exit_date,
                "status": "closed",
                "holding_days": 5,
                "exit_reason": "exit_resonance",
                "net_pnl": 100.0,
                "net_return": 0.01,
                "had_partial_exit": False,
            }
        ]
    )
    trades = pd.DataFrame(
        [
            {
                "symbol": "SZ000001",
                "date": entry_date,
                "observation_date": dates[1],
                "side": "buy",
                "reason": "entry_right",
                "adjusted_price": 12.0,
            },
            {
                "symbol": "SZ000001",
                "date": exit_date,
                "observation_date": dates[4],
                "side": "sell",
                "reason": "exit_resonance",
                "adjusted_price": 15.0,
            },
        ]
    )

    result = diagnostics.analyze_trade_paths(
        FakePortal(frame),
        FakeLogic(),
        round_trips,
        trades,
        end_date=dates[-1],
        forward_days=3,
    )
    row = result.iloc[0]

    assert row["holding_bars"] == 3
    assert row["mfe"] == pytest.approx(15.0 / 12.0 - 1.0)
    assert row["mae"] == pytest.approx(11.0 / 12.0 - 1.0)
    assert row["terminal_price_return"] == pytest.approx(15.0 / 12.0 - 1.0)
    assert row["post_exit_mfe_3"] == pytest.approx(18.0 / 15.0 - 1.0)
    assert row["post_exit_mae_3"] == pytest.approx(14.0 / 15.0 - 1.0)
    assert row["entry_gap"] == pytest.approx(12.0 / 11.5 - 1.0)


def test_trade_path_metrics_keep_open_positions_and_missing_forward_days():
    diagnostics = load_module()
    dates = pd.bdate_range("2025-01-01", periods=5)
    frame = pd.DataFrame(
        {
            "open": [10.0] * 5,
            "high": [11.0] * 5,
            "low": [9.0] * 5,
            "close": [10.0] * 5,
            "money": [100_000_000.0] * 5,
            "raw_open": [10.0] * 5,
        },
        index=dates,
    )
    round_trips = pd.DataFrame(
        [
            {
                "symbol": "SZ000001",
                "entry_date": dates[3],
                "exit_date": pd.NaT,
                "status": "open",
                "holding_days": np.nan,
                "exit_reason": None,
                "net_pnl": np.nan,
                "net_return": np.nan,
                "had_partial_exit": True,
            }
        ]
    )
    trades = pd.DataFrame(
        [
            {
                "symbol": "SZ000001",
                "date": dates[3],
                "observation_date": dates[2],
                "side": "buy",
                "reason": "entry_right",
                "adjusted_price": 10.0,
            }
        ]
    )

    result = diagnostics.analyze_trade_paths(
        FakePortal(frame),
        FakeLogic(),
        round_trips,
        trades,
        end_date=dates[-1],
        forward_days=10,
    )
    row = result.iloc[0]

    assert row["holding_bars"] == 2
    assert np.isnan(row["terminal_price_return"])
    assert np.isnan(row["post_exit_close_return_5"])
