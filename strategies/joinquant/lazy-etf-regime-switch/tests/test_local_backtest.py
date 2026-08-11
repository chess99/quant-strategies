import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


FAMILY = Path(__file__).resolve().parents[1]
ENGINE = FAMILY / "local_backtest.py"


def load_engine():
    spec = importlib.util.spec_from_file_location("lazy_etf_local", ENGINE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_weekly_execution_is_strictly_after_observation():
    engine = load_engine()
    dates = pd.bdate_range("2024-01-01", "2024-01-19")
    pairs = engine.weekly_execution_pairs(dates)
    assert pairs
    for observation, execution in pairs:
        assert execution > observation
        location = dates.get_loc(observation)
        assert dates[location + 1] == execution


def test_standard_and_close_only_cci_are_distinct():
    engine = load_engine()
    close = np.arange(1.0, 15.0)
    high = close + np.linspace(0.1, 3.0, len(close))
    low = close - 0.1
    close_only = engine.close_only_cci(close, 14)
    standard = engine.standard_cci(high, low, close, 14)
    assert np.isfinite(close_only)
    assert np.isfinite(standard)
    assert close_only != standard


def test_model_layers_have_fixed_priority():
    engine = load_engine()
    signals = engine.SignalState(
        gem_close_cci=150.0,
        gem_standard_cci=140.0,
        nasdaq_above_ma=True,
        gold_above_ma=True,
        momentum={"gem": 0.10, "nasdaq": 0.20, "gold": 0.30},
        eligible_ma40={"gem": True, "nasdaq": True, "gold": True},
    )
    assert engine.choose_model_asset("m0", signals) == "nasdaq"
    assert engine.choose_model_asset("m1", signals) == "nasdaq"
    assert engine.choose_model_asset("m2", signals) == "nasdaq"
    assert engine.choose_model_asset("m3", signals) == "gem"
    assert engine.choose_model_asset("m4", signals) == "gem"
    assert engine.choose_model_asset("b2", signals) == "gold"
    assert engine.choose_model_asset("b3", signals) == "gold"


def test_m4_falls_back_from_nasdaq_to_gold_then_cash():
    engine = load_engine()
    base = {
        "gem_close_cci": 0.0,
        "gem_standard_cci": 0.0,
        "momentum": {"gem": -0.1, "nasdaq": -0.1, "gold": -0.1},
        "eligible_ma40": {"gem": False, "nasdaq": False, "gold": False},
    }
    gold = engine.SignalState(
        nasdaq_above_ma=False, gold_above_ma=True, **base
    )
    cash = engine.SignalState(
        nasdaq_above_ma=False, gold_above_ma=False, **base
    )
    assert engine.choose_model_asset("m4", gold) == "gold"
    assert engine.choose_model_asset("m4", cash) is None
