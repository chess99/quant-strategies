import ast
import datetime as dt
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
STRATEGY_PATH = ROOT / "variants" / "formal_candidate.py"


def load_strategy():
    spec = importlib.util.spec_from_file_location(
        "oneil_canslim_formal_candidate", STRATEGY_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_is_self_contained_and_joinquant_compatible():
    source = STRATEGY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert "from __future__ import annotations" not in source
    assert "import trading_os" not in source
    assert "current_data.get(" not in source
    assert 'set_option("avoid_future_data", True)' in source
    assert 'get_all_securities(["stock"], date=observation_date)' in source
    assert "finance.STK_FIN_FORCAST.pub_date <= observation_date" in source
    unqualified = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"all", "any", "sum"}
    ]
    assert unqualified == []


def test_forecast_features_use_only_information_published_by_observation_date():
    strategy = load_strategy()
    rows = pd.DataFrame(
        [
            {
                "code": "688001.XSHG",
                "pub_date": "2025-03-01",
                "end_date": "2025-03-31",
                "profit_ratio_min": 40.0,
                "profit_ratio_max": 60.0,
                "profit_min": -30.0,
                "profit_max": -10.0,
                "profit_last": -80.0,
            },
            {
                "code": "688001.XSHG",
                "pub_date": "2025-04-10",
                "end_date": "2025-03-31",
                "profit_ratio_min": 70.0,
                "profit_ratio_max": 90.0,
                "profit_min": 20.0,
                "profit_max": 30.0,
                "profit_last": -80.0,
            },
        ]
    )

    result = strategy.prepare_forecast_features(rows, dt.date(2025, 3, 31))

    assert list(result["code"]) == ["688001.XSHG"]
    feature = result.iloc[0]
    assert feature["forecast_pub_date"] == pd.Timestamp("2025-03-01")
    assert feature["forecast_profit_growth"] == 0.50
    assert feature["forecast_profit_mid"] == -20.0
    assert bool(feature["forecast_positive"]) is False
    assert bool(feature["forecast_turnaround"]) is False


def test_established_growth_track_requires_realized_growth_and_annual_quality():
    strategy = load_strategy()
    row = {
        "current_eps_growth": 0.30,
        "core_profit_growth": 0.25,
        "current_sales_growth": 0.22,
        "annual_eps_cagr": 0.18,
        "annual_eps_increasing": True,
        "roe": 0.19,
        "current_profit": 120.0,
        "year_ago_profit": 90.0,
        "forecast_positive": False,
        "forecast_turnaround": False,
        "forecast_profit_growth": np.nan,
        "rs_rating": 85.0,
        "industry_rs_rating": 80.0,
    }

    assert strategy.classify_fundamental_track(row) == "established_growth"


def test_emerging_leader_allows_loss_narrowing_when_sales_and_price_lead():
    strategy = load_strategy()
    row = {
        "current_eps_growth": np.nan,
        "core_profit_growth": np.nan,
        "current_sales_growth": 0.48,
        "annual_eps_cagr": np.nan,
        "annual_eps_increasing": False,
        "roe": np.nan,
        "current_profit": -40.0,
        "year_ago_profit": -120.0,
        "forecast_positive": False,
        "forecast_turnaround": False,
        "forecast_profit_growth": np.nan,
        "rs_rating": 94.0,
        "industry_rs_rating": 82.0,
    }

    assert strategy.classify_fundamental_track(row) == "emerging_leader"

    row["current_profit"] = -150.0
    assert strategy.classify_fundamental_track(row) is None

    row["forecast_turnaround"] = True
    assert strategy.classify_fundamental_track(row) == "emerging_leader"


def test_positive_forecast_needs_growth_threshold_unless_it_turns_profitable():
    strategy = load_strategy()
    row = {
        "current_eps_growth": np.nan,
        "core_profit_growth": np.nan,
        "current_sales_growth": 0.45,
        "annual_eps_cagr": np.nan,
        "roe": np.nan,
        "current_profit": -150.0,
        "year_ago_profit": -100.0,
        "forecast_positive": True,
        "forecast_turnaround": False,
        "forecast_profit_growth": np.nan,
        "rs_rating": 95.0,
        "industry_rs_rating": 85.0,
    }

    assert strategy.classify_fundamental_track(row) is None
    row["forecast_profit_growth"] = 0.50
    assert strategy.classify_fundamental_track(row) == "emerging_leader"


def test_market_vote_scales_risk_with_confirmed_index_count():
    strategy = load_strategy()
    confirmed = strategy.MARKET_CONFIRMED
    correction = strategy.MARKET_CORRECTION

    strong = strategy.aggregate_market_states(
        {"sh": confirmed, "hs300": confirmed, "cyb": confirmed, "star": correction}
    )
    mixed = strategy.aggregate_market_states(
        {"sh": confirmed, "hs300": confirmed, "cyb": correction, "star": correction}
    )
    weak = strategy.aggregate_market_states(
        {"sh": correction, "hs300": correction, "cyb": confirmed, "star": correction}
    )
    risk_off = strategy.aggregate_market_states(
        {"sh": correction, "hs300": correction, "cyb": correction, "star": correction}
    )

    assert (strong["state"], strong["exposure"]) == (confirmed, 1.0)
    assert (mixed["state"], mixed["exposure"]) == (confirmed, 0.70)
    assert (weak["state"], weak["exposure"]) == (
        strategy.MARKET_UNDER_PRESSURE,
        0.35,
    )
    assert (risk_off["state"], risk_off["exposure"]) == (correction, 0.0)


def test_profitable_position_exits_on_heavy_volume_twenty_day_break():
    strategy = load_strategy()

    reason = strategy.position_exit_reason(
        current_price=112.0,
        technical_close=108.0,
        average_cost=100.0,
        pivot=100.0,
        holding_days=45,
        close_20d_ma=110.0,
        close_50d_ma=101.0,
        volume_ratio=1.30,
        market_state=strategy.MARKET_CONFIRMED,
        power_hold=False,
    )

    assert reason == "twenty_day_break"
