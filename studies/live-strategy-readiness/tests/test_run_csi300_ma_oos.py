import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd


STUDY_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = STUDY_DIR / "run_csi300_ma_oos.py"
SPEC = importlib.util.spec_from_file_location("run_csi300_ma_oos", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_ma_signal_is_risk_on_for_a_rising_frozen_window():
    dates = pd.date_range("2018-01-01", periods=60, freq="B")
    close = pd.Series(np.arange(1.0, 61.0), index=dates)

    assert MODULE.ma_signal(close, dates[-1]) == 1


def test_ma_signal_is_risk_off_for_a_falling_frozen_window():
    dates = pd.date_range("2018-01-01", periods=60, freq="B")
    close = pd.Series(np.arange(60.0, 0.0, -1.0), index=dates)

    assert MODULE.ma_signal(close, dates[-1]) == 0


def test_ma_signal_ignores_prices_after_the_observation_date():
    dates = pd.date_range("2018-01-01", periods=61, freq="B")
    close = pd.Series(np.append(np.arange(1.0, 61.0), -1_000_000.0), index=dates)

    assert MODULE.ma_signal(close, dates[-2]) == 1


def test_fixed_source_cost_keeps_the_declared_one_per_mille_sell_tax():
    model = MODULE.FixedTaxCostModel(fixed_sell_tax=0.001)

    assert model.stamp_tax_rate("stock", "buy", "2025-01-01") == 0.0
    assert model.stamp_tax_rate("stock", "sell", "2025-01-01") == 0.001


def test_preregistered_source_hash_is_unchanged():
    assert MODULE.sha256_file(MODULE.SOURCE_PATH) == (
        "8d67a7ead17d757ee2b2edd59ace74c29fcfcda0536dc859d1ffb95e905886c3"
    )
