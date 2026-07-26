import numpy as np
import pandas as pd
import pytest

from quant_research.data.market_state import (
    build_market_state,
    price_limit_rate,
    round_price_limit,
)
from quant_research.data.valuation import normalize_eastmoney_valuation


def test_eastmoney_valuation_normalizes_units_and_dates():
    raw = pd.DataFrame(
        {
            "数据日期": ["2024-01-02"],
            "当日收盘价": [10.0],
            "当日涨跌幅": [1.2],
            "总市值": [1_000_000_000.0],
            "流通市值": [800_000_000.0],
            "总股本": [100_000_000.0],
            "流通股本": [80_000_000.0],
            "PE(TTM)": [15.0],
            "PE(静)": [16.0],
            "市净率": [2.0],
            "PEG值": [1.1],
            "市现率": [10.0],
            "市销率": [3.0],
        }
    )

    frame = normalize_eastmoney_valuation("SH600000", raw)

    assert frame.loc[0, "trade_date"] == pd.Timestamp("2024-01-02")
    assert frame.loc[0, "market_cap"] == 1_000_000_000.0
    assert frame.loc[0, "quality_grade"] == "B"


def test_price_limit_rules_change_by_board_date_and_st_status():
    assert price_limit_rate("main", "2024-01-01") == pytest.approx(0.10)
    assert price_limit_rate("chinext", "2020-08-21") == pytest.approx(0.10)
    assert price_limit_rate("chinext", "2020-08-24") == pytest.approx(0.20)
    assert price_limit_rate("star", "2024-01-01") == pytest.approx(0.20)
    assert price_limit_rate("beijing", "2024-01-01") == pytest.approx(0.30)
    assert price_limit_rate("star", "2024-01-01", is_st=True) == pytest.approx(0.05)
    assert round_price_limit([10.005, 9.994]).tolist() == [10.01, 9.99]


def test_market_state_preserves_unknown_st_and_detects_suspension():
    calendar = pd.date_range("2024-01-02", periods=3, freq="B")
    features = pd.DataFrame(
        {
            "symbol": ["SH600000", "SH600000", "SH600000"],
            "trade_date": calendar,
            "open": [1.0, np.nan, 1.1],
            "high": [1.02, np.nan, 1.12],
            "low": [0.98, np.nan, 1.08],
            "close": [1.0, np.nan, 1.1],
            "volume": [100.0, np.nan, 120.0],
            "factor": [0.1, np.nan, 0.1],
        }
    )
    master = pd.DataFrame(
        {
            "symbol": ["SH600000"],
            "start_date": [pd.Timestamp("2000-01-01")],
            "end_date": [pd.Timestamp("2026-01-01")],
            "board": ["main"],
        }
    )

    state = build_market_state(features, calendar, master, ["SH600000"])

    assert state["paused"].tolist() == [False, True, False]
    assert state["is_st"].isna().all()
    assert state.loc[2, "previous_raw_close"] == pytest.approx(10.0)
    assert state.loc[2, "high_limit"] == pytest.approx(11.0)
    assert state.loc[1, "buy_blocked"]


def test_market_state_keeps_active_symbol_without_feature_rows():
    calendar = pd.date_range("2024-01-02", periods=2, freq="B")
    features = pd.DataFrame(
        columns=["symbol", "trade_date", "open", "high", "low", "close", "volume", "factor"]
    )
    master = pd.DataFrame(
        {
            "symbol": ["SH600000"],
            "start_date": [pd.Timestamp("2000-01-01")],
            "end_date": [pd.Timestamp("2026-01-01")],
            "board": ["main"],
        }
    )

    state = build_market_state(features, calendar, master, ["SH600000"])

    assert state["paused"].tolist() == [True, True]
    assert state["high_limit"].isna().all()
