import ast
import importlib.util
from pathlib import Path

import numpy as np


FAMILY = Path(__file__).resolve().parents[1]
STRATEGY = FAMILY / "baseline.py"


def load_strategy():
    spec = importlib.util.spec_from_file_location("lazy_etf_baseline", STRATEGY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_platform_file_is_valid_and_avoids_future_data():
    source = STRATEGY.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "from __future__ import annotations" not in source
    assert 'set_option("avoid_future_data", True)' in source
    assert "context.previous_date" in source
    forbidden = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"sum", "all", "any"}
    }
    assert forbidden == set()


def test_close_only_cci_matches_formula():
    strategy = load_strategy()
    close = np.arange(1.0, 15.0)
    mean = close.mean()
    expected = (close[-1] - mean) / (0.015 * np.mean(np.abs(close - mean)))
    assert strategy.calc_close_cci(close, 14) == expected


def test_moving_average_requires_enough_history():
    strategy = load_strategy()
    assert not strategy.above_ma(np.arange(10.0), 45)
    assert strategy.above_ma(np.arange(1.0, 46.0), 45)
