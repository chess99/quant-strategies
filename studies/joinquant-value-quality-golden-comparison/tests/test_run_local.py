import importlib.util
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).resolve().parents[1] / "run_local.py"
SPEC = importlib.util.spec_from_file_location("value_quality_local", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_value_quality_ranking_rewards_lower_value_ratios_and_higher_quality():
    rows = []
    for number in range(10):
        rows.append(
            {
                "symbol": f"SH600{number:03d}",
                "industry_code": "110000",
                "pe_ttm": 5.0 + number,
                "pb": 0.5 + number / 10,
                "ps": 1.0 + number / 10,
                "roe": 30.0 - number,
                "roa": 20.0 - number,
                "gross_margin": 60.0 - number,
                "net_margin": 30.0 - number,
                "total_assets": 100.0,
                "total_liabilities": 20.0 + number,
                "operating_cash_flow": 10.0,
            }
        )

    ranked = MODULE.score_value_quality(pd.DataFrame(rows))

    assert ranked.iloc[0]["symbol"] == "SH600000"
    assert ranked.iloc[-1]["symbol"] == "SH600009"


def test_industry_cap_is_applied_to_actual_targets():
    ranked = pd.DataFrame(
        {
            "symbol": [f"SH600{number:03d}" for number in range(8)],
            "industry_code": ["110000"] * 5 + ["220000"] * 3,
            "score": list(reversed(range(8))),
        }
    )

    selected = MODULE.select_with_industry_cap(ranked, count=4, maximum_per_industry=2)

    assert len(selected) == 4
    assert selected["industry_code"].value_counts().max() == 2
