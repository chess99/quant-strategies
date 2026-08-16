import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd


FAMILY = Path(__file__).resolve().parents[1]
MODULE = FAMILY / "v2_research.py"


def load_module():
    sys.path.insert(0, str(FAMILY))
    spec = importlib.util.spec_from_file_location("etf_core_rotation_v2_research", MODULE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_frozen_v2_candidate_matches_preregistered_contract():
    module = load_module()
    config = module.V2Config()
    assert config.core_weights == (
        ("SH510300", 0.4),
        ("SH511010", 0.4),
        ("SH518880", 0.2),
    )
    assert config.active_sleeve == 0.30
    assert config.active_single_symbol_cap == 0.15
    assert config.lookbacks == (63, 126, 252)
    assert config.minimum_excess_horizons == 2
    assert config.minimum_dispersion_iqr == 0.10
    assert config.top_k == 3
    assert config.rank_buffer == 2
    assert config.maximum_pair_correlation == 0.90
    assert config.minimum_adv20 == 20_000_000.0
    assert config.maximum_adv_participation == 0.005


def test_defensive_hurdle_is_per_horizon_maximum_of_zero_bond_and_cash():
    module = load_module()
    date = pd.Timestamp("2024-01-10")
    close = pd.DataFrame(
        {
            "SH511010": [100.0, 102.0, 99.0, 105.0],
            "SH511880": [100.0, 101.0, 103.0, 104.0],
        },
        index=pd.to_datetime(["2023-09-01", "2023-10-01", "2023-12-01", date]),
    )
    hurdles = module.defensive_hurdles_from_prices(
        close,
        date,
        (1, 2, 3),
        bond_symbol="SH511010",
        cash_symbol="SH511880",
    )
    assert np.isclose(hurdles[1], max(0.0, 105.0 / 99.0 - 1, 104.0 / 103.0 - 1))
    assert np.isclose(hurdles[2], max(0.0, 105.0 / 102.0 - 1, 104.0 / 101.0 - 1))
    assert np.isclose(hurdles[3], 0.05)


def test_excess_gate_counts_horizons_against_investable_hurdles():
    module = load_module()
    ranked = pd.DataFrame(
        {
            "r63": [0.08, 0.02],
            "r126": [0.12, 0.02],
            "r252": [-0.01, 0.20],
        },
        index=["leader", "mixed"],
    )
    frame = module.add_excess_gate(
        ranked,
        (63, 126, 252),
        {63: 0.03, 126: 0.05, 252: 0.00},
        minimum_horizons=2,
    )
    assert frame.at["leader", "excess_count"] == 2
    assert bool(frame.at["leader", "excess_pass"])
    assert frame.at["mixed", "excess_count"] == 1
    assert not bool(frame.at["mixed", "excess_pass"])


def test_unused_active_budget_returns_pro_rata_to_strategic_core():
    module = load_module()
    config = module.V2Config()
    full = module.compose_core_and_satellite(config, ["sector_a", "sector_b", "sector_c"])
    assert np.isclose(sum(full.values()), 1.0)
    assert np.isclose(full["sector_a"], 0.10)
    assert np.isclose(full["SH510300"], 0.28)
    assert np.isclose(full["SH511010"], 0.28)
    assert np.isclose(full["SH518880"], 0.14)

    partial = module.compose_core_and_satellite(config, ["sector_a"])
    assert np.isclose(sum(partial.values()), 1.0)
    assert np.isclose(partial["sector_a"], 0.15)
    assert np.isclose(partial["SH510300"], 0.34)
    assert np.isclose(partial["SH511010"], 0.34)
    assert np.isclose(partial["SH518880"], 0.17)

    core_only = module.compose_core_and_satellite(config, [])
    assert core_only == {"SH510300": 0.4, "SH511010": 0.4, "SH518880": 0.2}


def test_parameter_grid_has_all_preregistered_combinations_and_frozen_candidate_once():
    module = load_module()
    frozen = module.V2Config()
    configs = module.parameter_configs(frozen)
    assert len(configs) == 2187
    combinations = {
        (
            config.lookbacks,
            config.top_k,
            config.active_sleeve,
            config.minimum_excess_horizons,
            config.minimum_dispersion_iqr,
            config.rank_buffer,
            config.maximum_pair_correlation,
        )
        for config in configs
    }
    assert len(combinations) == 2187
    matches = [
        config
        for config in configs
        if config.lookbacks == frozen.lookbacks
        and config.top_k == frozen.top_k
        and config.active_sleeve == frozen.active_sleeve
        and config.minimum_excess_horizons == frozen.minimum_excess_horizons
        and config.minimum_dispersion_iqr == frozen.minimum_dispersion_iqr
        and config.rank_buffer == frozen.rank_buffer
        and config.maximum_pair_correlation == frozen.maximum_pair_correlation
    ]
    assert len(matches) == 1


def test_module_factorial_contains_all_sixteen_combinations():
    module = load_module()
    configs = module.module_factorial_configs(module.V2Config())
    assert len(configs) == 16
    combinations = {
        (
            config.use_excess_hurdle,
            config.use_dispersion_gate,
            config.use_rank_buffer,
            config.use_correlation_guard,
        )
        for config in configs
    }
    assert len(combinations) == 16


def test_success_criteria_are_mechanical_and_not_repaired_after_results():
    module = load_module()
    evaluation = module.evaluate_success_criteria(
        {
            "cost20_v2_cagr": 0.06,
            "cost20_core_cagr": 0.05,
            "rolling_win_ratio": 0.62,
            "worst_rolling_active_excess": -0.08,
            "v2_sharpe": 0.60,
            "core_sharpe": 0.52,
            "v2_maximum_drawdown": 0.25,
            "core_maximum_drawdown": 0.27,
            "v2_worst_rolling_return": 0.01,
            "core_worst_rolling_return": -0.02,
            "satellite_sharpe": 0.10,
            "satellite_20bp_sharpe": 0.02,
            "pbo": 0.35,
            "frozen_dsr_probability": 0.85,
            "top1_positive_contribution_share": 0.20,
            "exclude_top1_active_excess": 0.01,
            "capacity_10m_average_active_exposure": 0.22,
            "capacity_10m_active_excess": 0.005,
            "local_active_excess": 0.01,
            "joinquant_pit_active_excess": 0.001,
            "joinquant_official_active_excess": 0.001,
        }
    )
    assert evaluation["overall_pass"]
    failed = dict(evaluation["criteria"])
    assert all(item["passed"] for item in failed.values())


def test_platform_criterion_checks_sign_consistency_not_positive_excess():
    module = load_module()
    common = {
        "cost20_v2_cagr": 0.04,
        "cost20_core_cagr": 0.05,
        "rolling_win_ratio": 0.20,
        "worst_rolling_active_excess": -0.20,
        "v2_sharpe": 0.40,
        "core_sharpe": 0.50,
        "v2_maximum_drawdown": 0.30,
        "core_maximum_drawdown": 0.20,
        "v2_worst_rolling_return": -0.20,
        "core_worst_rolling_return": -0.10,
        "satellite_sharpe": -0.10,
        "satellite_20bp_sharpe": -0.20,
        "pbo": 0.50,
        "frozen_dsr_probability": 0.70,
        "top1_positive_contribution_share": 0.10,
        "exclude_top1_active_excess": -0.01,
        "capacity_10m_average_active_exposure": 0.10,
        "capacity_10m_active_excess": -0.01,
        "local_active_excess": -0.018,
    }
    consistent = module.evaluate_success_criteria(
        {
            **common,
            "joinquant_pit_active_excess": -0.008,
            "joinquant_official_active_excess": -0.007,
        }
    )
    assert consistent["criteria"]["platform"]["passed"]

    reversed_sign = module.evaluate_success_criteria(
        {
            **common,
            "joinquant_pit_active_excess": -0.008,
            "joinquant_official_active_excess": 0.007,
        }
    )
    assert not reversed_sign["criteria"]["platform"]["passed"]
