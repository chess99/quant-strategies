import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd


MODULE_PATH = Path(__file__).resolve().parents[1] / "analyze_validation.py"
SPEC = importlib.util.spec_from_file_location("oneil_validation_audit", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_deflated_sharpe_probability_increases_for_stronger_returns():
    weak = pd.Series(np.tile([0.001, -0.001], 500))
    strong = pd.Series(np.tile([0.003, -0.001], 500))

    weak_result = MODULE.deflated_sharpe(weak, trials=30)
    strong_result = MODULE.deflated_sharpe(strong, trials=30)

    assert 0.0 <= weak_result["probability"] <= 1.0
    assert strong_result["probability"] > weak_result["probability"]


def test_rolling_validation_years_are_non_overlapping_and_follow_five_year_anchor():
    windows = MODULE.rolling_windows(2010, 2026)
    validation_years = [year for row in windows for year in row["validation_years"]]

    assert windows[0]["training_years"] == [2010, 2011, 2012, 2013, 2014]
    assert windows[0]["validation_years"] == [2015, 2016]
    assert len(validation_years) == len(set(validation_years))
    assert validation_years[-1] == 2026
