import importlib.util
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).resolve().parents[1] / "run_local.py"
SPEC = importlib.util.spec_from_file_location("small_cap_run_local", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_stable_symbol_hash_is_order_independent():
    assert MODULE.stable_symbol_hash(["SH600000", "SZ000001"]) == MODULE.stable_symbol_hash(
        ["SZ000001", "SH600000"]
    )


def test_month_schedule_uses_previous_trading_session():
    class Portal:
        @staticmethod
        def calendar(start, end):
            return pd.DatetimeIndex(
                pd.to_datetime(["2023-12-29", "2024-01-02", "2024-01-03", "2024-02-01"])
            )

    calendar, schedule = MODULE.month_execution_observation_dates(
        Portal(), "2024-01-01", "2024-02-29"
    )

    assert list(calendar) == [
        pd.Timestamp("2024-01-02"),
        pd.Timestamp("2024-01-03"),
        pd.Timestamp("2024-02-01"),
    ]
    assert schedule.to_dict("records") == [
        {
            "execution_date": pd.Timestamp("2024-01-02"),
            "observation_date": pd.Timestamp("2023-12-29"),
        },
        {
            "execution_date": pd.Timestamp("2024-02-01"),
            "observation_date": pd.Timestamp("2024-01-03"),
        },
    ]
