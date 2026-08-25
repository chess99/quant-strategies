import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd


STUDY_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = STUDY_DIR / "run_csi300_switch_oos.py"
SPEC = importlib.util.spec_from_file_location("run_csi300_switch_oos", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_sell_signal_matches_frozen_path_rule():
    values = np.concatenate(
        [
            np.array([1.0]),
            np.linspace(2.0, 10.0, 24),
            np.linspace(9.0, 3.0, 7),
        ]
    )
    dates = pd.date_range("2021-01-01", periods=32, freq="B")

    assert MODULE.switch_signal(pd.Series(values, index=dates), dates[-1]) == 0


def test_buy_signal_matches_frozen_path_rule():
    values = np.concatenate(
        [np.array([5.0, 5.0, 10.0]), np.ones(9), np.full(10, 2.0), np.full(10, 3.0)]
    )
    dates = pd.date_range("2021-01-01", periods=32, freq="B")

    assert MODULE.switch_signal(pd.Series(values, index=dates), dates[-1]) == 1


def test_signal_uses_no_observation_after_requested_date():
    values = np.concatenate(
        [np.array([5.0, 5.0, 10.0]), np.ones(9), np.full(10, 2.0), np.full(10, 3.0)]
    )
    dates = pd.date_range("2021-01-01", periods=33, freq="B")
    close = pd.Series(np.append(values, 1_000_000.0), index=dates)

    assert MODULE.switch_signal(close, dates[-2]) == 1


def test_preregistered_source_hash_is_unchanged():
    assert MODULE.sha256_file(MODULE.SOURCE_PATH) == (
        "4f80ec6b4e207dd9cb53baabb5debfd16671229f8b3b92867781e29d79dccd51"
    )
