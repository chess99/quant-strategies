import importlib.util
import sys
from pathlib import Path

import numpy as np


MODULE_PATH = Path(__file__).resolve().parents[1] / "run_market_ablation.py"
SPEC = importlib.util.spec_from_file_location("oneil_market_ablation", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_market_regime_requires_both_breadth_and_index_majority():
    assert MODULE.market_risk_on(0.60, [True, True, True, False, False])
    assert not MODULE.market_risk_on(0.49, [True, True, True, True, True])
    assert not MODULE.market_risk_on(0.60, [True, True, False, False, False])


def test_market_regime_ignores_missing_indices_but_not_missing_breadth():
    assert MODULE.market_risk_on(0.60, [True, np.nan])
    assert not MODULE.market_risk_on(np.nan, [True, True])
    assert not MODULE.market_risk_on(0.60, [np.nan, np.nan])
