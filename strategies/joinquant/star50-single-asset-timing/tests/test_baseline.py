import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest


FAMILY = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[4]
STRATEGY = FAMILY / "baseline.py"
ARCHIVED_INPUT = (
    REPO
    / "studies"
    / "star50-single-asset-timing"
    / "results"
    / "2026-09-01__walk-forward-technical-families__tencent-yahoo-2020-2026-v1"
    / "raw"
    / "input-sh588000.csv"
)


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_strategy():
    return load_module(STRATEGY, "star50_timing_baseline")


def test_platform_file_is_valid_and_causal():
    source = STRATEGY.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "from __future__ import annotations" not in source
    assert 'set_option("use_real_price", True)' in source
    assert 'set_option("avoid_future_data", True)' in source
    assert "context.previous_date" in source
    assert "end_date=observation_date" in source
    assert "current_data.get" not in source

    forbidden = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"sum", "all", "any"}
    }
    assert forbidden == set()


def test_rebalance_threshold_matches_frozen_rule():
    strategy = load_strategy()
    raw = np.array([0.0, 0.20, 0.23, 0.26, 0.0, 0.03, 0.30])
    expected = np.array([0.0, 0.20, 0.20, 0.26, 0.0, 0.03, 0.30])
    np.testing.assert_allclose(strategy.apply_rebalance_threshold(raw, 0.05), expected)
    np.testing.assert_allclose(
        strategy.apply_rebalance_threshold([np.nan, -0.1, 0.4, np.inf], 0.0),
        [0.0, 0.0, 0.4, 0.0],
    )


def test_risk_core_reproduces_frozen_target():
    strategy = load_strategy()
    frame = pd.read_csv(ARCHIVED_INPUT)
    targets = strategy.risk_core_targets(
        frame["close"].to_numpy(),
        trend_period=200,
        volatility_period=60,
        target_volatility=0.15,
        rebalance_threshold=0.05,
        maximum_weight=0.99,
    )
    assert targets[-1] == pytest.approx(0.2482052765086407)


def test_target_requires_complete_history():
    strategy = load_strategy()
    assert strategy.latest_target_weights(np.arange(199.0))[0] is None


def test_target_change_and_failed_boundary_orders_are_retried():
    strategy = load_strategy()
    assert strategy.should_submit_order(1000, 0.30, 0.30) is False
    assert strategy.should_submit_order(1000, 0.35, 0.30) is True
    assert strategy.should_submit_order(0, 0.30, 0.30) is True
    assert strategy.should_submit_order(1000, 0.0, 0.0) is True
    assert strategy.should_submit_order(0, 0.0, 0.0) is False


def test_tradability_and_round_lot_helpers():
    strategy = load_strategy()
    normal = SimpleNamespace(
        paused=False,
        is_st=False,
        last_price=1.0,
        high_limit=1.1,
        low_limit=0.9,
    )
    assert strategy.can_buy(normal)
    assert strategy.can_sell(normal)
    assert not strategy.can_buy(SimpleNamespace(**{**normal.__dict__, "paused": True}))
    assert not strategy.can_buy(SimpleNamespace(**{**normal.__dict__, "last_price": 1.1}))
    assert not strategy.can_sell(SimpleNamespace(**{**normal.__dict__, "last_price": 0.9}))
    assert strategy.affordable_round_lot(10000.0, 1.23) == 8100
    assert strategy.affordable_round_lot(99.0, 1.0) == 0


def configure_execution_stubs(strategy, target, previous_target, positions):
    security = "588000.XSHG"
    strategy.g = SimpleNamespace(
        security=security,
        history_start="2020-11-16",
        pending_target_weight=None,
    )
    strategy.load_close_history = lambda *_: np.arange(200.0)
    strategy.latest_target_weights = lambda *_: (target, previous_target)
    strategy.record = lambda **_: None
    strategy.log = SimpleNamespace(warning=lambda *_: None)
    snapshot = SimpleNamespace(
        paused=False,
        is_st=False,
        last_price=1.0,
        high_limit=1.1,
        low_limit=0.9,
    )
    strategy.get_current_data = lambda: {security: snapshot}
    context = SimpleNamespace(
        previous_date="2026-09-01",
        portfolio=SimpleNamespace(total_value=10000.0, positions=positions),
    )
    return security, snapshot, context


def test_rebalance_submits_round_lot_target():
    strategy = load_strategy()
    security, _, context = configure_execution_stubs(strategy, 0.30, 0.25, {})
    orders = []
    strategy.order_target = lambda code, amount: orders.append((code, amount)) or object()

    strategy.rebalance(context)

    assert orders == [(security, 3000)]
    assert strategy.g.pending_target_weight is None


def test_blocked_rebalance_keeps_target_and_retries_next_day():
    strategy = load_strategy()
    security, snapshot, context = configure_execution_stubs(strategy, 0.30, 0.25, {})
    orders = []
    strategy.order_target = lambda code, amount: orders.append((code, amount)) or object()

    snapshot.last_price = snapshot.high_limit
    strategy.rebalance(context)
    assert orders == []
    assert strategy.g.pending_target_weight == pytest.approx(0.30)

    strategy.latest_target_weights = lambda *_: (0.30, 0.30)
    snapshot.last_price = 1.0
    strategy.rebalance(context)

    assert orders == [(security, 3000)]
    assert strategy.g.pending_target_weight is None
