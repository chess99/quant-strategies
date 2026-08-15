import importlib.util
import sys
from pathlib import Path

import pandas as pd


FAMILY = Path(__file__).resolve().parents[1]
MODULE = FAMILY / "phase2_research.py"


def load_module():
    sys.path.insert(0, str(FAMILY))
    spec = importlib.util.spec_from_file_location("etf_core_rotation_phase2", MODULE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_module_factorial_contains_all_sixty_four_combinations():
    module = load_module()
    configs = module.module_factorial_configs(module.engine.StrategyConfig())
    assert len(configs) == 64
    combinations = {
        tuple(bool(getattr(config, flag)) for flag in module.MODULE_FLAGS)
        for config in configs
    }
    assert len(combinations) == 64
    assert all(config.use_top_k for config in configs)


def test_paired_effects_average_over_all_other_module_states():
    module = load_module()
    rows = []
    for config in module.module_factorial_configs(module.engine.StrategyConfig()):
        enabled = sum(bool(getattr(config, flag)) for flag in module.MODULE_FLAGS)
        row = {
            "period": "full",
            **{flag: bool(getattr(config, flag)) for flag in module.MODULE_FLAGS},
            "annualized_return": enabled * 0.01,
            "maximum_drawdown": 0.5 - enabled * 0.01,
            "sharpe": enabled * 0.1,
            "annualized_turnover": 10.0 + enabled,
            "average_risk_weight": enabled * 0.05,
        }
        rows.append(row)
    effects = module.paired_module_effects(pd.DataFrame(rows))
    assert len(effects) == len(module.MODULE_FLAGS)
    assert effects["pair_count"].eq(32).all()
    assert effects["mean_delta_sharpe"].round(12).eq(0.1).all()
    assert effects["positive_sharpe_pair_ratio"].eq(1.0).all()


def test_local_symbol_conversion_matches_joinquant_codes():
    module = load_module()
    assert module.local_to_joinquant("SH510300") == "510300.XSHG"
    assert module.local_to_joinquant("SZ159915") == "159915.XSHE"
