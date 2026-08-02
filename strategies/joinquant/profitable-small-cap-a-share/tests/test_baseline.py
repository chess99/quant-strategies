import ast
import importlib.util
from pathlib import Path


FAMILY = Path(__file__).resolve().parents[1]
STRATEGY = FAMILY / "baseline.py"
PUBLISHED_CORE = FAMILY / "variants" / "published_core.py"


def load_strategy():
    spec = importlib.util.spec_from_file_location("profitable_small_cap", STRATEGY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_platform_file_is_valid_and_old_runtime_compatible():
    source = STRATEGY.read_text(encoding="utf-8")
    ast.parse(source)
    assert "from __future__ import annotations" not in source
    assert "from jqdata import *" in source


def test_point_in_time_queries_are_explicit():
    tree = ast.parse(STRATEGY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id == "get_fundamentals":
            assert any(keyword.arg == "date" for keyword in node.keywords)
        if node.func.id == "get_all_securities":
            assert any(keyword.arg == "date" for keyword in node.keywords)


def test_stock_costs_and_lazy_current_data_are_used():
    source = STRATEGY.read_text(encoding="utf-8")
    assert 'type="stock"' in source
    assert "current_data[code]" in source
    assert ".get(code)" not in source


def test_jq_wildcard_does_not_call_shadowed_builtins():
    tree = ast.parse(STRATEGY.read_text(encoding="utf-8"))
    forbidden = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in {"sum", "all", "any"}:
                forbidden.append((node.func.id, node.lineno))
    assert forbidden == []


def test_rank_candidates_respects_industry_cap_and_priority():
    module = load_strategy()
    rows = [
        {"code": "A", "industry": "I1", "score": 1},
        {"code": "B", "industry": "I1", "score": 2},
        {"code": "C", "industry": "I1", "score": 3},
        {"code": "D", "industry": "I2", "score": 4},
        {"code": "E", "industry": "I3", "score": 5},
    ]
    assert module.rank_candidates(rows, 4, 2) == ["A", "B", "D", "E"]


def test_practical_defaults_are_diversified_and_liquid():
    module = load_strategy()
    assert module.STOCK_COUNT == 20
    assert module.MINIMUM_LISTING_DAYS >= 365
    assert module.MINIMUM_AVERAGE_MONEY >= 10_000_000
    assert module.MAXIMUM_INDUSTRY_COUNT <= 4
    assert module.MARKET_MA_DAYS == 120
    assert module.RISK_OFF_EXPOSURE == 0.5


def test_published_core_variant_keeps_post_parameters_and_pit_dates():
    source = PUBLISHED_CORE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "STOCK_COUNT = 10" in source
    assert "MAXIMUM_PRICE = 10.0" in source
    assert "MINIMUM_QUARTER_ROE = 0.15" in source
    assert "MINIMUM_QUARTER_ROA = 0.10" in source
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "get_fundamentals":
                assert any(keyword.arg == "date" for keyword in node.keywords)
