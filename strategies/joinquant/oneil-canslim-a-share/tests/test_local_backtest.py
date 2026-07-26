import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = ROOT / "local_backtest.py"


def load_engine():
    spec = importlib.util.spec_from_file_location("oneil_local_backtest", ENGINE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cumulative_reports_are_converted_to_single_quarters():
    engine = load_engine()
    reports = pd.DataFrame(
        [
            {
                "symbol": "SH600001",
                "report_date": "2024-03-31",
                "notice_date": "2024-04-20",
                "basic_eps": 0.20,
                "adjusted_profit": 20.0,
                "parent_net_profit": 22.0,
                "revenue": 100.0,
                "roe": 5.0,
            },
            {
                "symbol": "SH600001",
                "report_date": "2024-06-30",
                "notice_date": "2024-08-20",
                "basic_eps": 0.55,
                "adjusted_profit": 55.0,
                "parent_net_profit": 60.0,
                "revenue": 260.0,
                "roe": 11.0,
            },
            {
                "symbol": "SH600001",
                "report_date": "2024-09-30",
                "notice_date": "2024-10-20",
                "basic_eps": 0.95,
                "adjusted_profit": 95.0,
                "parent_net_profit": 105.0,
                "revenue": 450.0,
                "roe": 16.0,
            },
            {
                "symbol": "SH600001",
                "report_date": "2024-12-31",
                "notice_date": "2025-03-20",
                "basic_eps": 1.50,
                "adjusted_profit": 150.0,
                "parent_net_profit": 165.0,
                "revenue": 700.0,
                "roe": 22.0,
            },
        ]
    )

    normalized = engine.cumulative_to_single_quarter(reports)

    np.testing.assert_allclose(
        normalized["quarter_basic_eps"], [0.20, 0.35, 0.40, 0.55]
    )
    np.testing.assert_allclose(
        normalized["quarter_adjusted_profit"], [20.0, 35.0, 40.0, 55.0]
    )
    np.testing.assert_allclose(
        normalized["quarter_revenue"], [100.0, 160.0, 190.0, 250.0]
    )
    assert normalized.iloc[-1]["annual_basic_eps"] == 1.50
    assert normalized.iloc[-1]["annual_roe"] == 22.0


def test_missing_previous_cumulative_report_does_not_invent_a_quarter():
    engine = load_engine()
    reports = pd.DataFrame(
        [
            {
                "symbol": "SZ000001",
                "report_date": "2024-03-31",
                "notice_date": "2024-04-20",
                "basic_eps": 0.20,
                "adjusted_profit": 20.0,
                "parent_net_profit": 22.0,
                "revenue": 100.0,
                "roe": 5.0,
            },
            {
                "symbol": "SZ000001",
                "report_date": "2024-09-30",
                "notice_date": "2024-10-20",
                "basic_eps": 0.95,
                "adjusted_profit": 95.0,
                "parent_net_profit": 105.0,
                "revenue": 450.0,
                "roe": 16.0,
            },
        ]
    )

    normalized = engine.cumulative_to_single_quarter(reports)

    assert np.isnan(normalized.iloc[-1]["quarter_basic_eps"])
    assert np.isnan(normalized.iloc[-1]["quarter_adjusted_profit"])
    assert np.isnan(normalized.iloc[-1]["quarter_revenue"])


def test_financial_portal_only_exposes_reports_announced_by_observation_date(tmp_path):
    engine = load_engine()
    cache = engine.cumulative_to_single_quarter(
        pd.DataFrame(
            [
                {
                    "symbol": "SH600001",
                    "report_date": "2023-12-31",
                    "notice_date": "2024-03-20",
                    "basic_eps": 1.00,
                    "adjusted_profit": 100.0,
                    "parent_net_profit": 110.0,
                    "revenue": 500.0,
                    "roe": 18.0,
                },
                {
                    "symbol": "SH600001",
                    "report_date": "2024-03-31",
                    "notice_date": "2024-04-25",
                    "basic_eps": 0.35,
                    "adjusted_profit": 35.0,
                    "parent_net_profit": 38.0,
                    "revenue": 160.0,
                    "roe": 6.0,
                },
            ]
        )
    )
    cache_path = tmp_path / "financials.parquet"
    cache.to_parquet(cache_path, index=False)
    pd.DataFrame(
        [{"symbol": "SH600001", "industry": "测试行业", "name": "测试股份"}]
    ).to_csv(tmp_path / "industries.csv", index=False, encoding="utf-8-sig")

    portal = engine.FinancialDataPortal(tmp_path)
    before = portal.histories("SH600001", "2024-04-24")
    after = portal.histories("SH600001", "2024-04-25")

    assert before.quarterly["statDate"].max() == pd.Timestamp("2023-12-31")
    assert after.quarterly["statDate"].max() == pd.Timestamp("2024-03-31")
    assert before.annual["statDate"].tolist() == [pd.Timestamp("2023-12-31")]
    assert portal.industry("SH600001") == "测试行业"


def test_eastmoney_code_mapping_matches_qlib_symbols():
    engine = load_engine()

    assert engine.eastmoney_code("SH600519") == "600519.SH"
    assert engine.eastmoney_code("SZ000001") == "000001.SZ"
    assert engine.eastmoney_code("BJ430047") == "430047.BJ"
    assert engine.qlib_symbol("600519.SH") == "SH600519"
    assert engine.qlib_symbol("000001.SZ") == "SZ000001"


def test_local_engine_can_load_the_formal_candidate_variant():
    engine = load_engine()

    logic = engine.load_strategy_logic("formal-candidate")

    assert logic.MIN_LISTING_DAYS == 120
    assert hasattr(logic, "aggregate_market_states")
    with pytest.raises(ValueError, match="不支持的策略变体"):
        engine.load_strategy_logic("unknown")


def test_market_risk_budget_only_allows_exposure_gap():
    engine = load_engine()

    assert engine.market_risk_budget(1_000_000, 400_000, 0.70) == 100_000
    assert engine.market_risk_budget(1_000_000, 100_000, 0.35) == 0.0
    assert engine.market_risk_budget(1_000_000, 1_000_000, 0.0) == 0.0
