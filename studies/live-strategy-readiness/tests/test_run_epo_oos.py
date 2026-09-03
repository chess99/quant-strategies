import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


STUDY_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = STUDY_DIR / "run_epo_oos.py"
SPEC = importlib.util.spec_from_file_location("live_readiness_run_epo_oos", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_momentum_score_matches_frozen_log_trend_times_r_squared():
    close = pd.Series(np.exp(np.arange(34) * 0.002))

    score = MODULE.momentum_score(close, 34)

    assert score == pytest.approx(np.exp(0.002 * 250.0) - 1.0)


def test_epo_weights_are_long_only_and_normalized():
    returns = pd.DataFrame(
        {
            "A": [0.01, -0.01, 0.02, 0.01, -0.005],
            "B": [0.005, 0.002, -0.003, 0.004, 0.006],
            "C": [-0.01, 0.015, 0.004, -0.002, 0.01],
        }
    )

    weights = MODULE.epo_weights(returns, w=0.2)

    assert list(weights.index) == ["A", "B", "C"]
    assert weights.sum() == pytest.approx(1.0)
    assert (weights >= 0.0).all()


def test_target_weights_use_only_observation_date_and_keep_frozen_top_three():
    dates = pd.date_range("2023-01-02", periods=80, freq="B")
    close = pd.DataFrame(
        {
            "A": np.exp(np.arange(80) * 0.004),
            "B": np.exp(np.arange(80) * 0.003),
            "C": np.exp(np.arange(80) * 0.002),
            "D": np.exp(np.arange(80) * -0.001),
        },
        index=dates,
    )
    # 观察日之后 D 暴涨，不能进入当次信号。
    observation_date = dates[-2]
    close.loc[dates[-1], "D"] *= 100.0

    weights, diagnostics = MODULE.build_target_weights(
        close,
        observation_date,
        method="equal-top3",
        momentum_days=34,
        stock_num=3,
        epo_w=0.2,
        price_history_days=1200,
    )

    assert set(weights) == {"A", "B", "C"}
    assert all(value == pytest.approx(1.0 / 3.0) for value in weights.values())
    assert diagnostics["observation_date"] == observation_date.strftime("%Y-%m-%d")


def test_committed_epo_oos_artifacts_bind_source_engine_and_data_hashes():
    candidate_dir = STUDY_DIR / "results" / "multi-asset-etf-momentum-epo"
    manifest_path = candidate_dir / "oos-run-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["candidate_id"] == "multi-asset-etf-momentum-epo"
    assert manifest["period"] == {"start": "2024-03-25", "end": "2026-07-24"}
    assert manifest["source_sha256"] == (
        "438cb254e50a3056eb125b67b17b051fea7ef78bd7f6a1f079349730feb331ba"
    )
    assert manifest["engine_sha256"] == MODULE.sha256_file(MODULE_PATH)
    assert manifest["parameter_selection_used_oos"] is False
    assert manifest["scenario_count"] == 5
    assert manifest["scenarios"][0]["execution_policy"] == "source-sequential"
    assert all(
        item["execution_policy"] == "sell-first"
        for item in manifest["scenarios"][1:]
    )
    assert set(manifest["data_manifests"]) == {"etf_daily", "etf_master"}
    for item in manifest["data_manifests"].values():
        assert Path(item["path"]).is_file()
        assert MODULE.sha256_file(Path(item["path"])) == item["sha256"]

    oos = pd.read_csv(candidate_dir / "oos.csv")
    comparison = pd.read_csv(candidate_dir / "original-vs-causal.csv")
    assert set(oos["scenario"]) == {
        "frozen-original-cost",
        "causal-baseline-cost",
        "causal-double-cost",
        "equal-top3-baseline-cost",
        "equal-pool-baseline-cost",
    }
    assert len(comparison) == 6

    by_scenario = oos.set_index("scenario")
    baseline = by_scenario.loc["causal-baseline-cost"]
    double = by_scenario.loc["causal-double-cost"]
    equal_top3 = by_scenario.loc["equal-top3-baseline-cost"]
    assert baseline["total_return"] > 0.0
    assert baseline["sharpe"] >= 0.5
    assert baseline["maximum_drawdown"] <= 0.35
    assert baseline["sharpe"] > equal_top3["sharpe"]
    assert double["total_return"] > 0.0
