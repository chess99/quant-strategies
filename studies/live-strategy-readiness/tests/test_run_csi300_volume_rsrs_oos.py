import importlib.util
import json
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


def test_committed_oos_fails_without_parameter_selection_and_binds_hashes():
    candidate_dir = MODULE.CANDIDATE_DIR
    manifest = json.loads(
        (candidate_dir / "oos-run-manifest.json").read_text(encoding="utf-8")
    )
    scorecard = json.loads(
        (candidate_dir / "live-readiness-scorecard.json").read_text(encoding="utf-8")
    )

    assert manifest["source_sha256"] == MODULE.sha256_file(MODULE.base.SOURCE_PATH)
    assert manifest["base_engine_sha256"] == MODULE.sha256_file(MODULE.BASE_PATH)
    assert manifest["oos_engine_sha256"] == MODULE.sha256_file(MODULE_PATH)
    assert manifest["protocol_sha256"] == MODULE.sha256_file(MODULE.base.PROTOCOL_PATH)
    assert manifest["parameter_selection_used_oos"] is False
    assert manifest["decision"]["passed"] is False
    assert manifest["decision"]["pass_count"] == 2
    assert scorecard["status"] == "R1"
    assert scorecard["parameter_selection_used_oos"] is False

    oos = pd.read_csv(candidate_dir / "oos.csv").set_index("scenario")
    strategy = oos.loc["rsrs-baseline-cost"]
    buy_hold = oos.loc["csi300-etf-buy-hold"]
    half_cash = oos.loc["static-50pct-etf-cash"]
    assert strategy["sharpe"] < buy_hold["sharpe"]
    assert strategy["sharpe"] < half_cash["sharpe"]
    assert strategy["maximum_drawdown"] > half_cash["maximum_drawdown"]
