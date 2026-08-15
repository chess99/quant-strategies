import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd


FAMILY = Path(__file__).resolve().parents[1]
ENGINE = FAMILY / "local_backtest.py"


def load_engine():
    spec = importlib.util.spec_from_file_location("etf_core_rotation_local", ENGINE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_weekly_execution_is_strictly_causal():
    engine = load_engine()
    dates = pd.bdate_range("2024-01-01", "2024-01-31")
    pairs = engine.weekly_execution_pairs(dates)
    assert pairs
    for observation, execution in pairs:
        assert execution > observation
        assert dates[dates.get_loc(observation) + 1] == execution


def test_parameter_matrix_has_declared_full_factorial_count_and_baseline():
    engine = load_engine()
    baseline = engine.StrategyConfig()
    configs = engine.parameter_configs(baseline)
    assert len(configs) == 4 * 3 * 3 * 4 * 3 * 3 == 1296
    matches = [
        config
        for config in configs
        if config.top_k == 3
        and config.lookbacks == (63, 126, 252)
        and config.max_pair_corr == 0.90
        and config.target_portfolio_vol == 0.18
        and config.min_adv20 == 20_000_000
        and config.rank_buffer == 2
    ]
    assert len(matches) == 1


def test_weight_cap_does_not_force_risk_budget_when_assets_are_insufficient():
    engine = load_engine()
    two_assets = engine.cap_weights_without_forced_redistribution({"a": 0.8, "b": 0.2}, 0.4)
    assert two_assets == {"a": 0.4, "b": 0.4}
    three_assets = engine.cap_weights_without_forced_redistribution(
        {"a": 0.8, "b": 0.1, "c": 0.1}, 0.4
    )
    assert np.isclose(sum(three_assets.values()), 1.0)
    assert max(three_assets.values()) <= 0.4 + 1e-12


def test_ablation_activates_exactly_one_new_layer_at_each_step():
    engine = load_engine()
    configs = engine.ablation_configs(engine.StrategyConfig())
    flags = (
        "use_absolute_momentum",
        "use_top_k",
        "use_inverse_vol",
        "use_vol_target",
        "use_rank_buffer",
        "use_correlation_guard",
        "use_capacity",
    )
    counts = [sum(bool(getattr(config, flag)) for flag in flags) for config in configs]
    assert counts == [0, 1, 2, 3, 4, 5, 6, 7]


def test_pbo_reports_all_eight_block_half_splits():
    engine = load_engine()
    rng = np.random.default_rng(7)
    returns = rng.normal(0.0002, 0.01, size=(12, 160))
    dates = pd.bdate_range("2020-01-01", periods=160)
    splits, summary = engine.compute_pbo(returns, dates, [f"trial_{index}" for index in range(12)])
    assert len(splits) == 70
    assert summary["split_count"] == 70
    assert 0 <= summary["pbo"] <= 1


def test_strict_trade_participation_rounds_down_to_etf_lots():
    engine = load_engine()
    shares = engine.participation_limited_shares(
        requested_shares=1_000,
        mark_price=10.0,
        adv20=1_000_000.0,
        participation_rate=0.005,
    )
    assert shares == 500
    assert shares * 10.0 / 1_000_000.0 <= 0.005
    assert engine.participation_limited_shares(1_000, 10.0, None, 0.005) == 0
