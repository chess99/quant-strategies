import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest


FAMILY = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[4]
MACD = FAMILY / "variants" / "macd_binary.py"
BALANCED = FAMILY / "variants" / "balanced_ensemble.py"
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


@pytest.mark.parametrize("path", [MACD, BALANCED])
def test_variant_is_self_contained_platform_file(path):
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "from __future__ import annotations" not in source
    assert 'set_option("use_real_price", True)' in source
    assert 'set_option("avoid_future_data", True)' in source
    assert "context.previous_date" in source
    assert "start_date=history_start" in source
    assert "end_date=observation_date" in source
    assert "g.security, g.history_start, observation_date" in source
    assert "current_data.get" not in source
    assert ".to_numpy(" not in source

    forbidden = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"sum", "all", "any"}
    }
    assert forbidden == set()


def test_macd_variant_matches_research_formula():
    strategy = load_module(MACD, "star50_macd_binary")
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


def test_macd_signal_requires_complete_history_and_tracks_direction():
    strategy = load_module(MACD, "star50_macd_signal")
    assert strategy.latest_macd_signal(np.arange(33.0), 12, 26, 9)[0] is None
    assert strategy.latest_macd_signal(np.arange(100.0), 12, 26, 9)[0] is True
    assert strategy.latest_macd_signal(np.arange(100.0, 0.0, -1.0), 12, 26, 9)[0] is False


@pytest.mark.parametrize(
    ("path", "name", "loader_name", "empty_history", "extra_globals", "warning"),
    [
        (
            MACD,
            "star50_macd_warmup",
            "load_close_history",
            np.array([], dtype=float),
            {"fast_period": 12, "slow_period": 26, "signal_period": 9},
            "MACD历史数据不足，至少需要34个交易日；热身期不交易",
        ),
        (
            BALANCED,
            "star50_balanced_warmup",
            "load_price_history",
            pd.DataFrame(columns=["high", "low", "close"]),
            {"pending_target_weight": None},
            "平衡型目标历史数据不足，至少需要200个交易日；热身期不交易",
        ),
    ],
)
def test_variant_insufficient_history_warning_is_emitted_once(
    path,
    name,
    loader_name,
    empty_history,
    extra_globals,
    warning,
):
    strategy = load_module(path, name)
    strategy.g = SimpleNamespace(
        security="588000.XSHG",
        history_start="2020-11-16",
        target_weight=0.99,
        insufficient_history_warned=False,
        **extra_globals,
    )
    setattr(strategy, loader_name, lambda *_: empty_history)
    warnings = []
    strategy.log = SimpleNamespace(warning=lambda message: warnings.append(message))
    context = SimpleNamespace(previous_date="2020-11-16")

    strategy.rebalance(context)
    strategy.rebalance(context)

    assert warnings == [warning]


def configure_macd_execution_stubs(strategy, bullish, positions):
    security = "588000.XSHG"
    strategy.g = SimpleNamespace(
        security=security,
        fast_period=12,
        slow_period=26,
        signal_period=9,
        history_start="2020-11-16",
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


def test_macd_bullish_signal_buys_round_lot_once():
    strategy = load_module(MACD, "star50_macd_buy")
    security, context = configure_macd_execution_stubs(strategy, True, {})
    orders = []
    strategy.order_target = lambda code, amount: orders.append((code, amount))

    strategy.rebalance(context)
    context.portfolio.positions[security] = SimpleNamespace(total_amount=9900)
    strategy.rebalance(context)

    assert orders == [(security, 9900)]


def test_macd_bearish_signal_liquidates_existing_position():
    strategy = load_module(MACD, "star50_macd_sell")
    security = "588000.XSHG"
    positions = {security: SimpleNamespace(total_amount=1200)}
    security, context = configure_macd_execution_stubs(strategy, False, positions)
    orders = []
    strategy.order_target = lambda code, amount: orders.append((code, amount))

    strategy.rebalance(context)

    assert orders == [(security, 0)]


def test_balanced_variant_reproduces_frozen_target():
    strategy = load_module(BALANCED, "star50_balanced_ensemble")
    frame = pd.read_csv(ARCHIVED_INPUT)
    targets = strategy.balanced_ensemble_targets(
        frame[["high", "low", "close"]],
        rebalance_threshold=0.10,
    )
    assert targets[-1] == pytest.approx(0.11890493840797611)


def test_balanced_fixed_ensemble_never_exceeds_risk_core():
    strategy = load_module(BALANCED, "star50_balanced_ensemble_bounds")
    frame = pd.read_csv(ARCHIVED_INPUT)[["high", "low", "close"]]
    core = strategy.risk_core_targets(frame["close"].to_numpy())
    combined = strategy.fixed_ensemble_raw_targets(frame)
    assert np.all(combined >= -1e-12)
    assert np.all(combined <= core + 1e-12)


def test_balanced_rebalance_submits_round_lot_target():
    strategy = load_module(BALANCED, "star50_balanced_rebalance")
    security = "588000.XSHG"
    strategy.g = SimpleNamespace(
        security=security,
        history_start="2020-11-16",
        pending_target_weight=None,
    )
    strategy.load_price_history = lambda *_: pd.DataFrame(
        {"high": np.arange(200.0), "low": np.arange(200.0), "close": np.arange(200.0)}
    )
    strategy.latest_target_weights = lambda *_: (0.20, 0.10)
    strategy.record = lambda **_: None
    strategy.log = SimpleNamespace(warning=lambda *_: None)
    strategy.get_current_data = lambda: {
        security: SimpleNamespace(
            paused=False,
            is_st=False,
            last_price=2.0,
            high_limit=2.2,
            low_limit=1.8,
        )
    }
    context = SimpleNamespace(
        previous_date="2026-09-01",
        portfolio=SimpleNamespace(total_value=10000.0, positions={}),
    )
    orders = []
    strategy.order_target = lambda code, amount: orders.append((code, amount)) or object()

    strategy.rebalance(context)

    assert orders == [(security, 1000)]
    assert strategy.g.pending_target_weight is None
