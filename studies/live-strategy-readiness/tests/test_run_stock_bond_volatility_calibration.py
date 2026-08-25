import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


STUDY_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = STUDY_DIR / "run_stock_bond_volatility_calibration.py"
SPEC = importlib.util.spec_from_file_location(
    "run_stock_bond_volatility_calibration", MODULE_PATH
)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_annualized_volatility_matches_clipped_log_return_definition():
    close = pd.Series(np.exp(np.arange(40) * 0.002 + np.sin(np.arange(40)) * 0.01))

    value = MODULE.annualized_volatility(close)

    returns = np.log(close / close.shift(1)).dropna()
    mean = returns.mean()
    standard_deviation = returns.std(ddof=1)
    expected = (
        returns.clip(
            mean - 3.0 * standard_deviation,
            mean + 3.0 * standard_deviation,
        ).std(ddof=1)
        * np.sqrt(250.0)
        * 100.0
    )
    assert value == pytest.approx(expected)


def test_target_weights_exclude_an_unlisted_asset_and_normalize():
    dates = pd.date_range("2014-01-01", periods=60, freq="B")
    close = pd.DataFrame(
        {
            symbol: np.exp(np.arange(60) * (0.001 + index * 0.0001))
            for index, symbol in enumerate(MODULE.LOCAL_SYMBOLS)
        },
        index=dates,
    )
    close.loc[:, "SH512010"] = np.nan

    weights, diagnostics = MODULE.target_weights(close, dates[-1])

    assert "SH512010" not in weights
    assert set(weights) == set(MODULE.LOCAL_SYMBOLS) - {"SH512010"}
    assert sum(weights.values()) == pytest.approx(1.0)
    assert diagnostics["observation_date"] == dates[-1].strftime("%Y-%m-%d")


def test_target_weights_ignore_prices_after_observation_date():
    dates = pd.date_range("2014-01-01", periods=61, freq="B")
    close = pd.DataFrame(
        {
            symbol: np.exp(np.arange(61) * (0.001 + index * 0.0001))
            for index, symbol in enumerate(MODULE.LOCAL_SYMBOLS)
        },
        index=dates,
    )
    observation = dates[-2]
    before, _ = MODULE.target_weights(close, observation)
    close.loc[dates[-1], "SH513100"] *= 1_000.0

    after, _ = MODULE.target_weights(close, observation)

    assert after == pytest.approx(before)


def test_preregistered_source_hash_is_unchanged():
    assert MODULE.sha256_file(MODULE.SOURCE_PATH) == (
        "163e8e3025b9e97bfbf1ea820c59722333c9d9839b256f48ea6f59815e82087c"
    )
