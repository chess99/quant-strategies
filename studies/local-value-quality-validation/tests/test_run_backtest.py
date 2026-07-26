import importlib.util
import sys
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).resolve().parents[1] / "run_backtest.py"
SPEC = importlib.util.spec_from_file_location("local_value_quality_study", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_monthly_first_dates_select_exactly_one_session_per_month():
    calendar = pd.DatetimeIndex(pd.to_datetime(["2024-01-02", "2024-01-03", "2024-02-01"]))

    dates = MODULE.monthly_first_dates(calendar)

    assert dates == {pd.Timestamp("2024-01-02"), pd.Timestamp("2024-02-01")}


def test_value_quality_features_exclude_financials_announced_later():
    fundamentals = pd.DataFrame(
        {
            "symbol": ["AAA", "AAA", "AAA", "AAA", "AAA"],
            "report_date": pd.to_datetime(
                ["2022-12-31", "2023-03-31", "2023-12-31", "2024-03-31", "2024-06-30"]
            ),
            "notice_date": pd.to_datetime(
                ["2023-03-31", "2023-04-30", "2024-03-31", "2024-04-30", "2024-08-31"]
            ),
            "is_annual": [True, False, True, False, False],
            "annual_roe": [12.0, None, 15.0, None, None],
            "revenue": [80.0, 20.0, 100.0, 30.0, 9999.0],
            "parent_net_profit": [8.0, 2.0, 10.0, 4.0, 9999.0],
        }
    )
    valuation = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2024-05-10"]),
            "symbol": ["AAA"],
            "market_cap": [1_000_000_000.0],
            "pe_ttm": [10.0],
            "pb": [1.0],
        }
    ).set_index("trade_date")

    features = MODULE.value_quality_features(
        fundamentals,
        valuation,
        ["AAA"],
        "2024-05-10",
    )

    assert features.loc[0, "report_date"] == pd.Timestamp("2024-03-31")
    assert features.loc[0, "notice_date"] <= pd.Timestamp("2024-05-10")
    assert features.loc[0, "revenue_growth"] == 0.5
