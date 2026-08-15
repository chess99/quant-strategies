import importlib.util
import sys
from pathlib import Path

import pandas as pd


FAMILY = Path(__file__).resolve().parents[1]
MODULE = FAMILY / "compare_joinquant.py"


def load_module():
    spec = importlib.util.spec_from_file_location("etf_core_rotation_compare", MODULE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_platform_comparison_reports_universe_rank_and_weight_agreement():
    module = load_module()
    local_summary = pd.DataFrame(
        [
            {
                "observation_date": "2024-01-05",
                "selected": "A;B",
                "target_weights": '{"A": 0.5, "B": 0.5}',
            }
        ]
    )
    jq_summary = pd.DataFrame(
        [
            {
                "observation_date": "2024-01-05",
                "selected": "A;C",
                "target_weights": '{"A": 0.5, "C": 0.5}',
            }
        ]
    )
    columns = ["observation_date", "symbol", "rank", "score", "r63", "r126", "r252", "vol60", "adv20"]
    local_members = pd.DataFrame(
        [
            ["2024-01-05", "A", 1, 1.0, 0.3, 0.2, 0.1, 0.2, 100.0],
            ["2024-01-05", "B", 2, 0.5, 0.2, 0.1, 0.0, 0.3, 80.0],
        ],
        columns=columns,
    )
    jq_members = pd.DataFrame(
        [
            ["2024-01-05", "A", 1, 1.0, 0.3, 0.2, 0.1, 0.2, 100.0],
            ["2024-01-05", "C", 2, 0.5, 0.2, 0.1, 0.0, 0.3, 80.0],
        ],
        columns=columns,
    )
    summary, members, aggregate = module.compare_frames(
        local_summary, local_members, jq_summary, jq_members
    )
    assert len(summary) == 1
    assert summary.iloc[0]["universe_jaccard"] == 1 / 3
    assert summary.iloc[0]["selected_jaccard"] == 1 / 3
    assert summary.iloc[0]["target_weight_l1"] == 1.0
    assert len(members) == 1
    assert aggregate["matched_dates"] == 1
