import ast
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SOURCES = [
    ROOT
    / "studies"
    / "joinquant-small-cap-golden-comparison"
    / "joinquant_strategy.py",
    ROOT
    / "studies"
    / "joinquant-value-quality-golden-comparison"
    / "joinquant_strategy.py",
]


def _calls(tree, function_name):
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == function_name
    ]


@pytest.mark.parametrize("source_path", SOURCES, ids=lambda path: path.parent.name)
def test_joinquant_golden_source_is_self_contained_and_point_in_time(source_path):
    text = source_path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(source_path))

    assert "from __future__ import annotations" not in text
    assert "from quant_research" not in text
    assert 'set_option("avoid_future_data", True)' in text
    assert 'set_option("use_real_price", True)' in text
    assert "run_monthly(" in text
    assert "context.previous_date" in text
    assert "current[code]" in text
    assert "current.get(" not in text
    for marker in ("QR_CANDIDATES|", "QR_ORDERS|", "QR_HOLDINGS|"):
        assert marker in text
    assert "QR_ORDER|" not in text

    for function_name in ("get_all_securities", "get_fundamentals"):
        calls = _calls(tree, function_name)
        assert calls
        assert all(any(keyword.arg == "date" for keyword in call.keywords) for call in calls)

    forbidden_direct_builtins = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"sum", "all", "any"}
    }
    assert not forbidden_direct_builtins
    for builtin_name in ("sum", "all", "any"):
        assert f"builtins.{builtin_name}(" in text


def test_value_quality_source_batches_expensive_platform_queries():
    source_path = SOURCES[1]
    text = source_path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(source_path))

    industry_calls = _calls(tree, "get_industry")
    assert industry_calls
    assert all(any(keyword.arg == "date" for keyword in call.keywords) for call in industry_calls)
    assert text.count("for batch in _chunks(codes, 300)") == 2


@pytest.mark.parametrize("source_path", SOURCES, ids=lambda path: path.parent.name)
def test_joinquant_golden_orders_set_star_market_protection_prices(source_path):
    text = source_path.read_text(encoding="utf-8")

    assert "MarketOrderStyle(current[code].low_limit)" in text
    assert "MarketOrderStyle(current[code].high_limit)" in text
