import importlib.util
import math
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = ROOT / "local_backtest.py"


def load_engine():
    spec = importlib.util.spec_from_file_location("oneil_factor_local", ENGINE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_safe_growth_rejects_non_positive_base():
    engine = load_engine()

    assert engine.safe_growth(125.0, 100.0) == 0.25
    assert math.isnan(engine.safe_growth(1.0, 0.0))
    assert math.isnan(engine.safe_growth(1.0, -1.0))
    assert math.isnan(engine.safe_growth(np.nan, 1.0))


def test_latest_quarter_growth_aligns_same_fiscal_quarter():
    engine = load_engine()
    quarterly = pd.DataFrame(
        {
            "statDate": pd.to_datetime(
                ["2023-06-30", "2024-03-31", "2024-06-30", "2025-03-31"]
            ),
            "basic_eps": [0.20, 0.10, 0.30, 0.16],
            "np_parent_company_owners": [20.0, 10.0, 32.0, 18.0],
            "total_operating_revenue": [100.0, 80.0, 130.0, 100.0],
        }
    )

    growth = engine.latest_quarter_growths(quarterly)

    assert growth["report_date"] == pd.Timestamp("2025-03-31")
    assert round(growth["eps_growth"], 6) == 0.6
    assert round(growth["profit_growth"], 6) == 0.8
    assert round(growth["revenue_growth"], 6) == 0.25


def test_turnaround_strength_recognizes_loss_to_profit_without_fake_percentage():
    engine = load_engine()

    assert engine.turnaround_strength(10.0, -5.0) == 4.0
    assert engine.turnaround_strength(10.0, 5.0) == 1.0
    assert math.isnan(engine.turnaround_strength(-1.0, -5.0))
    assert math.isnan(engine.turnaround_strength(0.0, -5.0))


def test_annual_growth_path_uses_five_visible_years_and_requires_each_year_positive():
    engine = load_engine()
    annual = pd.DataFrame(
        {
            "statDate": pd.to_datetime(
                [
                    "2020-12-31",
                    "2021-12-31",
                    "2022-12-31",
                    "2023-12-31",
                    "2024-12-31",
                ]
            ),
            "np_parent_company_owners": [100.0, 120.0, 150.0, 190.0, 240.0],
        }
    )

    accepted = engine.annual_growth_path(annual)
    annual.loc[3, "np_parent_company_owners"] = 140.0
    rejected = engine.annual_growth_path(annual)

    assert accepted["years"] == 5
    assert accepted["all_positive_growth"]
    assert accepted["cagr"] > 0.15
    assert not rejected["all_positive_growth"]


def test_nine_one_momentum_skips_most_recent_month():
    engine = load_engine()
    closes = pd.Series(np.linspace(100.0, 200.0, 230))

    actual = engine.nine_one_momentum(closes)
    expected = closes.iloc[-22] / closes.iloc[-211] - 1.0

    assert round(actual, 12) == round(expected, 12)


def test_cross_sectional_percentile_keeps_ties_and_missing_values_explicit():
    engine = load_engine()
    values = pd.Series([10.0, 20.0, 20.0, np.nan], index=list("abcd"))

    ranked = engine.percentile_rank(values)

    assert ranked["a"] == 25.0
    assert ranked["b"] == ranked["c"] == 75.0
    assert math.isnan(ranked["d"])


def test_price_features_measure_new_high_and_base_proxy_without_lookahead():
    engine = load_engine()
    dates = pd.bdate_range("2024-01-01", periods=260)
    closes = np.linspace(60.0, 100.0, 260)
    closes[-65:-25] = np.linspace(100.0, 82.0, 40)
    closes[-25:] = np.linspace(84.0, 98.0, 25)
    frame = pd.DataFrame(
        {
            "close": closes,
            "high": closes + 1.0,
            "low": closes - 1.0,
            "money": np.full(260, 100_000_000.0),
        },
        index=dates,
    )

    features = engine.price_features(frame)

    assert 0.95 <= features["high_proximity"] <= 1.0
    assert features["base_depth"] >= 0.15
    assert features["liquid"]


def test_model_selection_distinguishes_strict_and_adaptive_growth_rules():
    engine = load_engine()
    features = pd.DataFrame(
        [
            {
                "symbol": "SH600001",
                "eps_growth": 0.30,
                "profit_growth": 0.30,
                "revenue_growth": 0.30,
                "annual_cagr": 0.20,
                "annual_positive_path": True,
                "rps": 90.0,
                "momentum_percentile": 90.0,
                "growth_percentile": 90.0,
                "revenue_percentile": 90.0,
                "high_proximity": 0.98,
                "base_ready": True,
                "liquid": True,
            },
            {
                "symbol": "SH600002",
                "eps_growth": 0.55,
                "profit_growth": 0.70,
                "revenue_growth": 0.45,
                "annual_cagr": 0.10,
                "annual_positive_path": False,
                "rps": 95.0,
                "momentum_percentile": 95.0,
                "growth_percentile": 95.0,
                "revenue_percentile": 95.0,
                "high_proximity": 0.97,
                "base_ready": True,
                "liquid": True,
            },
        ]
    ).set_index("symbol", drop=False)

    strict = engine.select_candidates(features, "huachuang-2019-available")
    adaptive = engine.select_candidates(features, "a-share-adaptive")

    assert strict["symbol"].tolist() == ["SH600001"]
    assert adaptive.iloc[0]["symbol"] == "SH600002"
    assert set(adaptive["symbol"]) == {"SH600001", "SH600002"}


def test_cycle_turnaround_model_admits_profitable_turnaround_with_momentum():
    engine = load_engine()
    features = pd.DataFrame(
        [
            {
                "symbol": "SH688525",
                "profit_current": 80.0,
                "turnaround_percentile": 98.0,
                "revenue_growth": 0.60,
                "revenue_percentile": 95.0,
                "momentum_percentile": 90.0,
                "rps": 88.0,
                "high_proximity": 0.90,
                "liquid": True,
            },
            {
                "symbol": "SH600001",
                "profit_current": -5.0,
                "turnaround_percentile": 99.0,
                "revenue_growth": 0.80,
                "revenue_percentile": 99.0,
                "momentum_percentile": 95.0,
                "rps": 95.0,
                "high_proximity": 0.95,
                "liquid": True,
            },
        ]
    )

    selected = engine.select_candidates(features, "a-share-cycle-turnaround")

    assert selected["symbol"].tolist() == ["SH688525"]


def test_market_filter_scales_exposure_instead_of_forcing_all_cash():
    engine = load_engine()
    rising = pd.Series(np.linspace(80.0, 120.0, 300))
    falling = pd.Series(np.linspace(120.0, 80.0, 300))

    assert engine.market_exposure(rising, "huachuang-2019-available") == 1.0
    assert engine.market_exposure(falling, "huachuang-2019-available") == 1.0
    assert engine.market_exposure(falling, "shenwan-2018-lite") == 0.5
    assert engine.market_exposure(falling, "a-share-adaptive") == 0.5
    assert engine.market_exposure(falling, "huachuang-2-risk-scaled") == 0.5


def test_huachuang_2_risk_overlay_does_not_change_stock_selection():
    engine = load_engine()
    features = pd.DataFrame(
        [
            {
                "symbol": "SH600001",
                "growth_percentile": 90.0,
                "momentum_percentile": 95.0,
                "liquid": True,
            },
            {
                "symbol": "SH600002",
                "growth_percentile": 70.0,
                "momentum_percentile": 99.0,
                "liquid": True,
            },
        ]
    )

    plain = engine.select_candidates(features, "huachuang-2-lite")
    scaled = engine.select_candidates(features, "huachuang-2-risk-scaled")

    assert plain["symbol"].tolist() == scaled["symbol"].tolist() == ["SH600001"]


def test_monthly_rebalance_uses_first_trade_date_only():
    engine = load_engine()
    dates = pd.DatetimeIndex(
        pd.to_datetime(
            ["2025-01-02", "2025-01-03", "2025-02-05", "2025-02-06", "2025-03-03"]
        )
    )

    assert engine.monthly_rebalance_dates(dates) == {
        pd.Timestamp("2025-01-02"),
        pd.Timestamp("2025-02-05"),
        pd.Timestamp("2025-03-03"),
    }
