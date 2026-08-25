import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest


STUDY_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = STUDY_DIR / "run_ebit_ev_calibration.py"
SPEC = importlib.util.spec_from_file_location("run_ebit_ev_calibration", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_rank_candidates_uses_positive_ebit_and_enterprise_value():
    frame = pd.DataFrame(
        {
            "symbol": ["SH600001", "SH600002", "SH600003", "SH600004"],
            "market_cap": [100.0, 100.0, 100.0, 100.0],
            "interest_bearing_debt": [20.0, 20.0, 20.0, 20.0],
            "cash": [10.0, 10.0, 130.0, 10.0],
            "ebit": [22.0, 11.0, 10.0, -1.0],
        }
    )

    ranked = MODULE.rank_candidates(frame)

    assert ranked["symbol"].tolist() == ["SH600001", "SH600002"]
    assert ranked["ebit_ev"].tolist() == pytest.approx([0.2, 0.1])


def test_rank_candidates_has_stable_symbol_tie_break():
    frame = pd.DataFrame(
        {
            "symbol": ["SZ000002", "SH600001"],
            "market_cap": [100.0, 100.0],
            "interest_bearing_debt": [0.0, 0.0],
            "cash": [0.0, 0.0],
            "ebit": [10.0, 10.0],
        }
    )

    ranked = MODULE.rank_candidates(frame)

    assert ranked["symbol"].tolist() == ["SH600001", "SZ000002"]


def test_month_schedule_uses_previous_trading_day_observation():
    calendar = pd.to_datetime(
        ["2019-12-30", "2019-12-31", "2020-01-02", "2020-01-03", "2020-02-03"]
    )

    run_calendar, schedule = MODULE.month_execution_observation_dates(
        calendar, "2020-01-02", "2020-02-03"
    )

    assert run_calendar.tolist() == [pd.Timestamp("2020-01-02"), pd.Timestamp("2020-01-03"), pd.Timestamp("2020-02-03")]
    assert schedule.to_dict("records") == [
        {
            "execution_date": pd.Timestamp("2020-01-02"),
            "observation_date": pd.Timestamp("2019-12-31"),
        },
        {
            "execution_date": pd.Timestamp("2020-02-03"),
            "observation_date": pd.Timestamp("2020-01-03"),
        },
    ]


def test_calibration_decision_requires_metrics_and_coverage():
    passing = {
        "annualized_return": MODULE.PUBLIC_METRICS["annualized_return"],
        "maximum_drawdown": MODULE.PUBLIC_METRICS["maximum_drawdown"],
        "sharpe": MODULE.PUBLIC_METRICS["sharpe"],
        "median_holdings": 50,
        "valid_month_ratio": 1.0,
    }

    assert MODULE.calibration_decision(passing)["calibration_passed"] is True
    passing["median_holdings"] = 39
    assert MODULE.calibration_decision(passing)["calibration_passed"] is False


def test_preregistered_protocol_and_source_hash_are_unchanged():
    protocol = json.loads(
        (STUDY_DIR / "results" / MODULE.CANDIDATE_ID / "protocol.json").read_text(
            encoding="utf-8"
        )
    )

    assert protocol["source"]["source_sha256"] == MODULE.sha256_file(MODULE.SOURCE_PATH)
    assert protocol["calibration"]["parameter_selection_allowed"] is False
    assert protocol["post_publication_evaluation"]["parameter_selection_allowed"] is False
