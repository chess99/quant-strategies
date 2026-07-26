import ast
import importlib.util
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "variants" / "quality_growth_momentum.py"


def load_strategy():
    previous = sys.modules.get("jqdata")
    sys.modules["jqdata"] = types.ModuleType("jqdata")
    try:
        spec = importlib.util.spec_from_file_location("quality_growth_momentum", SOURCE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if previous is None:
            del sys.modules["jqdata"]
        else:
            sys.modules["jqdata"] = previous


def test_source_is_self_contained_legacy_compatible_and_point_in_time():
    source = SOURCE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert "from __future__ import annotations" not in source
    assert "from jqdata import *" in source
    assert 'set_option("avoid_future_data", True)' in source
    assert 'get_all_securities(types=["stock"], date=observation_date)' in source
    assert "watch_date=observation_date" in source
    assert "end_date=observation_date" in source
    assert "current_data.get(" not in source
    unqualified = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"sum", "all", "any"}
    ]
    assert unqualified == []


def test_quarter_growth_requires_exact_prior_year_and_positive_base():
    strategy = load_strategy()
    frame = pd.DataFrame(
        {
            "statDate": pd.to_datetime(["2023-03-31", "2024-03-31"]),
            "np_parent_company_owners": [100.0, 150.0],
            "total_operating_revenue": [200.0, 260.0],
        }
    )
    negative = frame.copy()
    negative.loc[0, "np_parent_company_owners"] = -100.0

    result = strategy._quarter_growth(frame)
    invalid = strategy._quarter_growth(negative)

    assert result["profit_growth"] == 0.5
    assert result["revenue_growth"] == pytest.approx(0.3)
    assert np.isnan(invalid["profit_growth"])


def test_selection_is_equal_weight_quality_growth_and_momentum_ranking():
    strategy = load_strategy()
    features = pd.DataFrame(
        {
            "code": ["A", "B", "C", "D", "ILLIQUID"],
            "profit_growth": [3.0, 2.0, 1.0, 0.5, 9.0],
            "revenue_growth": [3.0, 2.0, 1.0, 0.5, 9.0],
            "momentum_12_1": [1.0, 3.0, 2.0, 0.5, 9.0],
            "annual_roe": [1.0, 3.0, 2.0, 0.5, 9.0],
            "amount_20": [100.0, 100.0, 100.0, 100.0, 1.0],
        }
    )

    selected = strategy.select_from_features(features)

    assert selected.iloc[0]["code"] == "B"
    assert "ILLIQUID" not in set(selected["code"])
