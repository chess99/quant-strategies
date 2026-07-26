import importlib.util
import sys
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).resolve().parents[1] / "run_acceptance.py"
SPEC = importlib.util.spec_from_file_location("oneil_acceptance", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_assign_point_in_time_industry_never_uses_future_change():
    selections = pd.DataFrame(
        {
            "symbol": ["SH600000", "SH600000"],
            "observation_date": pd.to_datetime(["2015-01-31", "2020-01-31"]),
        }
    )
    history = pd.DataFrame(
        {
            "symbol": ["SH600000", "SH600000"],
            "change_date": pd.to_datetime(["2010-01-01", "2018-01-01"]),
            "classification_standard_code": ["008021", "008021"],
            "industry_major": ["旧行业", "新行业"],
        }
    )

    result = MODULE.assign_point_in_time_industry(selections, history)

    assert result["industry"].tolist() == ["旧行业", "新行业"]


def test_cashflow_attribution_includes_costs_and_final_position_value():
    trades = pd.DataFrame(
        {
            "symbol": ["AAA", "AAA", "BBB"],
            "side": ["buy", "sell", "buy"],
            "gross_value": [100.0, 120.0, 50.0],
            "commission": [1.0, 1.0, 1.0],
            "tax": [0.0, 2.0, 0.0],
        }
    )
    final_holdings = pd.DataFrame({"symbol": ["BBB"], "market_value": [70.0]})

    result = MODULE.cashflow_attribution(trades, final_holdings).set_index("symbol")

    assert result.loc["AAA", "net_contribution"] == 16.0
    assert result.loc["BBB", "net_contribution"] == 19.0
