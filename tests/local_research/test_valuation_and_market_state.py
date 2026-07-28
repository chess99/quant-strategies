import numpy as np
import pandas as pd
import pytest

from quant_research.data.market_state import (
    apply_market_reference,
    build_market_state,
    finalize_rule_based_limits,
    ipo_has_no_price_limit,
    price_limit_rate,
    round_price_limit,
)
from quant_research.data.market_reference import (
    apply_st_name_events,
    derive_delisting_events_from_market_history,
    normalize_delisting_events,
    normalize_dolthub_baostock_status,
    normalize_dolthub_price_limits,
    normalize_szse_st_name_events,
)
from quant_research.data.security_lifecycle import clip_to_security_lifecycle
from quant_research.data.store import ResearchDataStore
from quant_research.data.valuation import (
    densify_baidu_valuation_with_market_state,
    normalize_baidu_valuation,
    normalize_eastmoney_valuation,
    sync_valuation_partitions,
)


def test_delisting_notices_become_point_in_time_events_on_next_session():
    master = pd.DataFrame(
        {
            "symbol": ["SH600091", "SZ000585", "SH600000"],
            "asset_type": ["stock", "stock", "stock"],
        }
    )
    notices = pd.DataFrame(
        {
            "stock_code": ["600091", "000585", "600000"],
            "notice_date": pd.to_datetime(["2022-05-17"] * 3),
            "short_name": ["退市明科", "*ST东电", "浦发银行"],
            "title": [
                "关于公司股票进入退市整理期交易的公告",
                "关于公司A股股票进入退市整理期交易的公告",
                "年度股东大会决议公告",
            ],
            "art_code": ["A1", "A2", "A3"],
        }
    )
    calendar = pd.to_datetime(["2022-05-17", "2022-05-18", "2022-05-19"])

    events = normalize_delisting_events(notices, master, calendar)

    assert events["symbol"].tolist() == ["SH600091", "SZ000585"]
    assert events["effective_from"].tolist() == [
        pd.Timestamp("2022-05-18"),
        pd.Timestamp("2022-05-18"),
    ]
    assert events["is_delisting"].tolist() == [True, True]
    assert events["quality_grade"].tolist() == ["B", "B"]


def test_delisting_period_start_is_derived_from_historical_trading_sessions():
    master = pd.DataFrame(
        {
            "symbol": ["SH600001", "SH600002"],
            "asset_type": ["stock", "stock"],
            "display_name": ["退市旧规", "退市新规"],
            "end_date": pd.to_datetime(["2020-12-31", "2022-12-30"]),
        }
    )
    old_dates = pd.bdate_range("2020-11-02", periods=44)
    new_dates = pd.bdate_range("2022-12-01", periods=22)
    history = pd.DataFrame(
        {
            "symbol": ["SH600001"] * len(old_dates) + ["SH600002"] * len(new_dates),
            "trade_date": old_dates.tolist() + new_dates.tolist(),
            "paused": [False] * (len(old_dates) + len(new_dates)),
            "raw_close": [1.0] * (len(old_dates) + len(new_dates)),
        }
    )

    events = derive_delisting_events_from_market_history(master, history)
    rows = events.set_index("symbol")

    assert rows.loc["SH600001", "effective_from"] == old_dates[-30]
    assert rows.loc["SH600002", "effective_from"] == new_dates[-15]
    assert rows["quality_grade"].eq("B").all()


def test_delisting_period_prefers_final_block_after_long_suspension():
    master = pd.DataFrame(
        {
            "symbol": ["SH600701"],
            "asset_type": ["stock"],
            "display_name": ["退市工新"],
            "end_date": pd.to_datetime(["2021-04-26"]),
        }
    )
    calendar = pd.bdate_range("2021-02-01", "2021-04-26")
    final_block_start = pd.Timestamp("2021-03-25")
    history = pd.DataFrame(
        {
            "symbol": ["SH600701"] * len(calendar),
            "trade_date": calendar,
            "paused": (calendar > pd.Timestamp("2021-02-05"))
            & (calendar < final_block_start),
            "raw_close": np.where(
                (calendar > pd.Timestamp("2021-02-05"))
                & (calendar < final_block_start),
                np.nan,
                1.0,
            ),
        }
    )

    events = derive_delisting_events_from_market_history(master, history)

    assert events.loc[0, "effective_from"] == final_block_start
    assert events.loc[0, "source"].endswith("final-trading-block")


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


def test_baidu_market_cap_normalizes_yi_yuan_unit():
    frame = normalize_baidu_valuation(
        "SH600000",
        "market_cap",
        pd.DataFrame({"date": ["2024-01-02"], "value": [123.45]}),
    )

    assert frame.loc[0, "market_cap"] == pytest.approx(12_345_000_000.0)


def test_baidu_valuation_is_densified_from_past_anchor_and_raw_price():
    valuation = pd.DataFrame(
        {
            "symbol": ["SH600000", "SH600000"],
            "trade_date": pd.to_datetime(["2024-01-02", "2024-01-08"]),
            "close": [np.nan, np.nan],
            "change_percent": [np.nan, np.nan],
            "market_cap": [1_000_000_000.0, 1_200_000_000.0],
            "circulating_market_cap": [np.nan, np.nan],
            "total_shares": [np.nan, np.nan],
            "circulating_shares": [np.nan, np.nan],
            "pe_ttm": [10.0, 12.0],
            "pe_static": [11.0, 13.0],
            "pb": [1.0, 1.2],
            "peg": [2.0, 2.4],
            "pcf": [8.0, 9.6],
            "ps": [3.0, 3.6],
            "source": ["akshare/baidu-stock-valuation"] * 2,
            "quality_grade": ["B", "B"],
        }
    )
    state = pd.DataFrame(
        {
            "symbol": ["SH600000"] * 5,
            "trade_date": pd.to_datetime(
                ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"]
            ),
            "raw_close": [10.0, 11.0, np.nan, 11.5, 12.0],
        }
    )

    result = densify_baidu_valuation_with_market_state(valuation, state)

    assert result["trade_date"].tolist() == state["trade_date"].tolist()
    assert result["market_cap"].tolist() == pytest.approx(
        [1_000_000_000.0, 1_100_000_000.0, 1_100_000_000.0, 1_150_000_000.0, 1_200_000_000.0]
    )
    assert result["total_shares"].tolist() == pytest.approx([100_000_000.0] * 5)
    # 1 月 3 日只能使用 1 月 2 日锚点，不能提前看到 1 月 8 日供应商记录。
    assert result.loc[result["trade_date"].eq("2024-01-03"), "pe_ttm"].iloc[0] == pytest.approx(11.0)
    assert result["source"].str.contains("price-scaled", regex=False).all()


def test_partitioned_valuation_sync_is_resumable(tmp_path):
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

    class Provider:
        calls = 0

        def fetch(self, symbol):
            self.calls += 1
            return raw

    store = ResearchDataStore(tmp_path)
    store.write_parquet(
        "security_master",
        pd.DataFrame(
            {
                "symbol": ["SH600000", "SZ000001"],
                "listing_date": pd.to_datetime(["1999-11-10", "1991-04-03"]),
                "delisting_date": [pd.NaT, pd.NaT],
            }
        ),
    )
    provider = Provider()
    statuses, manifest = sync_valuation_partitions(
        store,
        ["SH600000", "SZ000001"],
        active_symbols={"SH600000", "SZ000001"},
        provider=provider,
        workers=1,
    )

    assert provider.calls == 2
    assert len(statuses) == 2
    assert manifest.coverage["current_coverage_ratio"] == 1.0
    assert len(manifest.data_files) == 2
    second_statuses, _ = sync_valuation_partitions(
        store,
        ["SH600000", "SZ000001"],
        active_symbols={"SH600000", "SZ000001"},
        provider=provider,
        workers=1,
    )
    assert provider.calls == 2
    assert len(second_statuses) == 2


def test_vendor_rows_are_clipped_to_listing_and_delisting_dates():
    frame = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(
                ["2023-12-29", "2024-01-02", "2024-01-03", "2024-01-04"]
            ),
            "value": [1, 2, 3, 4],
        }
    )
    security = pd.Series(
        {
            "listing_date": pd.Timestamp("2024-01-02"),
            "delisting_date": pd.Timestamp("2024-01-03"),
        }
    )

    result = clip_to_security_lifecycle(
        frame,
        security,
        date_column="trade_date",
    )

    assert result["value"].tolist() == [2, 3]


def test_migrated_code_uses_canonical_valuation_inside_lifecycle(tmp_path):
    def raw_on(date):
        return pd.DataFrame(
            {
                "数据日期": [date],
                "当日收盘价": [10.0],
                "当日涨跌幅": [0.0],
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

    class Provider:
        def fetch(self, symbol):
            return raw_on("2024-01-02" if symbol == "BJ920017" else "2023-12-29")

    store = ResearchDataStore(tmp_path)
    store.write_parquet(
        "security_master",
        pd.DataFrame(
            {
                "symbol": ["BJ430017"],
                "listing_date": [pd.Timestamp("2024-01-01")],
                "delisting_date": [pd.Timestamp("2024-12-31")],
                "canonical_symbol": ["BJ920017"],
            }
        ),
    )

    statuses, _ = sync_valuation_partitions(
        store,
        ["BJ430017"],
        active_symbols=set(),
        provider=Provider(),
        workers=1,
    )
    valuation = store.read_symbol_partitions("daily_valuation", ["BJ430017"])

    assert statuses.loc[0, "status"] == "success"
    assert valuation["trade_date"].tolist() == [pd.Timestamp("2024-01-02")]
    assert "bj920017" in statuses.loc[0, "raw_path"]


def test_price_limit_rules_change_by_board_date_and_st_status():
    assert price_limit_rate("main", "2024-01-01") == pytest.approx(0.10)
    assert price_limit_rate("chinext", "2020-08-21") == pytest.approx(0.10)
    assert price_limit_rate("chinext", "2020-08-24") == pytest.approx(0.20)
    assert price_limit_rate("star", "2024-01-01") == pytest.approx(0.20)
    assert price_limit_rate("beijing", "2024-01-01") == pytest.approx(0.30)
    assert price_limit_rate("star", "2024-01-01", is_st=True) == pytest.approx(0.20)
    assert price_limit_rate("chinext", "2024-01-01", is_st=True) == pytest.approx(0.20)
    assert price_limit_rate("main", "2024-01-01", is_st=True) == pytest.approx(0.05)
    assert round_price_limit([10.005, 9.994]).tolist() == [10.01, 9.99]


def test_known_st_status_promotes_rule_based_limit_to_b_quality():
    state = pd.DataFrame(
        {
            "symbol": ["SZ300478", "SH600000"],
            "trade_date": pd.to_datetime(["2021-01-04", "2021-01-04"]),
            "paused": [False, False],
            "is_st": pd.array([False, True], dtype="boolean"),
            "raw_open": [10.0, 9.5],
            "raw_high": [10.5, 9.5],
            "raw_low": [9.8, 9.5],
            "raw_close": [10.2, 9.5],
            "previous_raw_close": [10.0, 10.0],
            "high_limit": [12.0, 11.0],
            "low_limit": [8.0, 9.0],
            "one_price": [False, True],
            "buy_blocked": [False, False],
            "sell_blocked": [False, False],
            "no_price_limit": [False, False],
            "status_quality": ["B", "B"],
            "st_quality": ["B", "A"],
            "limit_quality": ["C", "C"],
            "status_source": ["test", "test"],
            "st_source": ["test", "test"],
            "limit_source": ["board-rule-derived", "board-rule-derived"],
            "source": ["test", "test"],
        }
    )

    result = finalize_rule_based_limits(
        state,
        {"SZ300478": "chinext", "SH600000": "main"},
    ).set_index("symbol")

    assert result.loc["SZ300478", "high_limit"] == pytest.approx(12.0)
    assert result.loc["SZ300478", "low_limit"] == pytest.approx(8.0)
    assert result.loc["SH600000", "high_limit"] == pytest.approx(10.5)
    assert result.loc["SH600000", "low_limit"] == pytest.approx(9.5)
    assert result["limit_quality"].eq("B").all()
    assert result.loc["SH600000", "sell_blocked"]


def test_ipo_no_limit_rules_cover_registration_boards():
    assert ipo_has_no_price_limit("star", "2020-01-02", 1)
    assert ipo_has_no_price_limit("star", "2020-01-02", 5)
    assert not ipo_has_no_price_limit("star", "2020-01-02", 6)
    assert not ipo_has_no_price_limit("chinext", "2020-08-21", 1)
    assert ipo_has_no_price_limit("chinext", "2020-08-24", 1)
    assert ipo_has_no_price_limit("main", "2023-04-10", 5)
    assert not ipo_has_no_price_limit("main", "2023-04-10", 6)
    assert ipo_has_no_price_limit("beijing", "2024-01-02", 1)
    assert not ipo_has_no_price_limit("beijing", "2024-01-02", 2)


def test_dolthub_limits_normalize_symbols_and_infer_st():
    raw = pd.DataFrame(
        {
            "tradedate": ["2024-01-02", "2024-01-02"],
            "symbol": ["SH600000", "sz000001"],
            "pre_close": ["10", "20"],
            "up_limit": ["10.5", "22"],
            "down_limit": ["9.5", "18"],
        }
    )

    frame = normalize_dolthub_price_limits(raw)

    assert frame["symbol"].tolist() == ["SH600000", "SZ000001"]
    assert frame["is_st"].tolist() == [True, False]
    assert frame["st_quality"].tolist() == ["B", "B"]
    assert frame["limit_quality"].tolist() == ["B", "B"]


def test_registration_board_limits_do_not_falsely_imply_non_st():
    raw = pd.DataFrame(
        {
            "tradedate": ["2024-01-02", "2024-01-02"],
            "symbol": ["SH688001", "SZ300001"],
            "pre_close": [10.0, 10.0],
            "up_limit": [12.0, 12.0],
            "down_limit": [8.0, 8.0],
        }
    )

    frame = normalize_dolthub_price_limits(raw)

    assert frame["is_st"].isna().all()
    assert frame["st_quality"].tolist() == ["C", "C"]


def test_baostock_status_overrides_registration_board_st_unknown():
    state = pd.DataFrame(
        {
            "symbol": ["SH688001"],
            "trade_date": pd.to_datetime(["2023-01-03"]),
            "paused": [False],
            "is_st": pd.array([pd.NA], dtype="boolean"),
            "raw_open": [10.0],
            "raw_high": [10.1],
            "raw_low": [9.9],
            "raw_close": [10.0],
            "previous_raw_close": [10.0],
            "high_limit": [12.0],
            "low_limit": [8.0],
            "one_price": [False],
            "buy_blocked": [False],
            "sell_blocked": [False],
            "no_price_limit": [False],
            "status_quality": ["B"],
            "st_quality": ["C"],
            "limit_quality": ["B"],
            "status_source": ["qlib-community-cn/derived"],
            "st_source": [None],
            "limit_source": ["dolthub/final-a-stock-limit"],
            "source": ["qlib-community-cn/derived"],
        }
    )
    reference = normalize_dolthub_baostock_status(
        pd.DataFrame(
            {
                "tradedate": ["2023-01-03"],
                "symbol": ["SH688001"],
                "tradestatus": [1],
                "is_st": [1],
            }
        )
    )

    result = apply_market_reference(state, reference)

    assert result.loc[0, "is_st"]
    assert result.loc[0, "st_quality"] == "B"
    assert result.loc[0, "st_source"] == "dolthub/baostock-is-st"


def test_baostock_false_does_not_override_exact_five_percent_st_evidence():
    raw_limits = pd.DataFrame(
        {
            "tradedate": ["2023-04-03"],
            "symbol": ["SH600242"],
            "pre_close": [4.00],
            "up_limit": [4.20],
            "down_limit": [3.80],
        }
    )
    state = pd.DataFrame(
        {
            "symbol": ["SH600242"],
            "trade_date": pd.to_datetime(["2023-04-03"]),
            "paused": [False],
            "is_st": pd.array([pd.NA], dtype="boolean"),
            "raw_open": [4.00],
            "raw_high": [4.01],
            "raw_low": [3.99],
            "raw_close": [4.00],
            "previous_raw_close": [4.00],
            "high_limit": [4.40],
            "low_limit": [3.60],
            "one_price": [False],
            "buy_blocked": [False],
            "sell_blocked": [False],
            "no_price_limit": [False],
            "status_quality": ["B"],
            "st_quality": ["C"],
            "limit_quality": ["C"],
            "status_source": ["qlib-community-cn/derived"],
            "st_source": [None],
            "limit_source": ["board-rule-derived"],
            "source": ["qlib-community-cn/derived"],
        }
    )
    state = apply_market_reference(state, normalize_dolthub_price_limits(raw_limits))
    baostock = normalize_dolthub_baostock_status(
        pd.DataFrame(
            {
                "tradedate": ["2023-04-03"],
                "symbol": ["SH600242"],
                "tradestatus": [1],
                "is_st": [0],
            }
        )
    )

    result = apply_market_reference(state, baostock)

    assert result.loc[0, "is_st"]
    assert result.loc[0, "st_quality"] == "B"
    assert result.loc[0, "st_source"] == "dolthub/final-a-stock-limit-inferred"


def test_szse_name_change_events_replay_st_by_effective_date():
    master = pd.DataFrame(
        {
            "symbol": ["SZ300001"],
            "exchange": ["XSHE"],
            "asset_type": ["stock"],
            "listing_date": [pd.Timestamp("2020-01-01")],
            "display_name": ["特锐德"],
        }
    )
    raw = pd.DataFrame(
        {
            "变更日期": ["2023-01-03", "2024-01-03"],
            "证券代码": ["300001", "300001"],
            "证券简称": ["特锐德", "特锐德"],
            "变更前简称": ["特锐德", "*ST特锐"],
            "变更后简称": ["*ST特锐", "特锐德"],
        }
    )
    events = normalize_szse_st_name_events(raw, master)
    state = pd.DataFrame(
        {
            "symbol": ["SZ300001"] * 3,
            "trade_date": pd.to_datetime(
                ["2022-12-30", "2023-01-03", "2024-01-03"]
            ),
            "is_st": pd.array([pd.NA] * 3, dtype="boolean"),
            "st_quality": ["C"] * 3,
            "st_source": [None] * 3,
        }
    )

    result = apply_st_name_events(state, events)

    assert result["is_st"].tolist() == [False, True, False]
    assert result["st_quality"].tolist() == ["A", "A", "A"]


def test_reference_limits_override_rule_proxy_and_preserve_unknown_days():
    state = pd.DataFrame(
        {
            "symbol": ["SH600000", "SH600000"],
            "trade_date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
            "paused": [False, False],
            "is_st": pd.array([pd.NA, pd.NA], dtype="boolean"),
            "raw_open": [10.5, 10.1],
            "raw_high": [10.5, 10.2],
            "raw_low": [10.5, 10.0],
            "raw_close": [10.5, 10.1],
            "previous_raw_close": [10.0, 10.5],
            "high_limit": [11.0, 11.55],
            "low_limit": [9.0, 9.45],
            "one_price": [True, False],
            "buy_blocked": [False, False],
            "sell_blocked": [False, False],
            "no_price_limit": [False, False],
            "status_quality": ["B", "B"],
            "st_quality": ["C", "C"],
            "limit_quality": ["C", "C"],
            "status_source": ["qlib-community-cn/derived"] * 2,
            "st_source": [None, None],
            "limit_source": ["board-rule-derived"] * 2,
            "source": ["qlib-community-cn/derived"] * 2,
        }
    )
    reference = normalize_dolthub_price_limits(
        pd.DataFrame(
            {
                "tradedate": ["2024-01-02"],
                "symbol": ["SH600000"],
                "pre_close": [10.0],
                "up_limit": [10.5],
                "down_limit": [9.5],
            }
        )
    )

    result = apply_market_reference(state, reference)

    assert result.loc[0, "high_limit"] == pytest.approx(10.5)
    assert result.loc[0, "low_limit"] == pytest.approx(9.5)
    assert result.loc[0, "is_st"]
    assert result.loc[0, "buy_blocked"]
    assert result.loc[0, "limit_quality"] == "B"
    assert result.loc[1, "st_quality"] == "C"


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
    assert state["no_price_limit"].tolist() == [False, False, False]


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
