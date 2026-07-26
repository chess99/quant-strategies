import pandas as pd
import pytest

from quant_research.backtest import (
    BacktestConfig,
    CostModel,
    DailyBacktester,
    performance_metrics,
)


def make_bars(rows):
    return pd.DataFrame(rows, columns=["symbol", "trade_date", "open", "close", "volume"])


def make_state(rows):
    frame = pd.DataFrame(
        rows,
        columns=[
            "symbol",
            "trade_date",
            "paused",
            "is_st",
            "buy_blocked",
            "sell_blocked",
        ],
    )
    frame["is_st"] = pd.array(frame["is_st"], dtype="boolean")
    return frame


def test_backtester_uses_board_lots_fees_and_sell_before_buy():
    dates = pd.to_datetime(["2024-01-02", "2024-01-03"])
    bars = make_bars(
        [
            ("SH600000", dates[0], 10.0, 10.0, 1_000_000),
            ("SZ000001", dates[0], 20.0, 20.0, 1_000_000),
            ("SH600000", dates[1], 10.0, 10.0, 1_000_000),
            ("SZ000001", dates[1], 20.0, 20.0, 1_000_000),
        ]
    )
    state = make_state(
        [
            ("SH600000", dates[0], False, False, False, False),
            ("SZ000001", dates[0], False, False, False, False),
            ("SH600000", dates[1], False, False, False, False),
            ("SZ000001", dates[1], False, False, False, False),
        ]
    )
    engine = DailyBacktester(
        bars,
        state,
        config=BacktestConfig(initial_cash=100_000, maximum_volume_ratio=1.0),
    )

    engine.rebalance_to_weights(dates[0], {"SH600000": 1.0})
    engine.mark_close(dates[0])
    engine.rebalance_to_weights(dates[1], {"SZ000001": 1.0})

    assert engine.trades.iloc[0]["filled_shares"] == 9_900
    second_day = engine.trades[engine.trades["trade_date"].eq(dates[1])]
    assert second_day.iloc[0]["side"] == "sell"
    assert second_day.iloc[1]["side"] == "buy"
    assert engine.positions["SZ000001"].shares % 100 == 0
    assert engine.cash >= 0


def test_failed_sell_does_not_release_cash_for_new_buy():
    dates = pd.to_datetime(["2024-01-02", "2024-01-03"])
    bars = make_bars(
        [
            ("SH600000", dates[0], 10.0, 10.0, 1_000_000),
            ("SZ000001", dates[0], 20.0, 20.0, 1_000_000),
            ("SH600000", dates[1], 10.0, 10.0, 1_000_000),
            ("SZ000001", dates[1], 20.0, 20.0, 1_000_000),
        ]
    )
    state = make_state(
        [
            ("SH600000", dates[0], False, False, False, False),
            ("SZ000001", dates[0], False, False, False, False),
            ("SH600000", dates[1], False, False, False, True),
            ("SZ000001", dates[1], False, False, False, False),
        ]
    )
    engine = DailyBacktester(
        bars,
        state,
        config=BacktestConfig(initial_cash=100_000, maximum_volume_ratio=1.0),
    )
    engine.rebalance_to_weights(dates[0], {"SH600000": 1.0})
    cash_before = engine.cash

    engine.rebalance_to_weights(dates[1], {"SZ000001": 1.0})

    assert engine.positions["SH600000"].shares == 9_900
    assert "SZ000001" not in engine.positions
    assert engine.cash == pytest.approx(cash_before)
    reasons = engine.orders[engine.orders["trade_date"].eq(dates[1])]["reason"].tolist()
    assert reasons == ["price_limit", "insufficient_cash"]


def test_unknown_st_is_rejected_unless_explicitly_allowed():
    date = pd.Timestamp("2024-01-02")
    bars = make_bars([("SH600000", date, 10.0, 10.0, 1_000_000)])
    state = make_state([("SH600000", date, False, pd.NA, False, False)])
    strict = DailyBacktester(
        bars,
        state,
        config=BacktestConfig(initial_cash=100_000, maximum_volume_ratio=1.0),
    )
    exploratory = DailyBacktester(
        bars,
        state,
        config=BacktestConfig(
            initial_cash=100_000,
            maximum_volume_ratio=1.0,
            allow_unknown_st=True,
        ),
    )

    strict.rebalance_to_weights(date, {"SH600000": 1.0})
    exploratory.rebalance_to_weights(date, {"SH600000": 1.0})

    assert strict.orders.iloc[0]["reason"] == "unknown_st"
    assert exploratory.positions["SH600000"].shares == 9_900


def test_volume_limit_partially_fills_and_stamp_tax_changes():
    date = pd.Timestamp("2024-01-02")
    bars = make_bars([("SH600000", date, 10.0, 10.0, 5_000)])
    state = make_state([("SH600000", date, False, False, False, False)])
    engine = DailyBacktester(
        bars,
        state,
        config=BacktestConfig(initial_cash=100_000, maximum_volume_ratio=0.10),
    )

    engine.rebalance_to_weights(date, {"SH600000": 1.0})

    assert engine.positions["SH600000"].shares == 500
    assert engine.orders.iloc[0]["reason"] == "partial_volume_or_cash"
    costs = CostModel()
    _, old_tax = costs.fees("stock", "sell", 100_000, "2023-08-25")
    _, new_tax = costs.fees("stock", "sell", 100_000, "2023-08-28")
    _, etf_tax = costs.fees("etf", "sell", 100_000, "2023-08-25")
    assert old_tax == 100.0
    assert new_tax == 50.0
    assert etf_tax == 0.0


def test_performance_metrics_include_initial_cash_and_yearly_returns():
    equity = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2023-12-29", "2024-01-02"]),
            "total_value": [110.0, 121.0],
            "daily_return": [0.10, 0.10],
        }
    )

    metrics = performance_metrics(equity)

    assert metrics["total_return"] == pytest.approx(0.21)
    assert metrics["yearly_returns"] == pytest.approx({"2023": 0.10, "2024": 0.10})
