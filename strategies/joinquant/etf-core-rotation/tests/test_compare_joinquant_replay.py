import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest


FAMILY = Path(__file__).resolve().parents[1]
MODULE = FAMILY / "compare_joinquant_replay.py"


def load_module():
    spec = importlib.util.spec_from_file_location("etf_core_replay_compare", MODULE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_full_replay_comparison_normalizes_symbols_and_aligns_start_boundary():
    module = load_module()
    local_decisions = pd.DataFrame(
        [
            {
                "execution_date": "2024-01-08",
                "observation_date": "2024-01-05",
                "liquid_count": 10,
                "selected": "SHA;SZ000001",
                "target_weights": '{"SHA": 0.5, "SZ000001": 0.5}',
            }
        ]
    )
    replay_decisions = pd.DataFrame(
        [
            {
                "execution_date": "2024-01-02",
                "observation_date": "2023-12-29",
                "universe_count": 9,
                "selected": "X",
                "target_weights": '{"X": 1.0}',
            },
            {
                "execution_date": "2024-01-08",
                "observation_date": "2024-01-05",
                "universe_count": 11,
                "selected": "SHA;000001.XSHE",
                "target_weights": '{"SHA": 0.4, "000001.XSHE": 0.6}',
            },
        ]
    )
    local_equity = pd.DataFrame(
        [
            {"trade_date": "2024-01-08", "total_value": 100.0, "daily_return": 0.0},
            {"trade_date": "2024-01-09", "total_value": 101.0, "daily_return": 0.01},
        ]
    )
    replay_equity = pd.DataFrame(
        [
            {"date": "2024-01-08", "total_value": 200.0, "daily_return": 0.0},
            {"date": "2024-01-09", "total_value": 204.0, "daily_return": 0.02},
        ]
    )
    decisions, path, aggregate = module.compare_frames(
        local_decisions, replay_decisions, local_equity, replay_equity
    )
    assert aggregate["matched_observation_dates"] == 1
    assert aggregate["extra_joinquant_start_boundary_decisions"] == 1
    assert decisions.iloc[0]["selected_exact_match"]
    assert decisions.iloc[0]["target_weight_l1"] == pytest.approx(0.2)
    assert path.iloc[-1]["normalized_value_local"] == 1.01
    assert path.iloc[-1]["normalized_value_jq"] == 1.02
