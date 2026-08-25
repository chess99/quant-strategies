import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


STUDY_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = STUDY_DIR / "run_dynamic_volume_etf_rotation.py"
SPEC = importlib.util.spec_from_file_location(
    "live_readiness_run_dynamic_volume_etf_rotation", MODULE_PATH
)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_rank_uses_only_completed_observation_history():
    dates = pd.date_range("2024-01-02", periods=40, freq="B")
    bars = pd.DataFrame(
        {
            "trade_date": np.repeat(dates, 2),
            "symbol": ["A", "B"] * len(dates),
            "adjusted_close": np.ravel(
                np.column_stack(
                    [np.linspace(1.0, 1.4, len(dates)), np.linspace(1.0, 1.2, len(dates))]
                )
            ),
            "volume": np.ravel(
                np.column_stack([np.full(len(dates), 100.0), np.full(len(dates), 90.0)])
            ),
        }
    )
    observation = dates[-2]
    bars.loc[(bars["trade_date"] == dates[-1]) & (bars["symbol"] == "B"), "volume"] = 1e9

    features = MODULE.build_signal_features(bars)
    target, diagnostics = MODULE.select_target(features, observation, pool_size=2)

    assert target == "A"
    assert diagnostics["observation_date"] == observation.strftime("%Y-%m-%d")
    assert diagnostics["leader"] == "A"


def test_persistent_low_volume_switches_to_defensive_asset():
    dates = pd.date_range("2024-01-02", periods=45, freq="B")
    volume = np.concatenate([np.full(35, 100.0), np.linspace(90.0, 20.0, 10)])
    bars = pd.DataFrame(
        {
            "trade_date": dates,
            "symbol": "A",
            "adjusted_close": np.linspace(1.0, 1.5, len(dates)),
            "volume": volume,
        }
    )

    features = MODULE.build_signal_features(bars)
    target, diagnostics = MODULE.select_target(features, dates[-1], pool_size=1)

    assert diagnostics["low_volume_streak"] >= MODULE.LOW_VOLUME_STREAK
    assert target == MODULE.DEFENSIVE_SYMBOL


def test_protocol_freezes_calibration_before_post_publication_window():
    protocol = MODULE.load_protocol()

    assert protocol["status"] == "preregistered-before-local-results"
    assert protocol["public_calibration"]["must_run_before_oos"] is True
    assert protocol["public_calibration"]["stop_rule"].startswith(
        "Do not calculate post-publication"
    )
    assert protocol["post_publication_window_if_unlocked"][
        "parameter_selection_used_window"
    ] is False
    assert protocol["frozen_parameters"]["dynamic_pool_size"] == 7


def test_calibration_decision_requires_return_and_sharpe():
    public = {"annualized_return": 0.20, "maximum_drawdown": 0.30, "sharpe": 0.80}
    local = {
        "annualized_return": 0.18,
        "maximum_drawdown": 0.32,
        "sharpe": 0.75,
        "switch_event_count": 100,
    }

    decision = MODULE.evaluate_calibration(local, public, public_switch_events=110)

    assert decision["unlocked"] is True
    assert decision["pass_count"] == 4


def test_signal_switch_count_ignores_repeated_unavailable_target_attempts():
    targets = ["DEFENSIVE", "DEFENSIVE", "A", "A", "DEFENSIVE"]

    switches = MODULE.count_signal_switches(targets)

    assert switches == 2


@pytest.mark.parametrize("field,value", [("annualized_return", 0.10), ("sharpe", 0.40)])
def test_calibration_decision_stays_locked_when_mandatory_gate_fails(field, value):
    public = {"annualized_return": 0.20, "maximum_drawdown": 0.30, "sharpe": 0.80}
    local = {
        "annualized_return": 0.19,
        "maximum_drawdown": 0.31,
        "sharpe": 0.79,
        "switch_event_count": 100,
    }
    local[field] = value

    decision = MODULE.evaluate_calibration(local, public, public_switch_events=100)

    assert decision["unlocked"] is False


def test_committed_calibration_is_locked_and_binds_hashes():
    candidate_dir = STUDY_DIR / "results" / MODULE.CANDIDATE_ID
    manifest = json.loads(
        (candidate_dir / "version-calibration-manifest.json").read_text(encoding="utf-8")
    )
    decision = json.loads(
        (candidate_dir / "version-calibration-decision.json").read_text(encoding="utf-8")
    )
    scorecard = json.loads(
        (candidate_dir / "live-readiness-scorecard.json").read_text(encoding="utf-8")
    )

    assert manifest["source_sha256"] == MODULE.sha256_file(MODULE.SOURCE_PATH)
    assert manifest["engine_sha256"] == MODULE.sha256_file(MODULE_PATH)
    assert manifest["protocol_sha256"] == MODULE.sha256_file(MODULE.PROTOCOL_PATH)
    assert manifest["post_publication_performance_calculated"] is False
    assert decision["unlocked"] is False
    assert decision["pass_count"] == 2
    assert decision["gates_passed"] == {
        "annualized_return": False,
        "maximum_drawdown": False,
        "sharpe": True,
        "switch_event_count": True,
    }
    assert scorecard["status"] == "R0"
    assert scorecard["post_publication_performance_calculated"] is False

    oos = pd.read_csv(candidate_dir / "oos.csv")
    assert oos.loc[0, "status"] == "not-run"
    assert bool(oos.loc[0, "post_publication_performance_calculated"]) is False
