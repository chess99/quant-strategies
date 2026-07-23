from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
STRATEGY_PATH = ROOT / "baseline.py"


def load_strategy():
    spec = importlib.util.spec_from_file_location("ktv_macd_proxy", STRATEGY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_signal_frame():
    size = 130
    index = pd.date_range("2025-01-01", periods=size, freq="B")
    frame = pd.DataFrame(index=index)
    frame["close"] = 102.0
    frame.iloc[-60:-20, frame.columns.get_loc("close")] = np.linspace(120.0, 104.0, 40)
    frame.iloc[-20:, frame.columns.get_loc("close")] = np.linspace(100.0, 102.0, 20)
    frame["money"] = 1.0e8
    frame.iloc[-5:, frame.columns.get_loc("money")] = 1.2e8
    frame["ma20"] = 102.0
    frame["ma60"] = np.linspace(99.0, 100.0, size)
    frame["ma120"] = 98.0
    frame["v"] = 40.0
    frame["k"] = 40.0
    frame["t"] = 45.0
    frame["diff"] = -0.2
    frame["dea"] = -0.1
    frame["macd_hist"] = -0.4
    frame.iloc[-5:, frame.columns.get_loc("v")] = [15.0, 18.0, 22.0, 30.0, 45.0]
    frame.iloc[-2:, frame.columns.get_loc("k")] = [40.0, 50.0]
    frame.iloc[-2:, frame.columns.get_loc("t")] = [45.0, 46.0]
    frame.iloc[-3:, frame.columns.get_loc("macd_hist")] = [-0.30, -0.20, -0.10]
    return frame


def test_strategy_source_is_joinquant_legacy_compatible_and_self_contained():
    source = STRATEGY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    unqualified = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"all", "any", "sum"}
    ]

    assert "from __future__ import annotations" not in source
    assert "from **future** import annotations" not in source
    assert "strict=" not in source
    assert unqualified == []
    assert "import trading_os" not in source
    assert "current_data.get(" not in source


def test_stochastic_rsi_proxy_is_bounded_and_exposes_k_t_v():
    strategy = load_strategy()
    close = pd.Series(
        100.0 + np.sin(np.arange(180) / 7.0) * 8.0 + np.arange(180) * 0.04
    )

    ktv = strategy.calculate_ktv(close)

    assert list(ktv.columns) == ["k", "t", "v"]
    assert ktv[["k", "t", "v"]].dropna().ge(0.0).all().all()
    assert ktv[["k", "t", "v"]].dropna().le(100.0).all().all()
    assert ktv["v"].std() >= ktv["k"].std()


def test_cross_detection_supports_recent_up_and_down_crosses():
    strategy = load_strategy()

    assert strategy.crossed_up_recent(
        pd.Series([40.0, 42.0, 48.0]),
        pd.Series([45.0, 45.0, 45.0]),
        lookback=2,
    )
    assert strategy.crossed_down_recent(
        pd.Series([60.0, 58.0, 49.0]),
        pd.Series([55.0, 55.0, 55.0]),
        lookback=2,
    )
    assert not strategy.crossed_up_recent(
        pd.Series([48.0, 47.0, 46.0]),
        pd.Series([45.0, 45.0, 45.0]),
        lookback=2,
    )


def test_left_entry_requires_low_position_ktv_macd_and_moderate_volume():
    strategy = load_strategy()
    frame = make_signal_frame()

    assert strategy.is_left_entry(frame)

    no_volume = frame.copy()
    no_volume.iloc[-5:, no_volume.columns.get_loc("money")] = 3.0e8
    assert not strategy.is_left_entry(no_volume)

    downtrend = frame.copy()
    downtrend.iloc[-1, downtrend.columns.get_loc("ma20")] = 90.0
    assert not strategy.is_left_entry(downtrend)


def test_right_entry_requires_bull_trend_pullback_and_red_bar_reexpansion():
    strategy = load_strategy()
    frame = make_signal_frame()
    frame["close"] = np.linspace(90.0, 120.0, len(frame))
    frame["ma20"] = 115.0
    frame["ma60"] = np.linspace(103.0, 110.0, len(frame))
    frame["ma120"] = 100.0
    frame["t"] = 55.0
    frame["k"] = 58.0
    frame.iloc[-2:, frame.columns.get_loc("k")] = [52.0, 60.0]
    frame["diff"] = 1.2
    frame["dea"] = 1.0
    frame["macd_hist"] = 0.3
    frame.iloc[-3:, frame.columns.get_loc("macd_hist")] = [0.40, 0.20, 0.35]
    frame["money"] = 1.0e8
    frame.iloc[-5:, frame.columns.get_loc("money")] = 1.3e8

    assert strategy.is_right_entry(frame)

    below_zero = frame.copy()
    below_zero["diff"] = -0.1
    below_zero["dea"] = -0.2
    assert not strategy.is_right_entry(below_zero)


def test_exit_decision_prioritizes_full_exit_and_only_reduces_once():
    strategy = load_strategy()
    frame = make_signal_frame()
    frame["k"] = 85.0
    frame["t"] = 80.0
    frame["diff"] = 1.2
    frame["dea"] = 1.0
    frame["macd_hist"] = 0.5
    frame.iloc[-2:, frame.columns.get_loc("k")] = [85.0, 75.0]
    frame.iloc[-2:, frame.columns.get_loc("t")] = [80.0, 80.0]
    frame.iloc[-3:, frame.columns.get_loc("macd_hist")] = [0.50, 0.35, 0.20]

    assert strategy.exit_decision(frame, avg_cost=90.0, half_reduced=False) == "half"
    assert strategy.exit_decision(frame, avg_cost=90.0, half_reduced=True) is None

    full_exit = frame.copy()
    full_exit["k"] = 40.0
    full_exit["t"] = 50.0
    full_exit["diff"] = -0.2
    full_exit["dea"] = -0.1
    full_exit["macd_hist"] = -0.1
    assert strategy.exit_decision(full_exit, avg_cost=90.0, half_reduced=False) == "full"

    hard_stop = frame.copy()
    hard_stop.iloc[-1, hard_stop.columns.get_loc("close")] = 80.0
    assert strategy.exit_decision(hard_stop, avg_cost=90.0, half_reduced=False) == "full"


def test_current_snapshot_materializes_lazy_joinquant_mapping():
    strategy = load_strategy()

    class LazyCurrentData(dict):
        def __missing__(self, key):
            value = SimpleNamespace(code=key)
            self[key] = value
            return value

    current_data = LazyCurrentData()
    snapshot = strategy.get_current_snapshot(current_data, "000001.XSHE")

    assert snapshot.code == "000001.XSHE"
    assert "000001.XSHE" in current_data


def test_signal_queries_use_previous_trade_day_and_next_session_schedules():
    source = STRATEGY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    scheduled = {
        node.func.id: node.args[0].id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"run_daily", "run_weekly"}
        and node.args
        and isinstance(node.args[0], ast.Name)
    }

    assert "observation_date = context.previous_date" in source
    assert scheduled["run_daily"] == "manage_positions"
    assert scheduled["run_weekly"] == "scan_entries"
    assert "end_date=observation_date" in source
