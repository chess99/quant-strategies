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


def test_entry_controls_change_only_the_requested_confirmation_layer():
    local = load_module()

    class FakeLogic:
        @staticmethod
        def entry_signal(frame):
            return {"kind": "right", "score": 203.0}

        @staticmethod
        def is_left_entry(frame):
            return bool(frame.attrs["baseline_left"])

        @staticmethod
        def is_right_entry(frame):
            return bool(frame.attrs["baseline_right"])

        @staticmethod
        def _last_values(frame, column, count):
            return frame[column].dropna().tail(count)

        @staticmethod
        def crossed_up_recent(first, second, lookback=3):
            return bool(first.attrs.get("crossed_up", False))

        @staticmethod
        def _green_histogram_shrinking(frame):
            return bool(frame.attrs["macd_turning"])

        @staticmethod
        def _macd_crossed_up_recent(frame):
            return False

        @staticmethod
        def _not_in_downtrend(frame):
            return True

        @staticmethod
        def _stage_low_not_falling_knife(frame):
            return True

        @staticmethod
        def _moderate_volume(frame):
            return True

        @staticmethod
        def _bull_trend(frame):
            return True

        @staticmethod
        def _red_histogram_reexpanding(frame):
            return bool(frame.attrs["red_reexpanding"])

        @staticmethod
        def _finite_number(value):
            return float(value)

    frame = pd.DataFrame(
        {
            "close": np.linspace(80.0, 70.0, 130),
            "v": [10.0] * 130,
            "k": [60.0] * 130,
            "t": [55.0] * 130,
            "diff": [1.2] * 130,
            "dea": [1.0] * 130,
            "ma20": [101.0] * 130,
            "ma60": [100.0] * 130,
        }
    )
    frame["k"].attrs["crossed_up"] = True
    frame.attrs.update(
        {
            "baseline_left": False,
            "baseline_right": False,
            "macd_turning": False,
            "red_reexpanding": False,
        }
    )

    assert local.entry_signal_for_mode(FakeLogic(), frame, "baseline") == {
        "kind": "right",
        "score": 203.0,
    }
    assert local.entry_signal_for_mode(FakeLogic(), frame, "ktv-entry-only")[
        "kind"
    ] == "right"
    assert (
        local.entry_signal_for_mode(FakeLogic(), frame, "macd-entry-only") is None
    )

    frame["k"].attrs["crossed_up"] = False
    frame.attrs["macd_turning"] = True
    frame.attrs["red_reexpanding"] = True
    assert (
        local.entry_signal_for_mode(FakeLogic(), frame, "ktv-entry-only") is None
    )
    assert local.entry_signal_for_mode(FakeLogic(), frame, "macd-entry-only")[
        "kind"
    ] == "right"


def test_left_and_right_controls_reuse_the_unmodified_baseline_predicates():
    local = load_module()

    class FakeLogic:
        @staticmethod
        def entry_signal(frame):
            return {"kind": "right", "score": 202.0}

        @staticmethod
        def is_left_entry(frame):
            return bool(frame.attrs["left"])

        @staticmethod
        def is_right_entry(frame):
            return bool(frame.attrs["right"])

        @staticmethod
        def _finite_number(value):
            return float(value)

    frame = pd.DataFrame(
        {
            "close": np.linspace(100.0, 80.0, 60),
            "ma20": [102.0] * 60,
            "ma60": [100.0] * 60,
        }
    )
    frame.attrs.update({"left": True, "right": True})

    left = local.entry_signal_for_mode(FakeLogic(), frame, "left-only")
    right = local.entry_signal_for_mode(FakeLogic(), frame, "right-only")

    assert left["kind"] == "left"
    assert 100.0 <= left["score"] < 200.0
    assert right["kind"] == "right"
    assert right["score"] >= 200.0
    with pytest.raises(ValueError, match="unsupported entry mode"):
        local.entry_signal_for_mode(FakeLogic(), frame, "unknown")


def test_right_filter_controls_remove_only_one_requested_filter():
    local = load_module()

    class FakeLogic:
        @staticmethod
        def _finite_number(value):
            return float(value)

        @staticmethod
        def crossed_up_recent(first, second, lookback=3):
            return True

        @staticmethod
        def _bull_trend(frame):
            return bool(frame.attrs["trend"])

        @staticmethod
        def _red_histogram_reexpanding(frame):
            return True

        @staticmethod
        def _moderate_volume(frame):
            return bool(frame.attrs["volume"])

    frame = pd.DataFrame(
        {
            "close": np.linspace(100.0, 110.0, 130),
            "k": [60.0] * 130,
            "t": [55.0] * 130,
            "diff": [1.2] * 130,
            "dea": [1.0] * 130,
            "ma20": [102.0] * 130,
            "ma60": [100.0] * 130,
        }
    )

    frame.attrs.update({"trend": True, "volume": False})
    assert local.entry_signal_for_mode(
        FakeLogic(), frame, "right-no-volume"
    )["kind"] == "right"
    assert (
        local.entry_signal_for_mode(FakeLogic(), frame, "right-no-trend")
        is None
    )

    frame.attrs.update({"trend": False, "volume": True})
    assert (
        local.entry_signal_for_mode(FakeLogic(), frame, "right-no-volume")
        is None
    )
    assert local.entry_signal_for_mode(
        FakeLogic(), frame, "right-no-trend"
    )["kind"] == "right"


def test_low_extension_mode_keeps_signal_but_reverses_trend_gap_ranking():
    local = load_module()

    class FakeLogic:
        @staticmethod
        def is_right_entry(frame):
            return True

        @staticmethod
        def _finite_number(value):
            return float(value)

    low_extension = pd.DataFrame(
        {
            "close": [100.0],
            "ma20": [102.0],
            "ma60": [100.0],
        }
    )
    high_extension = pd.DataFrame(
        {
            "close": [100.0],
            "ma20": [115.0],
            "ma60": [100.0],
        }
    )

    low = local.entry_signal_for_mode(
        FakeLogic(),
        low_extension,
        "right-low-extension",
    )
    high = local.entry_signal_for_mode(
        FakeLogic(),
        high_extension,
        "right-low-extension",
    )

    assert low["kind"] == "right"
    assert high["kind"] == "right"
    assert low["score"] > high["score"]


def test_exit_reason_classification_preserves_baseline_priority():
    local = load_module()

    class FakeLogic:
        HARD_STOP_LOSS = 0.08

        @staticmethod
        def _finite_number(value):
            return float(value)

        @staticmethod
        def _resonance_full_exit(frame):
            return bool(frame.attrs["resonance"])

        @staticmethod
        def _trend_invalid(frame):
            return bool(frame.attrs["trend_invalid"])

        @staticmethod
        def _take_profit_signal(frame):
            return bool(frame.attrs["take_profit"])

    frame = pd.DataFrame({"close": [91.0]})
    frame.attrs.update(
        {"resonance": True, "trend_invalid": True, "take_profit": True}
    )

    assert (
        local.classify_exit_reason(
            FakeLogic(), frame, "full", avg_cost=100.0, half_reduced=False
        )
        == "exit_hard_stop"
    )
    frame.iloc[-1, frame.columns.get_loc("close")] = 100.0
    assert (
        local.classify_exit_reason(
            FakeLogic(), frame, "full", avg_cost=100.0, half_reduced=False
        )
        == "exit_resonance"
    )
    frame.attrs["resonance"] = False
    assert (
        local.classify_exit_reason(
            FakeLogic(), frame, "full", avg_cost=100.0, half_reduced=False
        )
        == "exit_trend_invalid"
    )
    assert (
        local.classify_exit_reason(
            FakeLogic(), frame, "half", avg_cost=100.0, half_reduced=False
        )
        == "exit_take_profit_half"
    )


def test_round_trip_attribution_handles_partial_exit_and_open_position():
    local = load_module()
    trades = pd.DataFrame(
        [
            {
                "date": "2025-01-02",
                "symbol": "SZ000001",
                "side": "buy",
                "reason": "entry_right",
                "kind": "right",
                "score": 201.0,
                "gross": 10_000.0,
                "costs": 5.0,
            },
            {
                "date": "2025-01-10",
                "symbol": "SZ000001",
                "side": "sell",
                "reason": "exit_take_profit_half",
                "kind": None,
                "score": np.nan,
                "gross": 6_000.0,
                "costs": 8.0,
            },
            {
                "date": "2025-01-20",
                "symbol": "SZ000001",
                "side": "sell",
                "reason": "exit_trend_invalid",
                "kind": None,
                "score": np.nan,
                "gross": 5_000.0,
                "costs": 7.0,
            },
            {
                "date": "2025-02-03",
                "symbol": "SZ000002",
                "side": "buy",
                "reason": "entry_right",
                "kind": "right",
                "score": 202.0,
                "gross": 8_000.0,
                "costs": 5.0,
            },
        ]
    )

    round_trips, summary = local.build_round_trip_attribution(trades)
    closed = round_trips.loc[round_trips["status"] == "closed"].iloc[0]
    opened = round_trips.loc[round_trips["status"] == "open"].iloc[0]

    assert closed["gross_pnl"] == pytest.approx(1_000.0)
    assert closed["total_costs"] == pytest.approx(20.0)
    assert closed["net_pnl"] == pytest.approx(980.0)
    assert closed["holding_days"] == 18
    assert bool(closed["had_partial_exit"])
    assert closed["exit_reason"] == "exit_trend_invalid"
    assert np.isnan(opened["net_pnl"])
    assert summary["completed_round_trips"] == 1
    assert summary["open_round_trips"] == 1
    assert summary["round_trip_win_rate"] == pytest.approx(1.0)
