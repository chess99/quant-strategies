from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "local_backtest.py"


def load_module():
    spec = importlib.util.spec_from_file_location("ktv_local_backtest", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_feature(root, symbol, field, start_index, values):
    target = root / "features" / symbol.lower()
    target.mkdir(parents=True, exist_ok=True)
    payload = np.hstack(([float(start_index)], np.asarray(values, dtype="<f4")))
    payload.astype("<f4").tofile(target / f"{field}.day.bin")


def make_qlib_fixture(tmp_path, periods=90):
    root = tmp_path / "cn_data"
    (root / "calendars").mkdir(parents=True)
    (root / "instruments").mkdir(parents=True)
    dates = pd.bdate_range("2025-01-01", periods=periods)
    day_text = "\n".join(date.strftime("%Y-%m-%d") for date in dates) + "\n"
    (root / "calendars" / "day.txt").write_text(day_text, encoding="utf-8")

    first = dates[0].strftime("%Y-%m-%d")
    last = dates[-1].strftime("%Y-%m-%d")
    (root / "instruments" / "all.txt").write_text(
        f"SZ000001\t{first}\t{last}\nSZ000002\t{first}\t{last}\n",
        encoding="utf-8",
    )
    (root / "instruments" / "csi300.txt").write_text(
        f"SZ000001\t{first}\t{last}\n",
        encoding="utf-8",
    )
    (root / "instruments" / "csi500.txt").write_text(
        f"SZ000001\t{first}\t{last}\nSZ000002\t{first}\t{last}\n",
        encoding="utf-8",
    )

    adjusted = np.linspace(1.0, 1.2, periods)
    factor = np.full(periods, 0.1)
    amount = np.full(periods, 100_000.0)
    volume = np.full(periods, 1_000_000.0)
    for symbol in ("sz000001", "sz000002"):
        for field, values in {
            "open": adjusted,
            "high": adjusted * 1.01,
            "low": adjusted * 0.99,
            "close": adjusted,
            "factor": factor,
            "amount": amount,
            "volume": volume,
        }.items():
            write_feature(root, symbol, field, 0, values)
    return root, dates


def test_qlib_portal_reads_point_in_time_members_and_field_units(tmp_path):
    local = load_module()
    root, dates = make_qlib_fixture(tmp_path)
    portal = local.QlibBinDataPortal(root)

    members = portal.members_on(["csi300", "csi500"], dates[20])
    frame = portal.load_symbol_frame("SZ000001", dates[10], dates[15])

    assert members == ["SZ000001", "SZ000002"]
    assert frame.index.min() == dates[10]
    assert frame.index.max() == dates[15]
    assert frame["money"].iloc[0] == pytest.approx(100_000_000.0)
    assert frame["raw_open"].iloc[0] == pytest.approx(
        frame["open"].iloc[0] / frame["factor"].iloc[0]
    )


def test_adjustment_anomaly_filter_distinguishes_factor_error_from_real_move():
    local = load_module()
    index = pd.bdate_range("2025-02-20", periods=3)

    bad = pd.DataFrame(
        {
            "close": [1.0, 1.02, 5.9],
            "factor": [0.02, 0.02, 0.118],
        },
        index=index,
    )
    real_move = pd.DataFrame(
        {
            "close": [1.0, 1.02, 1.60],
            "factor": [0.02, 0.02, 0.02],
        },
        index=index,
    )

    bad_events = local.find_adjustment_anomalies(bad, adjusted_threshold=0.30)
    real_events = local.find_adjustment_anomalies(real_move, adjusted_threshold=0.30)

    assert len(bad_events) == 1
    assert bad_events.iloc[0]["date"] == index[-1]
    assert real_events.empty


def test_order_helpers_apply_board_lot_commission_tax_and_slippage():
    local = load_module()
    config = local.BacktestConfig(initial_cash=100_000.0)

    shares = local.affordable_board_lot(
        budget=10_000.0,
        cash=10_000.0,
        raw_price=10.0,
        config=config,
    )
    buy_cost = local.transaction_cost(shares * 10.0, "buy", config)
    sell_cost = local.transaction_cost(shares * 10.0, "sell", config)

    assert shares == 900
    assert buy_cost == pytest.approx(5.0)
    assert sell_cost == pytest.approx(14.0)
    assert local.execution_raw_price(10.0, "buy", config) == pytest.approx(10.002)
    assert local.execution_raw_price(10.0, "sell", config) == pytest.approx(9.998)


def test_performance_metrics_include_drawdown_sharpe_turnover_and_underwater():
    local = load_module()
    dates = pd.bdate_range("2025-01-01", periods=5)
    equity = pd.DataFrame(
        {
            "equity": [100.0, 110.0, 99.0, 105.0, 121.0],
            "cash": [100.0, 50.0, 50.0, 50.0, 121.0],
            "gross_traded": [0.0, 40.0, 0.0, 20.0, 0.0],
            "benchmark_value": [1.01, 1.02, 1.01, 1.03, 1.05],
        },
        index=dates,
    )

    metrics, yearly = local.calculate_performance(
        equity,
        trade_count=2,
        holding_days=[3],
        initial_equity=100.0,
    )

    assert metrics["total_return"] == pytest.approx(0.21)
    assert metrics["benchmark_total_return"] == pytest.approx(0.05)
    assert metrics["max_drawdown"] == pytest.approx(-0.10)
    assert metrics["longest_underwater_trading_days"] == 2
    assert metrics["trade_count"] == 2
    assert metrics["average_holding_days"] == pytest.approx(3.0)
    assert metrics["turnover"] > 0.0
    assert 2025 in yearly.index


def test_engine_uses_previous_close_signal_and_next_open_execution(tmp_path):
    local = load_module()
    root, dates = make_qlib_fixture(tmp_path, periods=120)
    start = pd.Timestamp("2025-04-07")
    end = pd.Timestamp("2025-04-11")

    class FakeLogic:
        @staticmethod
        def build_indicator_frame(frame):
            return frame.copy()

        @staticmethod
        def entry_signal(frame):
            return {"kind": "right", "score": 200.0}

        @staticmethod
        def exit_decision(frame, avg_cost=None, half_reduced=False):
            if frame.index[-1] >= pd.Timestamp("2025-04-09"):
                return "full"
            return None

    config = local.BacktestConfig(
        start_date=start,
        end_date=end,
        initial_cash=100_000.0,
        min_listing_days=0,
        history_count=20,
        min_signal_rows=5,
        benchmark_symbol="SZ000001",
        excluded_symbols=frozenset({"SZ000002", "SZ302132"}),
    )
    engine = local.LocalBacktester(
        data=local.QlibBinDataPortal(root),
        logic=FakeLogic(),
        config=config,
    )

    result = engine.run()
    trades = result.trades

    assert list(trades["side"]) == ["buy", "sell"]
    assert trades.iloc[0]["date"] == start
    assert trades.iloc[0]["observation_date"] < trades.iloc[0]["date"]
    assert trades.iloc[1]["date"] == pd.Timestamp("2025-04-10")
    assert result.equity.index.min() == start
    assert result.metrics["trade_count"] == 2


def test_default_known_bad_symbol_is_excluded():
    local = load_module()

    assert "SZ302132" in local.BacktestConfig().excluded_symbols
