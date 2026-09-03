import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


STUDY_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = STUDY_DIR / "run_white_horse_causal.py"
SPEC = importlib.util.spec_from_file_location("live_readiness_white_horse", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_market_temperature_preserves_previous_state_in_neutral_middle_zone():
    cold_to_neutral = np.concatenate(
        [np.linspace(100.0, 200.0, 160), np.full(60, 120.0)]
    )

    state, diagnostics = MODULE.market_temperature(cold_to_neutral, "cold")

    assert 0.2 <= diagnostics["market_height"] <= 0.9
    assert diagnostics["recent_60d_gain"] <= 0.2
    assert state == "cold"


def test_latest_visible_features_uses_latest_revision_and_signed_yoy_growth():
    fundamentals = pd.DataFrame(
        {
            "symbol": [
                "SH600001",
                "SH600001",
                "SH600001",
                "SH600002",
                "SH600002",
            ],
            "report_date": pd.to_datetime(
                ["2023-03-31", "2023-03-31", "2024-03-31", "2023-03-31", "2024-03-31"]
            ),
            "notice_date": pd.to_datetime(
                ["2023-04-20", "2023-05-01", "2024-04-20", "2023-04-20", "2024-04-20"]
            ),
            "quarter_operating_cash_flow": [1.0, 1.0, 1.0, 1.0, 1.0],
            "quarter_deducted_parent_net_profit": [1.0, 1.0, 1.0, 1.0, 1.0],
            "quarter_net_profit": [90.0, 100.0, 120.0, -100.0, -80.0],
            "quarter_roe": [2.0] * 5,
            "quarter_roa": [1.0] * 5,
        }
    )
    valuation = pd.DataFrame(
        {
            "symbol": ["SH600001", "SH600002"],
            "trade_date": pd.to_datetime(["2024-04-30", "2024-04-30"]),
            "pb": [0.8, 0.9],
        }
    )
    state = pd.DataFrame(
        {
            "symbol": ["SH600001", "SH600002"],
            "trade_date": pd.to_datetime(["2024-04-30", "2024-04-30"]),
            "paused": [False, False],
            "is_st": [False, False],
        }
    )

    result = MODULE.latest_visible_features(
        fundamentals,
        valuation,
        state,
        ["SH600001", "SH600002"],
        pd.Timestamp("2024-04-30"),
    ).set_index("symbol")

    assert result.loc["SH600001", "net_profit_yoy"] == pytest.approx(20.0)
    assert result.loc["SH600002", "net_profit_yoy"] == pytest.approx(20.0)


def test_slice_metrics_respects_end_date():
    equity = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
            "daily_return": [0.0, 0.1, -0.5],
        }
    )

    metrics = MODULE.slice_metrics(
        equity,
        pd.Timestamp("2024-01-02"),
        pd.Timestamp("2024-01-03"),
    )

    assert metrics["total_return"] == pytest.approx(0.1)


def test_select_candidates_applies_frozen_warm_thresholds_and_rank_buffer():
    features = pd.DataFrame(
        {
            "symbol": [f"SH60000{i}" for i in range(8)],
            "pb": [0.5] * 8,
            "quarter_operating_cash_flow": [20.0] * 8,
            "quarter_deducted_parent_net_profit": [10.0] * 8,
            "quarter_roe": [3.0] * 8,
            "quarter_roa": np.arange(1.0, 9.0),
            "net_profit_yoy": [10.0] * 8,
        }
    )

    selected = MODULE.select_candidates(features, "warm", buffer_count=6)

    assert len(selected) == 6
    assert selected.iloc[0]["symbol"] == "SH600007"
    assert selected.iloc[-1]["symbol"] == "SH600002"


def test_committed_white_horse_outputs_preserve_failed_or_passed_first_causal_run():
    candidate = STUDY_DIR / "results" / "white-horse-offense-defense"
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
    scorecard = json.loads(
        (candidate / "live-readiness-scorecard.json").read_text(encoding="utf-8")
    )
    comparison = pd.read_csv(candidate / "original-vs-causal.csv")
    assert scorecard["candidate_id"] == "white-horse-offense-defense"
    assert scorecard["source_vintage_grade"] == "C"
    assert scorecard["strict_natural_oos"] is False
    assert scorecard["first_causal_run_preserved"] is True
    assert "published-public-backtest" in set(comparison["scenario"])
    assert "local-causal-baseline-cost" in set(comparison["scenario"])


def test_white_horse_deep_protocol_freezes_trials_before_results():
    protocol = json.loads(
        (
            STUDY_DIR
            / "results"
            / "white-horse-offense-defense"
            / "deep-protocol.json"
        ).read_text(encoding="utf-8")
    )

    assert protocol["status"] == "preregistered-before-deep-results"
    assert protocol["parameter_neighborhood"]["trial_count"] == 27
    assert protocol["parameter_neighborhood"]["dimensions"]["holding_count"] == [
        4,
        5,
        6,
    ]
    assert protocol["promotion_gates"]["maximum_level"].startswith("R2")
