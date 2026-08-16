import ast
from pathlib import Path


FAMILY = Path(__file__).resolve().parents[1]
STRATEGY = FAMILY / "variants" / "conditional_momentum_overlay_v2.py"
REPLAY = FAMILY / "v2_joinquant_replay.py"
CORE_BENCHMARK = FAMILY / "v2_core_benchmark.py"


def test_v2_platform_variant_is_self_contained_and_old_runtime_compatible():
    source = STRATEGY.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "from __future__ import annotations" not in source
    assert "from jqdata import *" in source
    assert "set_option('avoid_future_data', True)" in source
    assert "set_option('use_real_price', True)" in source
    assert "run_weekly(rebalance, weekday=1, time='10:30'" in source
    forbidden = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"sum", "all", "any"}
    }
    assert forbidden == set()


def test_v2_platform_variant_contains_frozen_candidate_parameters():
    source = STRATEGY.read_text(encoding="utf-8")
    assert "g.core_weights = {" in source
    assert "'510300.XSHG': 0.40" in source
    assert "'511010.XSHG': 0.40" in source
    assert "'518880.XSHG': 0.20" in source
    assert "g.active_sleeve = 0.30" in source
    assert "g.active_single_symbol_cap = 0.15" in source
    assert "g.lookbacks = (63, 126, 252)" in source
    assert "g.minimum_excess_horizons = 2" in source
    assert "g.minimum_dispersion_iqr = 0.10" in source
    assert "g.top_k = 3" in source
    assert "g.rank_buffer = 2" in source
    assert "g.max_pair_corr = 0.90" in source
    assert "g.min_adv20 = 20_000_000" in source
    assert "g.max_adv_participation = 0.005" in source


def test_v2_research_replay_is_paired_with_identical_strategic_core():
    source = REPLAY.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "from __future__ import annotations" not in source
    assert 'start_date="2014-01-02"' in source
    assert 'end_date="2026-07-24"' in source
    assert 'frequency="weekly"' in source
    assert 'execution_price="open"' in source
    assert "def v2_target_weights(context):" in source
    assert "def core_target_weights(context):" in source
    assert "class _StrategyState(object):" in source
    assert "strategy.g = _StrategyState()" in source
    forbidden = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"sum", "all", "any"}
    }
    assert forbidden == set()


def test_official_core_benchmark_uses_same_schedule_costs_and_weights():
    source = CORE_BENCHMARK.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "from __future__ import annotations" not in source
    assert "set_option('avoid_future_data', True)" in source
    assert "set_slippage(PriceRelatedSlippage(0.002), type='fund')" in source
    assert "'510300.XSHG': 0.40" in source
    assert "'511010.XSHG': 0.40" in source
    assert "'518880.XSHG': 0.20" in source
    assert "run_weekly(rebalance, weekday=1, time='10:30'" in source
    forbidden = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"sum", "all", "any"}
    }
    assert forbidden == set()
