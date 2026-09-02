import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd


FAMILY = Path(__file__).resolve().parents[1]
STRATEGY = FAMILY / "baseline.py"


def load_strategy():
    spec = importlib.util.spec_from_file_location("star50_macd_baseline", STRATEGY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def test_macd_matches_research_formula():
    strategy = load_strategy()
    close = 100.0 + np.linspace(0.0, 30.0, 120) + np.sin(np.arange(120) / 4.0)

    difference, signal_line, histogram = strategy.macd_components(close, 12, 26, 9)
    series = pd.Series(close)
    expected_difference = (
        series.ewm(span=12, adjust=False, min_periods=12).mean()
        - series.ewm(span=26, adjust=False, min_periods=26).mean()
    )
    expected_signal = expected_difference.ewm(
        span=9, adjust=False, min_periods=9
    ).mean()

    np.testing.assert_allclose(difference, expected_difference, equal_nan=True)
    np.testing.assert_allclose(signal_line, expected_signal, equal_nan=True)
    np.testing.assert_allclose(histogram, expected_difference - expected_signal, equal_nan=True)


def test_signal_requires_complete_history_and_tracks_direction():
    strategy = load_strategy()
    assert strategy.latest_macd_signal(np.arange(33.0), 12, 26, 9)[0] is None
    assert strategy.latest_macd_signal(np.arange(100.0), 12, 26, 9)[0] is True
    assert strategy.latest_macd_signal(np.arange(100.0, 0.0, -1.0), 12, 26, 9)[0] is False


def test_tradability_checks_limits_and_status():
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


def test_round_lot_never_exceeds_budget():
    strategy = load_strategy()
    assert strategy.affordable_round_lot(10000.0, 1.23) == 8100
    assert strategy.affordable_round_lot(99.0, 1.0) == 0
    assert strategy.affordable_round_lot(10000.0, 0.0) == 0


def configure_execution_stubs(strategy, bullish, positions):
    security = "588000.XSHG"
    strategy.g = SimpleNamespace(
        security=security,
        fast_period=12,
        slow_period=26,
        signal_period=9,
        history_count=252,
        target_weight=0.99,
    )
    strategy.load_close_history = lambda *_: np.arange(100.0)
    strategy.latest_macd_signal = lambda *_: (bullish, 1.0, 0.5)
    strategy.record = lambda **_: None
    strategy.log = SimpleNamespace(warning=lambda *_: None)
    strategy.get_current_data = lambda: {
        security: SimpleNamespace(
            paused=False,
            is_st=False,
            last_price=1.0,
            high_limit=1.1,
            low_limit=0.9,
        )
    }
    context = SimpleNamespace(
        previous_date="2026-09-01",
        portfolio=SimpleNamespace(total_value=10000.0, positions=positions),
    )
    return security, context


def test_bullish_signal_buys_round_lot_once():
    strategy = load_strategy()
    security, context = configure_execution_stubs(strategy, True, {})
    orders = []
    strategy.order_target = lambda code, amount: orders.append((code, amount))

    strategy.rebalance(context)

    assert orders == [(security, 9900)]


def test_bearish_signal_liquidates_existing_position():
    strategy = load_strategy()
    security = "588000.XSHG"
    positions = {security: SimpleNamespace(total_amount=1200)}
    security, context = configure_execution_stubs(strategy, False, positions)
    orders = []
    strategy.order_target = lambda code, amount: orders.append((code, amount))

    strategy.rebalance(context)

    assert orders == [(security, 0)]
