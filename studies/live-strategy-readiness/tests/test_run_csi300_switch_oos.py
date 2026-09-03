import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


STUDY_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = STUDY_DIR / "run_csi300_switch_oos.py"
SPEC = importlib.util.spec_from_file_location("run_csi300_switch_oos", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_sell_signal_matches_frozen_path_rule():
    values = np.concatenate(
        [
            np.array([1.0]),
            np.linspace(2.0, 10.0, 24),
            np.linspace(9.0, 3.0, 7),
        ]
    )
    dates = pd.date_range("2021-01-01", periods=32, freq="B")

    assert MODULE.switch_signal(pd.Series(values, index=dates), dates[-1]) == 0


def test_buy_signal_matches_frozen_path_rule():
    values = np.concatenate(
        [np.array([5.0, 5.0, 10.0]), np.ones(9), np.full(10, 2.0), np.full(10, 3.0)]
    )
    dates = pd.date_range("2021-01-01", periods=32, freq="B")

    assert MODULE.switch_signal(pd.Series(values, index=dates), dates[-1]) == 1


def test_signal_uses_no_observation_after_requested_date():
    values = np.concatenate(
        [np.array([5.0, 5.0, 10.0]), np.ones(9), np.full(10, 2.0), np.full(10, 3.0)]
    )
    dates = pd.date_range("2021-01-01", periods=33, freq="B")
    close = pd.Series(np.append(values, 1_000_000.0), index=dates)

    assert MODULE.switch_signal(close, dates[-2]) == 1


def test_preregistered_source_hash_is_unchanged():
    assert MODULE.sha256_file(MODULE.SOURCE_PATH) == (
        "4f80ec6b4e207dd9cb53baabb5debfd16671229f8b3b92867781e29d79dccd51"
    )


def test_committed_oos_artifacts_preserve_the_failed_stop_decision():
    candidate_dir = STUDY_DIR / "results" / MODULE.CANDIDATE_ID
    manifest = json.loads(
        (candidate_dir / "oos-run-manifest.json").read_text(encoding="utf-8")
    )
    scorecard = json.loads(
        (candidate_dir / "live-readiness-scorecard.json").read_text(encoding="utf-8")
    )
    oos = pd.read_csv(candidate_dir / "oos.csv").set_index("scenario")

    assert manifest["source_sha256"] == MODULE.sha256_file(MODULE.SOURCE_PATH)
    assert manifest["engine_sha256"] == MODULE.sha256_file(MODULE_PATH)
    assert manifest["parameter_selection_used_oos"] is False
    assert scorecard["status"] == "R1"
    assert scorecard["hard_stop_triggered"] is True
    assert scorecard["parameter_selection_used_oos"] is False

    baseline = oos.loc["causal-baseline-cost"]
    static = oos.loc["static-50-50"]
    assert baseline["sharpe"] < 0.30
    assert baseline["maximum_drawdown"] > 0.30
    assert static["annualized_return"] > baseline["annualized_return"]
    assert static["maximum_drawdown"] < baseline["maximum_drawdown"]
    assert static["sharpe"] > baseline["sharpe"]
