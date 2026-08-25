import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


STUDY_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = STUDY_DIR / "run_stock_bond_volatility_oos.py"
SPEC = importlib.util.spec_from_file_location(
    "run_stock_bond_volatility_oos", MODULE_PATH
)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_static_prior_weights_preserve_frozen_preferences():
    dates = pd.date_range("2020-01-01", periods=60, freq="B")
    close = pd.DataFrame(
        {
            symbol: np.exp(np.arange(60) * 0.001)
            for symbol in MODULE.calibration.LOCAL_SYMBOLS
        },
        index=dates,
    )

    weights = MODULE.static_weights(close, dates[-1], method="static-prior")

    expected = MODULE.calibration.PRIOR_WEIGHTS_LOCAL
    expected = expected / expected.sum()
    assert weights == pytest.approx(expected.to_dict())


def test_static_weights_exclude_unavailable_products():
    dates = pd.date_range("2020-01-01", periods=60, freq="B")
    close = pd.DataFrame(
        1.0,
        index=dates,
        columns=MODULE.calibration.LOCAL_SYMBOLS,
    )
    close.loc[:, "SH512010"] = np.nan

    weights = MODULE.static_weights(close, dates[-1], method="equal-weight")

    assert "SH512010" not in weights
    assert sum(weights.values()) == pytest.approx(1.0)


def test_oos_protocol_is_bound_to_passed_b_grade_calibration():
    decision = json.loads(MODULE.VERSION_DECISION_PATH.read_text(encoding="utf-8"))
    protocol = json.loads(
        (MODULE.CANDIDATE_DIR / "oos-protocol.json").read_text(encoding="utf-8")
    )

    assert decision["calibration_status"] == "passed"
    assert decision["source_vintage_after"] == "B"
    assert protocol["source_vintage"]["grade"] == "B"
    assert protocol["post_publication_replay"]["authorized"] is True
    assert protocol["post_publication_replay"]["parameter_selection_used_oos"] is False
    assert protocol["version_calibration"]["decision_sha256"] == MODULE.sha256_file(
        MODULE.VERSION_DECISION_PATH
    )


def test_frozen_source_and_scenario_count_are_unchanged():
    assert MODULE.sha256_file(MODULE.SOURCE_PATH) == (
        "163e8e3025b9e97bfbf1ea820c59722333c9d9839b256f48ea6f59815e82087c"
    )
    assert len(MODULE.SCENARIOS) == 5
