import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


STUDY_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = STUDY_DIR / "run_gac_zscore_mean_reversion.py"
SPEC = importlib.util.spec_from_file_location("live_readiness_gac_zscore", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_zscore_matches_60_residuals_after_20_day_mean():
    x = np.arange(100, dtype=float)
    close = pd.Series(10.0 + x * 0.05 + np.sin(x / 4.0))
    expected_sub = close.rolling(20).mean().rsub(close).dropna().tail(60)
    expected = (expected_sub.iloc[-1] - expected_sub.mean()) / expected_sub.std(ddof=1)

    actual = MODULE.zscore_series(close).iloc[-1]

    assert actual == pytest.approx(expected)


def test_hysteresis_uses_frozen_asymmetric_thresholds():
    scores = pd.Series([-2.1, -1.0, 0.9, 1.1, -1.9])

    positions = MODULE.hysteresis_positions(scores)

    assert positions.tolist() == [1, 1, 1, 0, 0]


def test_protocol_keeps_oos_untuned_and_single_stock_explicit():
    protocol = MODULE.load_protocol()

    assert protocol["source"]["oos_integrity_grade"] == "B"
    assert protocol["frozen_parameters"]["symbol"] == "SH601238"
    assert protocol["frozen_parameters"]["buy_threshold"] == -2.0
    assert protocol["post_publication_window_if_unlocked"][
        "parameter_selection_used_window"
    ] is False


def test_committed_calibration_unlocks_oos_and_binds_hashes():
    candidate_dir = MODULE.CANDIDATE_DIR
    decision = json.loads(
        (candidate_dir / "version-calibration-decision.json").read_text(encoding="utf-8")
    )
    manifest = json.loads(
        (candidate_dir / "version-calibration-manifest.json").read_text(encoding="utf-8")
    )

    assert decision["unlocked"] is True
    assert decision["pass_count"] == 4
    assert all(decision["gates_passed"].values())
    assert decision["post_publication_performance_calculated"] is False
    assert manifest["source_sha256"] == MODULE.sha256_file(MODULE.SOURCE_PATH)
    assert manifest["engine_sha256"] == MODULE.sha256_file(MODULE_PATH)
    assert manifest["protocol_sha256"] == MODULE.sha256_file(MODULE.PROTOCOL_PATH)
    assert manifest["parameter_selection_used_window"] is False


def test_committed_oos_fails_and_keeps_parameters_untuned():
    candidate_dir = MODULE.CANDIDATE_DIR
    decision = json.loads((candidate_dir / "oos-decision.json").read_text(encoding="utf-8"))
    manifest = json.loads(
        (candidate_dir / "oos-run-manifest.json").read_text(encoding="utf-8")
    )
    scorecard = json.loads(
        (candidate_dir / "live-readiness-scorecard.json").read_text(encoding="utf-8")
    )

    assert decision["passed"] is False
    assert decision["pass_count"] == 1
    assert manifest["source_sha256"] == MODULE.sha256_file(MODULE.SOURCE_PATH)
    assert manifest["engine_sha256"] == MODULE.sha256_file(MODULE_PATH)
    assert manifest["parameter_selection_used_window"] is False
    assert scorecard["status"] == "R1"
    assert scorecard["parameter_selection_used_oos"] is False

    oos = pd.read_csv(candidate_dir / "oos.csv").set_index("scenario")
    strategy = oos.loc["zscore-baseline-cost"]
    half = oos.loc["static-50pct-gac-cash"]
    assert strategy["total_return"] < 0.0
    assert strategy["sharpe"] < half["sharpe"]
    assert strategy["maximum_drawdown"] > half["maximum_drawdown"]
