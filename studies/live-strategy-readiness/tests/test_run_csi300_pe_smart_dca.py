import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


STUDY_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = STUDY_DIR / "run_csi300_pe_smart_dca.py"
SPEC = importlib.util.spec_from_file_location("run_csi300_pe_smart_dca", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_valuation_state_uses_only_information_at_observation_date():
    dates = pd.bdate_range("2010-01-01", periods=20)
    pe = pd.Series(np.linspace(10.0, 20.0, len(dates)), index=dates)
    observation = dates[-2]

    before = MODULE.valuation_state(pe, observation, window=10)
    pe.loc[dates[-1]] = 1_000_000.0
    after = MODULE.valuation_state(pe, observation, window=10)

    assert after == pytest.approx(before)
    expected = np.log10(pe.loc[:observation].tail(10))
    assert before["center"] == pytest.approx(expected.median())
    assert before["upper"] == pytest.approx(expected.median() + 0.05 * expected.std())
    assert before["lower"] == pytest.approx(expected.median() - 0.25 * expected.std())


@pytest.mark.parametrize(
    ("now", "upper", "lower", "expected_mode", "expected_sign"),
    [
        (1.20, 1.10, 0.90, "sell", -1),
        (0.80, 1.10, 0.90, "buy", 1),
        (1.00, 1.10, 0.90, "normal", 1),
    ],
)
def test_target_weeks_preserves_frozen_signal(now, upper, lower, expected_mode, expected_sign):
    weeks, mode = MODULE.target_weeks(now, upper, lower, normal_weeks=50)

    assert mode == expected_mode
    assert np.sign(weeks) == expected_sign


def test_cash_flow_adjusted_returns_do_not_count_deposits_as_profit():
    equity = pd.DataFrame(
        {
            "trade_date": pd.bdate_range("2024-01-01", periods=3),
            "total_value": [100_000.0, 105_000.0, 105_000.0],
            "external_flow": [0.0, 5_000.0, 0.0],
        }
    )

    returns = MODULE.cash_flow_adjusted_returns(equity, initial_cash=100_000.0)

    assert returns.tolist() == pytest.approx([0.0, 0.0, 0.0])


def test_penultimate_weekly_schedule_handles_holiday_weeks():
    dates = pd.to_datetime(
        [
            "2024-01-02",
            "2024-01-03",
            "2024-01-04",
            "2024-01-05",
            "2024-01-08",
        ]
    )

    schedule = MODULE.penultimate_weekly_dates(dates)

    assert pd.Timestamp("2024-01-04") in schedule
    assert pd.Timestamp("2024-01-08") not in schedule


def test_preregistered_protocol_and_source_hash_are_unchanged():
    protocol = json.loads(
        (STUDY_DIR / "results" / MODULE.CANDIDATE_ID / "protocol.json").read_text(
            encoding="utf-8"
        )
    )

    assert protocol["source"]["source_sha256"] == MODULE.sha256_file(MODULE.SOURCE_PATH)
    assert protocol["post_publication_evaluation"]["parameter_selection_allowed"] is False
    assert protocol["first_read_advancement_gates"]["all_required"] is True


def test_committed_calibration_failure_did_not_inspect_post_publication_results():
    candidate = STUDY_DIR / "results" / MODULE.CANDIDATE_ID
    decision = json.loads(
        (candidate / "version-calibration-decision.json").read_text(encoding="utf-8")
    )
    scorecard = json.loads(
        (candidate / "live-readiness-scorecard.json").read_text(encoding="utf-8")
    )
    oos = pd.read_csv(candidate / "oos.csv").iloc[0]

    assert decision["calibration_passed"] is False
    assert decision["post_publication_performance_calculated"] is False
    assert scorecard["status"] == "R0"
    assert scorecard["parameter_selection_used"] is False
    assert oos["status"] == "not-run"
    assert not bool(oos["post_publication_performance_calculated"])
