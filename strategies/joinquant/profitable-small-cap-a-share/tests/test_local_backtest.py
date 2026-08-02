import importlib.util
from pathlib import Path

import pandas as pd
import pytest


FAMILY = Path(__file__).resolve().parents[1]
MODULE_PATH = FAMILY / "local_backtest.py"


def load_module():
    spec = importlib.util.spec_from_file_location("profitable_small_cap_local", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def candidate_frame():
    return pd.DataFrame(
        [
            {"symbol": "A", "market_cap": 1, "raw_close": 5, "quarter_roe": 2, "quarter_roa": 1, "average_money": 20, "industry": "I1", "eligible_base": True},
            {"symbol": "B", "market_cap": 2, "raw_close": 5, "quarter_roe": 2, "quarter_roa": 1, "average_money": 20, "industry": "I1", "eligible_base": True},
            {"symbol": "C", "market_cap": 3, "raw_close": 5, "quarter_roe": 2, "quarter_roa": 1, "average_money": 20, "industry": "I1", "eligible_base": True},
            {"symbol": "D", "market_cap": 4, "raw_close": 5, "quarter_roe": 2, "quarter_roa": 1, "average_money": 20, "industry": "I2", "eligible_base": True},
            {"symbol": "E", "market_cap": 5, "raw_close": 12, "quarter_roe": 2, "quarter_roa": 1, "average_money": 20, "industry": "I3", "eligible_base": True},
            {"symbol": "F", "market_cap": 6, "raw_close": 5, "quarter_roe": -1, "quarter_roa": 1, "average_money": 20, "industry": "I4", "eligible_base": True},
        ]
    )


def test_selection_applies_quality_price_liquidity_and_industry_caps():
    module = load_module()
    config = module.ExperimentConfig(
        name="test",
        stock_count=3,
        minimum_quarter_roe=1,
        minimum_quarter_roa=0.5,
        maximum_price=10,
        minimum_average_money=10,
        maximum_industry_count=2,
    )
    assert module.select_candidates(candidate_frame(), config) == ["A", "B", "D"]


def test_selection_can_remove_nominal_price_cap():
    module = load_module()
    config = module.ExperimentConfig(
        name="test",
        stock_count=5,
        minimum_quarter_roe=1,
        minimum_quarter_roa=0.5,
        maximum_price=None,
        minimum_average_money=10,
        maximum_industry_count=5,
    )
    assert "E" in module.select_candidates(candidate_frame(), config)


def test_published_configuration_keeps_original_numeric_thresholds():
    module = load_module()
    published = module.experiment_configs()[0]
    assert published.name == "published-core"
    assert published.stock_count == 10
    assert published.minimum_quarter_roe == 0.15
    assert published.minimum_quarter_roa == 0.10
    assert published.maximum_price == 10
    assert published.minimum_average_money == 0


def test_segment_metrics_accepts_an_empty_trade_ledger():
    module = load_module()
    equity = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2020-01-02", "2020-01-03"]),
            "total_value": [100.0, 101.0],
            "daily_return": [0.0, 0.01],
            "cash_ratio": [1.0, 1.0],
        }
    )
    metrics = module._segment_metrics(
        equity, pd.DataFrame(), "2020-01-01", "2020-12-31"
    )
    assert metrics["total_return"] == pytest.approx(0.01)


def test_risk_neighborhood_is_small_and_predeclared():
    module = load_module()
    risk = [config for config in module.experiment_configs() if config.name.startswith("risk-")]
    assert {config.risk_ma_days for config in risk} == {60, 120, 200}
    assert {config.risk_off_exposure for config in risk} == {0.0, 0.25, 0.5}
