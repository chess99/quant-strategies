from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd


STUDY_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = STUDY_DIR / "run_start_date_robustness.py"


def load_module():
    spec = importlib.util.spec_from_file_location("star50_start_date_robustness", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def synthetic_bars(periods=40):
    dates = pd.bdate_range("2025-01-02", periods=periods)
    dates.name = "trade_date"
    close = 100.0 + np.arange(periods, dtype=float)
    return pd.DataFrame(
        {
            "symbol": "SH588000",
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 50_000_000.0,
            "amount": close * 50_000_000.0,
        },
        index=dates,
    )


def test_start_windows_use_every_eligible_day_and_exact_horizon():
    module = load_module()
    frame = synthetic_bars(20)

    windows = module.build_start_windows(frame, warmup_sessions=5, horizons=(3, 5))

    assert len(windows[windows["horizon_sessions"].eq(3)]) == 13
    assert len(windows[windows["horizon_sessions"].eq(5)]) == 11
    first = windows.iloc[0]
    assert first["start_date"] == frame.index[5]
    assert first["end_date"] == frame.index[7]
    assert first["calendar_sessions"] == 3


def test_monthly_cohort_keeps_first_available_start_per_month_and_horizon():
    module = load_module()
    frame = synthetic_bars(40)
    windows = module.build_start_windows(frame, warmup_sessions=2, horizons=(3,))

    monthly = module.monthly_start_mask(windows)
    selected = windows.loc[monthly]

    assert not selected.empty
    assert selected.groupby(
        ["horizon_sessions", selected["start_date"].dt.to_period("M")]
    ).size().eq(1).all()


def test_summary_uses_matched_start_benchmark_and_severe_loss_definition():
    module = load_module()
    rows = []
    for start, benchmark_return, strategy_return, benchmark_dd, strategy_dd in (
        ("2024-01-02", 0.10, 0.08, 0.20, 0.10),
        ("2024-02-01", -0.25, -0.15, 0.30, 0.20),
    ):
        for model, total_return, drawdown, sharpe in (
            ("buy-hold", benchmark_return, benchmark_dd, 0.5),
            ("risk-friction__threshold-0p05", strategy_return, strategy_dd, 0.8),
        ):
            rows.append(
                {
                    "model": model,
                    "horizon_sessions": 252,
                    "start_date": pd.Timestamp(start),
                    "end_date": pd.Timestamp(start) + pd.offsets.BDay(251),
                    "total_return": total_return,
                    "annualized_return": total_return,
                    "maximum_drawdown": drawdown,
                    "sharpe": sharpe,
                    "longest_underwater_trading_days": 10,
                    "average_exposure": 0.4 if model != "buy-hold" else 0.99,
                    "filled_trade_count": 2,
                    "total_commission": 10.0,
                    "initial_target_weight": 0.4,
                    "trend_regime": "up",
                    "volatility_regime": "normal",
                }
            )
    results = module.add_matched_benchmark_fields(pd.DataFrame(rows))
    summary = module.summarize_start_results(results, cohort="daily")
    strategy = summary[summary["model"].eq("risk-friction__threshold-0p05")].iloc[0]

    assert strategy["outperform_benchmark_rate"] == 0.5
    assert strategy["drawdown_improvement_rate"] == 1.0
    assert strategy["sharpe_improvement_rate"] == 1.0
    assert strategy["severe_start_rate"] == 0.0


def test_cached_simulation_matches_canonical_engine():
    module = load_module()
    frame = synthetic_bars(40)
    target = pd.Series(0.50, index=frame.index)
    desired = module.engine.execution_target(target, delay=1)
    bars, market_state = module.engine._engine_inputs(frame)
    start = frame.index[5]
    end = frame.index[20]

    cached_metrics, cached_trades = module._cached_simulation(
        "cached", frame, desired, start, end, bars, market_state
    )
    canonical = module.engine.simulate_target(
        "canonical", frame, target, start, end
    )

    for key in (
        "total_return",
        "annualized_return",
        "maximum_drawdown",
        "sharpe",
        "average_exposure",
        "filled_trade_count",
    ):
        assert cached_metrics[key] == canonical.metrics[key]
    pd.testing.assert_frame_equal(cached_trades, canonical.trades)


def test_rejected_initial_target_is_retried_next_session():
    module = load_module()
    frame = synthetic_bars(12)
    frame.iloc[4, frame.columns.get_loc("close")] = 100.0
    frame.iloc[5, frame.columns.get_loc("open")] = 120.0
    frame.iloc[5, frame.columns.get_loc("high")] = 120.0
    frame.iloc[5, frame.columns.get_loc("low")] = 118.0
    frame.iloc[5, frame.columns.get_loc("close")] = 120.0
    frame.iloc[6, frame.columns.get_loc("open")] = 119.0
    frame.iloc[6, frame.columns.get_loc("high")] = 121.0
    frame.iloc[6, frame.columns.get_loc("low")] = 118.0
    frame.iloc[6, frame.columns.get_loc("close")] = 120.0
    target = pd.Series(0.50, index=frame.index)
    desired = module.engine.execution_target(target, delay=1)
    bars, market_state = module.engine._engine_inputs(frame)

    metrics, trades = module._cached_simulation(
        "retry", frame, desired, frame.index[5], frame.index[10], bars, market_state
    )

    assert metrics["rejected_order_count"] == 1
    assert metrics["filled_trade_count"] == 1
    assert pd.Timestamp(trades.iloc[0]["trade_date"]) == frame.index[6]


def test_gate_evaluation_keeps_risk_and_alpha_claims_separate():
    module = load_module()
    summary = pd.DataFrame(
        [
            {
                "cohort": "daily",
                "model": "buy-hold",
                "horizon_sessions": horizon,
                "median_annualized_return": 0.20,
                "positive_return_rate": 0.90,
                "severe_start_rate": 0.20,
                "drawdown_improvement_rate": np.nan,
                "sharpe_improvement_rate": np.nan,
                "outperform_benchmark_rate": np.nan,
                "median_total_return_difference": np.nan,
            }
            for horizon in (252, 504)
        ]
        + [
            {
                "cohort": "daily",
                "model": "risk-friction__threshold-0p05",
                "horizon_sessions": horizon,
                "median_annualized_return": 0.12,
                "positive_return_rate": 0.80,
                "severe_start_rate": 0.05,
                "drawdown_improvement_rate": 0.90,
                "sharpe_improvement_rate": 0.70,
                "outperform_benchmark_rate": 0.40,
                "median_total_return_difference": -0.02,
            }
            for horizon in (252, 504)
        ]
    )

    gates = module.evaluate_start_robustness_gates(summary)
    row = gates.iloc[0]

    assert row["risk_robust"]
    assert not row["return_timing_robust"]


def test_protocol_and_source_contain_no_machine_absolute_paths():
    module = load_module()
    windows_absolute = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]")
    protocol = (STUDY_DIR / "START_DATE_ROBUSTNESS.md").read_text(encoding="utf-8")
    source = MODULE_PATH.read_text(encoding="utf-8")

    assert "事后起点敏感性诊断" in protocol
    assert "每个启动日都创建全新的" in protocol
    assert module.HORIZONS == (63, 126, 252, 504)
    assert not windows_absolute.search(protocol)
    assert not windows_absolute.search(source)
