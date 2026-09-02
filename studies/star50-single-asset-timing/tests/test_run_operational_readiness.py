from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path


STUDY_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = STUDY_DIR / "run_operational_readiness.py"
INPUT_PATH = (
    STUDY_DIR
    / "results"
    / "2026-09-01__walk-forward-technical-families__tencent-yahoo-2020-2026-v1"
    / "raw"
    / "input-sh588000.csv"
)


def load_module():
    spec = importlib.util.spec_from_file_location("star50_operational_readiness_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_scenario_registry_is_preregistered_and_bounded():
    module = load_module()
    scenarios = module.build_scenarios()

    assert len(scenarios) == 132
    assert len({scenario.name for scenario in scenarios}) == 132
    assert {scenario.capital for scenario in scenarios} == set(module.CAPITAL_GRID)
    assert {scenario.volume_ratio for scenario in scenarios} == set(module.VOLUME_RATIOS)
    assert {scenario.slippage for scenario in scenarios} == set(module.SLIPPAGES)


def test_replay_respects_cash_lots_capacity_and_hash_chain():
    module = load_module()
    frame = module.engine.load_input_csv(INPUT_PATH)
    config = module.shadow.frozen_configs()[0]
    scenario = module.Scenario(
        model=config.name,
        capital=1_000_000.0,
        volume_ratio=0.01,
        slippage=0.002,
    )

    result = module.replay_scenario(frame, config, scenario)

    assert result["metrics"]["minimum_cash"] >= -0.01
    assert result["metrics"]["minimum_shares"] >= 0
    assert result["metrics"]["maximum_volume_participation"] <= 0.01 + 1e-12
    assert result["metrics"]["event_chain_valid"]
    assert result["metrics"]["p95_absolute_target_gap"] <= 0.02
    assert result["metrics"]["longest_unfinished_rebalance_days"] == 0
    assert result["metrics"]["filled_order_count"] == 31
    assert all(int(value) % 100 == 0 for value in result["equity"]["shares"])


def test_prefix_audit_and_fault_injection_pass():
    module = load_module()
    frame = module.engine.load_input_csv(INPUT_PATH)
    config = module.shadow.frozen_configs()[1]
    dates = list(frame.index[-3:])

    audit = module.causality_audit(frame, [config], dates=dates)
    faults = module.run_fault_injection()

    assert audit["matched"].all()
    assert len(audit) == 3
    assert faults["all_passed"]
    assert len(faults["cases"]) >= 12


def test_operations_files_contain_no_machine_absolute_paths():
    windows_absolute = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]")
    for filename in (
        "OPERATIONS_PROTOCOL.md",
        "run_shadow_operations.py",
        "run_operational_readiness.py",
    ):
        text = (STUDY_DIR / filename).read_text(encoding="utf-8")
        assert not windows_absolute.search(text)
