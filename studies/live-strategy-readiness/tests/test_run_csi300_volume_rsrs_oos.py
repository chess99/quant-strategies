import importlib.util
import sys
from pathlib import Path

import pandas as pd


STUDY_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = STUDY_DIR / "run_csi300_volume_rsrs_oos.py"
SPEC = importlib.util.spec_from_file_location(
    "live_readiness_run_csi300_volume_rsrs_oos", MODULE_PATH
)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_oos_targets_use_prior_session_and_reset_flat():
    dates = pd.date_range("2020-05-11", periods=6, freq="B")
    features = pd.DataFrame(
        {
            "trade_date": dates,
            "score": [0.0, 0.9, 0.2, -0.9, 0.0, 0.9],
        }
    )
    calendar = pd.DatetimeIndex(dates[2:])

    targets, signals = MODULE.build_oos_targets(features, calendar)

    assert signals.iloc[0]["observation_date"] == dates[1]
    assert targets[dates[2]] == 1
    assert targets[dates[3]] == 1
    assert targets[dates[4]] == 0


def test_scenarios_freeze_realistic_and_double_friction():
    by_name = {scenario.name: scenario for scenario in MODULE.SCENARIOS}

    assert by_name["rsrs-baseline-cost"].commission == 0.0003
    assert by_name["rsrs-baseline-cost"].slippage == 0.0005
    assert by_name["rsrs-double-cost"].commission == 0.0006
    assert by_name["rsrs-double-cost"].slippage == 0.001
    assert set(by_name) == {
        "rsrs-baseline-cost",
        "rsrs-double-cost",
        "csi300-etf-buy-hold",
        "static-50pct-etf-cash",
    }


def test_oos_gate_requires_all_preregistered_checks():
    template = {
        "total_return": 0.5,
        "annualized_return": 0.08,
        "maximum_drawdown": 0.20,
        "sharpe": 0.8,
        "completed_positions": 5,
    }
    results = [
        {**template, "scenario": "rsrs-baseline-cost"},
        {**template, "scenario": "rsrs-double-cost"},
        {**template, "scenario": "csi300-etf-buy-hold", "sharpe": 0.5},
        {**template, "scenario": "static-50pct-etf-cash", "sharpe": 0.6},
    ]

    decision = MODULE.evaluate_oos(results)

    assert decision["passed"] is True
    assert decision["pass_count"] == decision["gate_count"] == 6
