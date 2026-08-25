import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


STUDY_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = STUDY_DIR / "run_gac_zscore_mean_reversion.py"
SPEC = importlib.util.spec_from_file_location("live_readiness_gac_zscore", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_zscore_matches_60_residuals_after_20_day_mean():
    x = np.arange(100, dtype=float)
    close = pd.Series(10.0 + x * 0.05 + np.sin(x / 4.0))
    expected_sub = close.rolling(20).mean().rsub(close).dropna().tail(60)
    expected = (expected_sub.iloc[-1] - expected_sub.mean()) / expected_sub.std(ddof=1)

    actual = MODULE.zscore_series(close).iloc[-1]

    assert actual == pytest.approx(expected)


def test_hysteresis_uses_frozen_asymmetric_thresholds():
    scores = pd.Series([-2.1, -1.0, 0.9, 1.1, -1.9])

    positions = MODULE.hysteresis_positions(scores)

    assert positions.tolist() == [1, 1, 1, 0, 0]


def test_protocol_keeps_oos_untuned_and_single_stock_explicit():
    protocol = MODULE.load_protocol()

    assert protocol["source"]["oos_integrity_grade"] == "B"
    assert protocol["frozen_parameters"]["symbol"] == "SH601238"
    assert protocol["frozen_parameters"]["buy_threshold"] == -2.0
    assert protocol["post_publication_window_if_unlocked"][
        "parameter_selection_used_window"
    ] is False
