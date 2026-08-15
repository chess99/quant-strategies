import ast
from pathlib import Path


FAMILY = Path(__file__).resolve().parents[1]
STRATEGY = FAMILY / "baseline.py"


def test_platform_file_is_valid_and_baseline_parameters_are_frozen():
    source = STRATEGY.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "from __future__ import annotations" not in source
    assert "set_option('avoid_future_data', True)" in source or (
        'set_option("avoid_future_data", True)' in source
    )
    assert "context.previous_date" in source
    assert "g.lookbacks = (63, 126, 252)" in source
    assert "g.top_k = 3" in source
    assert "g.rank_buffer = 2" in source
    assert "g.max_pair_corr = 0.90" in source
    assert "g.target_portfolio_vol = 0.18" in source
    assert "g.min_adv20 = 20_000_000" in source
    forbidden = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"sum", "all", "any"}
    }
    assert forbidden == set()


def test_lazy_current_data_is_loaded_by_subscription():
    source = STRATEGY.read_text(encoding="utf-8")
    assert "if c not in current_data" not in source
    assert "current_data[c]" in source
