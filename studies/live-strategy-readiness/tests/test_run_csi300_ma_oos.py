import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


STUDY_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = STUDY_DIR / "run_csi300_ma_oos.py"
SPEC = importlib.util.spec_from_file_location("run_csi300_ma_oos", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_ma_signal_is_risk_on_for_a_rising_frozen_window():
    dates = pd.date_range("2018-01-01", periods=60, freq="B")
    close = pd.Series(np.arange(1.0, 61.0), index=dates)

    assert MODULE.ma_signal(close, dates[-1]) == 1


def test_ma_signal_is_risk_off_for_a_falling_frozen_window():
    dates = pd.date_range("2018-01-01", periods=60, freq="B")
    close = pd.Series(np.arange(60.0, 0.0, -1.0), index=dates)

    assert MODULE.ma_signal(close, dates[-1]) == 0


def test_ma_signal_ignores_prices_after_the_observation_date():
    dates = pd.date_range("2018-01-01", periods=61, freq="B")
    close = pd.Series(np.append(np.arange(1.0, 61.0), -1_000_000.0), index=dates)

    assert MODULE.ma_signal(close, dates[-2]) == 1


def test_fixed_source_cost_keeps_the_declared_one_per_mille_sell_tax():
    model = MODULE.FixedTaxCostModel(fixed_sell_tax=0.001)

    assert model.stamp_tax_rate("stock", "buy", "2025-01-01") == 0.0
    assert model.stamp_tax_rate("stock", "sell", "2025-01-01") == 0.001


def test_preregistered_source_hash_is_unchanged():
    assert MODULE.sha256_file(MODULE.SOURCE_PATH) == (
        "8d67a7ead17d757ee2b2edd59ace74c29fcfcda0536dc859d1ffb95e905886c3"
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
    assert manifest["scenarios"][1]["execution_policy"] == "source-daily-order"
    assert scorecard["status"] == "R1"
    assert scorecard["hard_stop_triggered"] is True

    baseline = oos.loc["causal-baseline-cost"]
    buy_hold = oos.loc["csi300-buy-hold"]
    static = oos.loc["static-50pct-cash"]
    assert baseline["sharpe"] < 0.25
    assert baseline["maximum_drawdown"] > 0.35
    assert buy_hold["annualized_return"] > baseline["annualized_return"]
    assert static["annualized_return"] > baseline["annualized_return"]
    assert static["maximum_drawdown"] < baseline["maximum_drawdown"]
    assert static["sharpe"] > baseline["sharpe"]
