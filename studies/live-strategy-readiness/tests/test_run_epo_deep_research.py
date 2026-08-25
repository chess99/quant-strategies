import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


STUDY_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = STUDY_DIR / "run_epo_deep_research.py"
SPEC = importlib.util.spec_from_file_location("live_readiness_epo_deep", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_shifted_execution_plan_keeps_signal_observation_before_scheduled_trade():
    calendar = pd.date_range("2024-01-02", "2024-04-10", freq="B")

    plan = MODULE.build_execution_plan(calendar, delay_sessions=3)

    assert len(plan) == 3
    for item in plan:
        assert item["observation_date"] < item["scheduled_date"]
        assert item["scheduled_date"] < item["execution_date"]
        assert calendar.get_loc(item["execution_date"]) - calendar.get_loc(
            item["scheduled_date"]
        ) == 3


def test_moving_block_bootstrap_is_deterministic_and_preserves_sample_length():
    returns = pd.Series(np.linspace(-0.02, 0.03, 80))

    first = MODULE.moving_block_bootstrap(
        returns, block_size=10, samples=50, seed=20260825
    )
    second = MODULE.moving_block_bootstrap(
        returns, block_size=10, samples=50, seed=20260825
    )

    pd.testing.assert_frame_equal(first, second)
    assert len(first) == 50
    assert set(first) == {"annualized_return", "maximum_drawdown"}


def test_pbo_diagnostic_returns_probability_and_all_split_count():
    index = pd.date_range("2020-01-02", periods=160, freq="B")
    returns = pd.DataFrame(
        {
            "a": np.sin(np.arange(160) / 10.0) / 100.0,
            "b": np.cos(np.arange(160) / 11.0) / 100.0,
            "c": np.linspace(-0.005, 0.008, 160),
        },
        index=index,
    )

    result = MODULE.probability_of_backtest_overfitting(returns, blocks=4)

    assert 0.0 <= result["pbo"] <= 1.0
    assert result["split_count"] == 6
    assert result["strategy_count"] == 3


def test_committed_deep_research_delivers_required_candidate_artifacts():
    candidate = STUDY_DIR / "results" / "multi-asset-etf-momentum-epo"
    required = {
        "source-audit.md",
        "protocol.json",
        "original-vs-causal.csv",
        "robustness.csv",
        "oos.csv",
        "capacity.csv",
        "attribution.csv",
        "live-readiness-scorecard.json",
        "conclusion.md",
    }
    assert required.issubset({path.name for path in candidate.iterdir()})

    robustness = pd.read_csv(candidate / "robustness.csv")
    capacity = pd.read_csv(candidate / "capacity.csv")
    attribution = pd.read_csv(candidate / "attribution.csv")
    scorecard = json.loads(
        (candidate / "live-readiness-scorecard.json").read_text(encoding="utf-8")
    )

    assert len(robustness[robustness["experiment"] == "parameter-neighborhood"]) == 27
    assert set(
        robustness.loc[robustness["experiment"] == "execution-delay", "delay_sessions"]
    ) == {0, 1, 2, 3, 5}
    assert set(capacity["capital_rmb"]) == {200000, 1000000, 2000000, 10000000}
    assert set(capacity["adv_participation"]) == {0.005, 0.01, 0.05}
    assert len(capacity) == 12
    assert {"asset-contribution", "factor-beta"}.issubset(set(attribution["analysis_type"]))
    assert scorecard["candidate_id"] == "multi-asset-etf-momentum-epo"
    assert scorecard["experiment_count"] >= 50
    assert scorecard["status"] in {"R1", "R2", "R3"}
