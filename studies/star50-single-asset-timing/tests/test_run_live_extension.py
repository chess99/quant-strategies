from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd


STUDY_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = STUDY_DIR / "run_live_extension.py"


def load_module():
    spec = importlib.util.spec_from_file_location("star50_live_extension", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def synthetic_bars(periods=800):
    dates = pd.bdate_range("2022-01-03", periods=periods)
    phase = np.linspace(0.0, 28.0, periods)
    close = 100.0 + np.linspace(0.0, 35.0, periods) + 12.0 * np.sin(phase)
    return pd.DataFrame(
        {
            "symbol": "SH588000",
            "open": close * (1.0 + 0.001 * np.cos(phase)),
            "high": close * 1.015,
            "low": close * 0.985,
            "close": close,
            "volume": 50_000_000 + np.arange(periods) * 1000,
            "amount": close * (50_000_000 + np.arange(periods) * 1000),
        },
        index=dates,
    )


def test_registry_is_preregistered_and_generation_bounded():
    module = load_module()
    configs = module.build_production_configs()

    assert {config.generation for config in configs} == {"G0", "G1", "G2", "G3"}
    assert len(configs) == 38
    assert len({config.name for config in configs}) == len(configs)
    assert {config.objective for config in configs} == {"risk", "return", "balanced"}
    assert sum(config.name == "risk-core__trend-200-vol-60-target-0p15" for config in configs) == 1


def test_hysteresis_requires_distinct_entry_and_exit_boundaries():
    module = load_module()
    index = pd.bdate_range("2025-01-02", periods=8)
    moving_average = pd.Series(100.0, index=index)
    close = pd.Series([99.0, 101.0, 103.0, 101.0, 99.0, 97.0, 99.0, 103.0], index=index)

    state = module.hysteresis_state(close, moving_average, 0.02)

    assert state.tolist() == [False, False, True, True, True, False, False, True]


def test_minimum_rebalance_change_reduces_small_target_updates_but_exits_immediately():
    module = load_module()
    index = pd.bdate_range("2025-01-02", periods=7)
    target = pd.Series([0.20, 0.23, 0.27, 0.34, 0.32, 0.0, 0.04], index=index)

    filtered = module.apply_rebalance_threshold(target, 0.10)

    assert filtered.tolist() == [0.20, 0.20, 0.20, 0.34, 0.34, 0.0, 0.04]


def test_generation_targets_are_causal_and_bounded():
    module = load_module()
    original = synthetic_bars()
    changed = original.copy()
    changed.iloc[-1, changed.columns.get_loc("close")] *= 1.7
    changed.iloc[-1, changed.columns.get_loc("high")] *= 1.7
    changed.iloc[-1, changed.columns.get_loc("low")] *= 1.4

    for config in module.build_production_configs():
        first = module.generate_production_target(original, config)
        second = module.generate_production_target(changed, config)
        pd.testing.assert_series_equal(first.iloc[:-1], second.iloc[:-1])
        assert first.between(0.0, module.TARGET_WEIGHT).all()


def test_pareto_front_rejects_strictly_dominated_candidate():
    module = load_module()
    metrics = pd.DataFrame(
        [
            {"config": "a", "annualized_return": 0.20, "maximum_drawdown": 0.10, "sharpe": 1.2, "turnover": 5.0},
            {"config": "b", "annualized_return": 0.18, "maximum_drawdown": 0.12, "sharpe": 1.0, "turnover": 6.0},
            {"config": "c", "annualized_return": 0.25, "maximum_drawdown": 0.18, "sharpe": 1.3, "turnover": 8.0},
        ]
    )

    frontier = module.pareto_front(metrics)

    assert set(frontier["config"]) == {"a", "c"}


def test_objective_gates_use_distinct_mandates():
    module = load_module()
    benchmark = {
        "annualized_return": 0.30,
        "maximum_drawdown": 0.30,
        "sharpe": 0.80,
    }
    common = {
        "annualized_return": 0.20,
        "maximum_drawdown": 0.15,
        "sharpe": 1.20,
        "calmar": 1.33,
        "turnover": 8.0,
        "positive_fold_ratio": 0.60,
        "worst_fold_return": -0.10,
        "slippage_20bp_annualized": 0.18,
        "second_next_open_annualized": 0.15,
    }

    risk = module.evaluate_objective_gate("risk", common, benchmark)
    enhanced = module.evaluate_objective_gate("return", common, benchmark)

    assert risk["candidate"]
    assert not enhanced["candidate"]


def test_paired_metric_bootstrap_is_deterministic_and_bounded():
    module = load_module()
    index = pd.bdate_range("2024-01-02", periods=160)
    strategy = pd.Series(np.sin(np.arange(160) / 8.0) / 100.0 + 0.0004, index=index)
    benchmark = pd.Series(np.cos(np.arange(160) / 10.0) / 100.0, index=index)

    first = module.paired_metric_bootstrap(strategy, benchmark, 20, 100, 17)
    second = module.paired_metric_bootstrap(strategy, benchmark, 20, 100, 17)

    assert first == second
    for key in (
        "probability_return_above_benchmark",
        "probability_drawdown_below_benchmark",
        "probability_sharpe_above_benchmark",
    ):
        assert 0.0 <= first[key] <= 1.0


def test_protocol_contains_honest_historical_evidence_boundary():
    text = (STUDY_DIR / "LIVE_EXTENSION.md").read_text(encoding="utf-8")

    assert "事后开发证据" in text
    assert "8 个新季度" in text
    assert "看过G3结果后不再" in text


def test_live_extension_files_contain_no_machine_absolute_paths():
    windows_absolute = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]")
    for filename in ("LIVE_EXTENSION.md", "run_live_extension.py"):
        text = (STUDY_DIR / filename).read_text(encoding="utf-8")
        assert not windows_absolute.search(text)
