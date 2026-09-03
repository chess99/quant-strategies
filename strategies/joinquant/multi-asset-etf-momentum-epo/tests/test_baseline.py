import ast
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


FAMILY = Path(__file__).resolve().parents[1]
STRATEGY = FAMILY / "baseline.py"


def load_strategy():
    spec = importlib.util.spec_from_file_location("multi_asset_epo_baseline", STRATEGY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def trending_close(periods=100):
    dates = pd.date_range("2023-01-02", periods=periods, freq="B")
    return pd.DataFrame(
        {
            "A": np.exp(np.arange(periods) * 0.004),
            "B": np.exp(np.arange(periods) * 0.003),
            "C": np.exp(np.arange(periods) * 0.002),
            "D": np.exp(np.arange(periods) * -0.001),
        },
        index=dates,
    )


def test_platform_file_is_causal_self_contained_and_joinquant_compatible():
    source = STRATEGY.read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert "from __future__ import annotations" not in source
    assert 'set_option("use_real_price", True)' in source
    assert 'set_option("avoid_future_data", True)' in source
    assert "context.previous_date" in source
    assert "from jqdata import *" in source
    assert "run_epo_safe_research" not in source
    assert "quant_research" not in source
    forbidden = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"sum", "all", "any"}
    }
    assert forbidden == set()


def test_frozen_parameters_and_asset_pool_are_not_changed():
    strategy = load_strategy()

    assert strategy.MOMENTUM_DAYS == 34
    assert strategy.STOCK_NUM == 3
    assert strategy.EPO_W == 0.2
    assert strategy.PRICE_HISTORY_DAYS == 1200
    assert strategy.ETF_POOL == (
        "518880.XSHG",
        "159985.XSHE",
        "513100.XSHG",
        "510300.XSHG",
        "159915.XSHE",
        "159992.XSHE",
        "515700.XSHG",
        "510150.XSHG",
        "515790.XSHG",
        "515880.XSHG",
        "512720.XSHG",
        "512660.XSHG",
        "159740.XSHE",
    )


def test_safe_fallback_equal_weights_only_frozen_momentum_selection(monkeypatch):
    strategy = load_strategy()
    close = trending_close()

    def no_positive_weights(*args, **kwargs):
        raise ValueError("EPO produced no positive weights")

    monkeypatch.setattr(strategy, "epo_weights", no_positive_weights)
    weights, diagnostics = strategy.build_target_weights(close, close.index[-1])

    assert weights == pytest.approx({"A": 1 / 3, "B": 1 / 3, "C": 1 / 3})
    assert diagnostics["selected"] == ["A", "B", "C"]
    assert diagnostics["fallback_used"] is True


def test_safe_fallback_does_not_swallow_unrelated_errors(monkeypatch):
    strategy = load_strategy()

    def invalid_covariance(*args, **kwargs):
        raise ValueError("EPO covariance contains non-positive variance")

    monkeypatch.setattr(strategy, "epo_weights", invalid_covariance)
    with pytest.raises(ValueError, match="non-positive variance"):
        strategy.build_target_weights(trending_close(), pd.Timestamp("2023-05-19"))


def test_close_normalization_accepts_joinquant_long_frame():
    strategy = load_strategy()
    raw = pd.DataFrame(
        {
            "time": ["2024-01-02", "2024-01-02", "2024-01-03", "2024-01-03"],
            "code": ["A", "B", "A", "B"],
            "close": [1.0, 2.0, 1.1, 2.1],
        }
    )

    close = strategy.normalize_close_frame(raw)

    assert list(close.columns) == ["A", "B"]
    assert close.loc[pd.Timestamp("2024-01-03"), "B"] == 2.1


def test_sell_block_aborts_rebalance_before_any_order(monkeypatch):
    strategy = load_strategy()
    calls = []

    class Snapshot:
        def __init__(self, paused=False, last=1.0, low=0.9, high=1.1):
            self.paused = paused
            self.is_st = False
            self.last_price = last
            self.low_limit = low
            self.high_limit = high

    class Position:
        total_amount = 100

    class Portfolio:
        total_value = 100_000.0
        positions = {"OLD": Position()}

    class Context:
        previous_date = pd.Timestamp("2024-01-31")
        portfolio = Portfolio()

    class Logger:
        @staticmethod
        def info(*args):
            return None

        @staticmethod
        def warning(*args):
            return None

    monkeypatch.setattr(strategy, "target_weights_for_date", lambda _: ({"NEW": 1.0}, {}))
    monkeypatch.setattr(
        strategy,
        "get_current_data",
        lambda: {"OLD": Snapshot(paused=True), "NEW": Snapshot()},
        raising=False,
    )
    monkeypatch.setattr(
        strategy,
        "order_target_value",
        lambda code, value: calls.append((code, value)),
        raising=False,
    )
    monkeypatch.setattr(strategy, "log", Logger(), raising=False)

    strategy.rebalance(Context())

    assert calls == []
