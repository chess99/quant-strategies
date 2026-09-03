import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd


STUDY_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = STUDY_DIR / "run_white_horse_deep_research.py"
SPEC = importlib.util.spec_from_file_location("white_horse_deep_research", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _features():
    return pd.DataFrame(
        {
            "symbol": ["SH600001", "SH600002"],
            "pb": [0.95, 1.05],
            "quarter_operating_cash_flow": [12.0, 12.0],
            "quarter_deducted_parent_net_profit": [10.0, 10.0],
            "quarter_roe": [2.1, 2.1],
            "quarter_roa": [3.0, 4.0],
            "net_profit_yoy": [10.0, 10.0],
        }
    )


def test_parameter_neighborhood_relaxes_valuation_without_selecting_a_winner():
    baseline = MODULE.select_candidates(_features(), "warm", valuation_scale=1.0)
    relaxed = MODULE.select_candidates(_features(), "warm", valuation_scale=1.1)

    assert baseline["symbol"].tolist() == ["SH600001"]
    assert relaxed["symbol"].tolist() == ["SH600002", "SH600001"]


def test_execution_map_uses_frozen_observation_with_delayed_execution():
    calendar = pd.bdate_range("2024-01-02", periods=8)
    scheduled = calendar[1]
    signals = {
        scheduled: {
            "scheduled_date": scheduled,
            "observation_date": calendar[0],
            "temperature": "warm",
            "features": _features(),
        }
    }

    execution = MODULE.build_execution_map(calendar, signals, delay_sessions=3)

    item = execution[calendar[4]]
    assert item["observation_date"] == calendar[0]
    assert item["execution_delay_sessions"] == 3


def test_parameter_grid_matches_preregistered_27_trials():
    assert len(MODULE.PARAMETER_VALUES) == 27
    assert (5, 1.0, 1.0) in MODULE.PARAMETER_VALUES


def test_committed_deep_outputs_preserve_failed_absolute_capacity_gate():
    candidate = STUDY_DIR / "results" / "white-horse-offense-defense"
    scorecard = json.loads(
        (candidate / "live-readiness-scorecard.json").read_text(encoding="utf-8")
    )
    capacity = pd.read_csv(candidate / "capacity.csv")

    assert scorecard["experiment_count"] == 63
    assert scorecard["status"] == "R1"
    assert scorecard["gates"]["primary_capacity_gate"] is False
    assert scorecard["primary_capital_minimum_exposure"] < 0.9
    assert scorecard["primary_capital_minimum_exposure_retention"] > 0.9
    assert "exposure_retention_vs_frozen" in capacity.columns
