import pandas as pd
import pytest

from quant_research.backtest import (
    BacktestConfig,
    CostModel,
    DailyBacktester,
    Position,
    performance_metrics,
    scheduled_dates,
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
    assert reasons == ["down_limit", "insufficient_cash"]


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

    trades = pd.DataFrame({"gross_value": [50.0, 60.0]})
    metrics = performance_metrics(equity, trades)

    assert metrics["total_return"] == pytest.approx(0.21)
    assert metrics["yearly_returns"] == pytest.approx({"2023": 0.10, "2024": 0.10})
    assert metrics["turnover"] == pytest.approx(110 / 115.5)


def test_open_close_execution_and_all_target_order_forms():
    date = pd.Timestamp("2024-01-02")
    bars = make_bars(
        [
            ("SH600000", date, 10.0, 12.0, 1_000_000),
            ("SH600001", date, 20.0, 24.0, 1_000_000),
        ]
    )
    state = make_state(
        [
            ("SH600000", date, False, False, False, False),
            ("SH600001", date, False, False, False, False),
        ]
    )
    engine = DailyBacktester(
        bars,
        state,
        asset_types={"SH600000": "etf", "SH600001": "etf"},
        config=BacktestConfig(initial_cash=100_000, maximum_volume_ratio=1.0),
    )

    engine.order_value(date, "SH600000", 12_000, execution="close")
    engine.order_target(date, "SH600000", 500, execution="close")
    engine.order_target_value(date, "SH600001", 12_000, execution="close")
    engine.order_target_percent(date, "SH600001", 0.2, execution="close")
    engine.order_target_weight(date, "SH600001", 0.1, execution="close")

    assert engine.trades["execution"].eq("close").all()
    assert engine.trades.iloc[0]["price"] == pytest.approx(12.0)
    assert engine.positions["SH600000"].shares == 500
    assert engine.positions["SH600001"].shares % 100 == 0


def test_stock_t_plus_one_and_etf_same_day_round_trip():
    date = pd.Timestamp("2024-01-02")
    bars = make_bars(
        [
            ("SH600000", date, 10.0, 10.0, 1_000_000),
            ("SH510300", date, 4.0, 4.0, 1_000_000),
        ]
    )
    state = make_state(
        [
            ("SH600000", date, False, False, False, False),
            ("SH510300", date, False, False, False, False),
        ]
    )
    engine = DailyBacktester(
        bars,
        state,
        asset_types={"SH600000": "stock", "SH510300": "etf"},
        config=BacktestConfig(initial_cash=100_000, maximum_volume_ratio=1.0),
    )

    engine.order_target(date, "SH600000", 1_000)
    engine.order_target(date, "SH600000", 0)
    engine.order_target(date, "SH510300", 1_000)
    engine.order_target(date, "SH510300", 0)

    assert engine.positions["SH600000"].shares == 1_000
    assert "SH510300" not in engine.positions
    assert "t_plus_one" in engine.rejections["reason"].tolist()


def test_t_plus_one_shares_become_available_next_session():
    dates = pd.to_datetime(["2024-01-02", "2024-01-03"])
    bars = make_bars(
        [("SH600000", date, 10.0, 10.0, 1_000_000) for date in dates]
    )
    state = make_state(
        [("SH600000", date, False, False, False, False) for date in dates]
    )
    engine = DailyBacktester(
        bars,
        state,
        config=BacktestConfig(initial_cash=100_000, maximum_volume_ratio=1.0),
    )
    engine.order_target(dates[0], "SH600000", 1_000)

    engine.order_target(dates[1], "SH600000", 0)

    assert "SH600000" not in engine.positions


def test_odd_lot_can_only_be_liquidated_as_a_whole():
    date = pd.Timestamp("2024-01-02")
    bars = make_bars([("SH600000", date, 10.0, 10.0, 1_000_000)])
    state = make_state([("SH600000", date, False, False, False, False)])
    engine = DailyBacktester(
        bars,
        state,
        config=BacktestConfig(initial_cash=0, maximum_volume_ratio=1.0),
    )
    engine.positions["SH600000"] = engine_position = Position("SH600000", 250, 8.0, 10.0)

    engine.order_target(date, "SH600000", 50)
    assert engine_position.shares == 50
    engine.order_target(date, "SH600000", 0)
    assert "SH600000" not in engine.positions


def test_daily_volume_capacity_is_shared_by_all_orders():
    date = pd.Timestamp("2024-01-02")
    bars = make_bars([("SH510300", date, 4.0, 4.0, 2_000)])
    state = make_state([("SH510300", date, False, False, False, False)])
    engine = DailyBacktester(
        bars,
        state,
        asset_types={"SH510300": "etf"},
        config=BacktestConfig(initial_cash=100_000, maximum_volume_ratio=0.1),
    )

    engine.order_target(date, "SH510300", 200)
    engine.order_target(date, "SH510300", 400)

    assert engine.positions["SH510300"].shares == 200
    assert engine.rejections.iloc[-1]["reason"] == "volume_limit"


def test_market_state_rejection_reasons_are_explicit():
    date = pd.Timestamp("2024-01-02")
    symbols = ["SH600000", "SH600001", "SH600002", "SH600003"]
    bars = make_bars([(symbol, date, 10.0, 10.0, 1_000_000) for symbol in symbols])
    state = make_state(
        [
            (symbols[0], date, True, False, False, False),
            (symbols[1], date, False, True, False, False),
            (symbols[2], date, False, False, True, False),
            (symbols[3], date, False, False, False, True),
        ]
    )
    engine = DailyBacktester(
        bars,
        state,
        config=BacktestConfig(initial_cash=100_000, maximum_volume_ratio=1.0),
    )

    for symbol in symbols[:3]:
        engine.order_target(date, symbol, 100)
    engine.positions[symbols[3]] = Position(symbols[3], 100, 10.0, 10.0)
    engine.order_target(date, symbols[3], 0)

    assert engine.rejections["reason"].tolist() == [
        "paused",
        "st_buy_blocked",
        "up_limit",
        "down_limit",
    ]


def test_scheduler_uses_actual_first_or_last_trading_session():
    calendar = pd.to_datetime(
        ["2024-01-02", "2024-01-03", "2024-01-05", "2024-01-08", "2024-02-01"]
    )

    assert scheduled_dates(calendar, "weekly", "first") == {
        pd.Timestamp("2024-01-02"),
        pd.Timestamp("2024-01-08"),
        pd.Timestamp("2024-02-01"),
    }
    assert scheduled_dates(calendar, "monthly", "last") == {
        pd.Timestamp("2024-01-08"),
        pd.Timestamp("2024-02-01"),
    }


def test_corporate_actions_and_all_ledgers_are_auditable():
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"])
    bars = make_bars(
        [("SH600000", date, 10.0, 10.0, 1_000_000) for date in dates]
    )
    state = make_state(
        [("SH600000", date, False, False, False, False) for date in dates]
    )
    actions = pd.DataFrame(
        [
            (dates[1], "SH600000", "cash_dividend", 0.5, None, None, None),
            (dates[2], "SH600000", "bonus", None, 1.5, None, None),
            (dates[3], "SH600000", "rights_issue", None, None, 0.1, 5.0),
        ],
        columns=[
            "action_date",
            "symbol",
            "action_type",
            "cash_per_share",
            "share_multiplier",
            "rights_ratio",
            "subscription_price",
        ],
    )
    engine = DailyBacktester(
        bars,
        state,
        config=BacktestConfig(
            initial_cash=100_000,
            maximum_volume_ratio=1.0,
            participate_rights_issues=True,
        ),
        corporate_actions=actions,
    )
    engine.order_target(dates[0], "SH600000", 1_000)
    for date in dates:
        engine.mark_close(date)

    assert engine.positions["SH600000"].shares == 1_650
    assert engine.corporate_actions["status"].eq("applied").all()
    assert {"initial_cash", "buy", "cash_dividend", "rights_issue"}.issubset(
        set(engine.cash_ledger["event"])
    )
    assert not engine.fees_ledger.empty
    assert not engine.holdings.empty
    assert "cash_ratio" in engine.equity


def test_stamp_tax_history_and_etf_exemption():
    costs = CostModel()

    assert costs.stamp_tax_rate("stock", "buy", "2007-06-01") == pytest.approx(0.003)
    assert costs.stamp_tax_rate("stock", "sell", "2007-06-01") == pytest.approx(0.003)
    assert costs.stamp_tax_rate("stock", "buy", "2008-09-19") == 0.0
    assert costs.stamp_tax_rate("stock", "sell", "2008-09-19") == pytest.approx(0.001)
    assert costs.stamp_tax_rate("stock", "sell", "2023-08-28") == pytest.approx(0.0005)
    assert costs.stamp_tax_rate("etf", "sell", "2007-06-01") == 0.0


def test_formal_backtest_rejects_c_grade_market_state_rows():
    date = pd.Timestamp("2024-01-02")
    bars = make_bars([("BJ430017", date, 10.0, 10.0, 1_000_000)])
    state = make_state([("BJ430017", date, False, False, False, False)])
    state["status_quality"] = "B"
    state["st_quality"] = "B"
    state["limit_quality"] = "C"
    engine = DailyBacktester(
        bars,
        state,
        config=BacktestConfig(
            initial_cash=100_000,
            maximum_volume_ratio=1.0,
            minimum_state_quality="B",
        ),
    )

    engine.order_target(date, "BJ430017", 100)

    assert engine.rejections.iloc[0]["reason"] == "insufficient_limit_quality"
