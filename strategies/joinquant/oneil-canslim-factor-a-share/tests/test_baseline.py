import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "baseline.py"


def test_joinquant_source_is_self_contained_and_legacy_compatible():
    source = SOURCE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert "from __future__ import annotations" not in source
    assert "from jqdata import *" in source
    assert "import trading_os" not in source
    assert "current_data.get(" not in source
    unqualified = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"sum", "all", "any"}
    ]
    assert unqualified == []


def test_point_in_time_boundaries_and_market_universe_are_explicit():
    source = SOURCE_PATH.read_text(encoding="utf-8")

    assert 'get_index_stocks("000300.XSHG", date=observation_date)' in source
    assert 'get_index_stocks("000905.XSHG", date=observation_date)' in source
    assert "watch_date=observation_date" in source
    assert "end_date=observation_date" in source
    assert 'set_option("avoid_future_data", True)' in source


def test_platform_source_declares_missing_institutional_filter():
    source = SOURCE_PATH.read_text(encoding="utf-8")

    assert 'INSTITUTIONAL_FILTER = "unavailable-not-proxied"' in source
    assert "income.basic_eps" in source
    assert "income.np_parent_company_owners" in source
    assert "income.total_operating_revenue" in source


def test_orders_use_integer_board_lots_and_lazy_current_data_indexing():
    source = SOURCE_PATH.read_text(encoding="utf-8")

    assert "BOARD_LOT = 100" in source
    assert "current_data[code]" in source
    assert "order_target(code, target_shares)" in source
