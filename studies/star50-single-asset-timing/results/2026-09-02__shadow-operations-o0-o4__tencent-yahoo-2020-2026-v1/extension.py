"""把科创 50 ETF 技术择时骨架扩展为实盘候选并执行预注册 G0-G3 实验。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


SOURCE_PATH = Path(__file__).resolve()
LOCAL_ENGINE = SOURCE_PATH.with_name("engine.py")
ENGINE_PATH = LOCAL_ENGINE if LOCAL_ENGINE.exists() else SOURCE_PATH.with_name("run_study.py")


def _load_engine():
    spec = importlib.util.spec_from_file_location("star50_timing_engine", ENGINE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载科创 50 研究执行引擎")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


engine = _load_engine()
ROOT = engine.ROOT
STUDY_DIR = ROOT / "studies" / "star50-single-asset-timing"
TARGET_WEIGHT = engine.TARGET_WEIGHT
TRADING_DAYS = engine.TRADING_DAYS
BASE_COMMISSION = engine.BASE_COMMISSION
BASE_SLIPPAGE = engine.BASE_SLIPPAGE
WARMUP_SESSIONS = engine.WARMUP_SESSIONS
INITIAL_TRAIN_SESSIONS = engine.INITIAL_TRAIN_SESSIONS
TEST_SESSIONS = engine.TEST_SESSIONS
MINIMUM_FINAL_TEST_SESSIONS = engine.MINIMUM_FINAL_TEST_SESSIONS
PHASE1_RESULT = (
    STUDY_DIR
    / "results"
    / "2026-09-01__walk-forward-technical-families__tencent-yahoo-2020-2026-v1"
)
DEFAULT_INPUT = PHASE1_RESULT / "raw" / "input-sh588000.csv"


@dataclass(frozen=True)
class ProductionConfig:
    generation: str
    name: str
    archetype: str
    objective: str
    params: dict


def _slug(value) -> str:
    if isinstance(value, float):
        return f"{value:g}".replace("-", "m").replace(".", "p")
    return str(value).replace("-", "m").replace(".", "p")


def build_production_configs() -> list[ProductionConfig]:
    configs = []
    for trend_period in (150, 200, 250):
        for vol_period in (20, 60):
            for target_vol in (0.15, 0.20):
                configs.append(
                    ProductionConfig(
                        "G0",
                        f"risk-core__trend-{trend_period}-vol-{vol_period}-target-{_slug(target_vol)}",
                        "risk-core",
                        "risk",
                        {
                            "kind": "risk-core",
                            "trend_period": trend_period,
                            "vol_period": vol_period,
                            "target_vol": target_vol,
                        },
                    )
                )

    friction_specs = [
        ("buffer-0p01", {"buffer": 0.01}),
        ("buffer-0p02", {"buffer": 0.02}),
        ("threshold-0p05", {"rebalance_threshold": 0.05}),
        ("threshold-0p1", {"rebalance_threshold": 0.10}),
        ("threshold-0p15", {"rebalance_threshold": 0.15}),
        ("schedule-5", {"schedule_sessions": 5}),
        ("smooth-3", {"smooth_span": 3}),
        ("smooth-5", {"smooth_span": 5}),
        ("smooth-10", {"smooth_span": 10}),
        ("slope-20", {"slope_sessions": 20}),
    ]
    for suffix, changes in friction_specs:
        configs.append(
            ProductionConfig(
                "G1",
                f"risk-friction__{suffix}",
                "risk-friction",
                "risk",
                {"kind": "risk-core", **_canonical_core_params(), **changes},
            )
        )

    for floor in (0.0, 0.25, 0.50):
        configs.append(
            ProductionConfig(
                "G2",
                f"macd-overlay__floor-{_slug(floor)}",
                "macd-overlay",
                "return",
                {"kind": "macd-overlay", "floor": floor},
            )
        )
    for multiplier in (1.5, 2.0, 2.5):
        for floor in (0.25, 0.50):
            configs.append(
                ProductionConfig(
                    "G2",
                    f"keltner-overlay__multiplier-{_slug(multiplier)}-floor-{_slug(floor)}",
                    "keltner-overlay",
                    "return",
                    {
                        "kind": "keltner-overlay",
                        "multiplier": multiplier,
                        "floor": floor,
                    },
                )
            )
    configs.append(
        ProductionConfig(
            "G2",
            "fixed-ensemble__core-macd-keltner",
            "fixed-ensemble",
            "balanced",
            {"kind": "fixed-ensemble"},
        )
    )

    generation_three = [
        (
            "production-core__buffer-0p02-threshold-0p1",
            "production-core",
            "risk",
            {
                "kind": "risk-core",
                **_canonical_core_params(),
                "buffer": 0.02,
                "rebalance_threshold": 0.10,
            },
        ),
        (
            "production-core__buffer-0p02-smooth-5-threshold-0p05",
            "production-core",
            "risk",
            {
                "kind": "risk-core",
                **_canonical_core_params(),
                "buffer": 0.02,
                "smooth_span": 5,
                "rebalance_threshold": 0.05,
            },
        ),
        (
            "production-core__buffer-0p02-schedule-5-threshold-0p1",
            "production-core",
            "risk",
            {
                "kind": "risk-core",
                **_canonical_core_params(),
                "buffer": 0.02,
                "schedule_sessions": 5,
                "rebalance_threshold": 0.10,
            },
        ),
        (
            "risk-guard__volatility-shock",
            "risk-guard",
            "risk",
            {"kind": "volatility-shock"},
        ),
        (
            "risk-guard__drawdown-63d-0p12",
            "risk-guard",
            "risk",
            {"kind": "drawdown-guard"},
        ),
        (
            "production-ensemble__threshold-0p1",
            "production-ensemble",
            "balanced",
            {"kind": "fixed-ensemble", "rebalance_threshold": 0.10},
        ),
    ]
    for name, archetype, objective, params in generation_three:
        configs.append(ProductionConfig("G3", name, archetype, objective, params))

    if len(configs) != 38:
        raise AssertionError(f"实盘扩展注册表应为38项，实际为{len(configs)}项")
    if len({config.name for config in configs}) != len(configs):
        raise AssertionError("实盘扩展配置名称重复")
    return configs


def _canonical_core_params() -> dict:
    return {"trend_period": 200, "vol_period": 60, "target_vol": 0.15}


def hysteresis_state(
    close: pd.Series,
    moving_average: pd.Series,
    buffer: float,
) -> pd.Series:
    state = False
    output = []
    for price, average in zip(close, moving_average):
        if not np.isfinite(price) or not np.isfinite(average):
            state = False
        elif state and price <= average * (1.0 - buffer):
            state = False
        elif not state and price >= average * (1.0 + buffer):
            state = True
        output.append(state)
    return pd.Series(output, index=close.index, dtype=bool)


def apply_rebalance_threshold(target: pd.Series, threshold: float) -> pd.Series:
    if threshold <= 0.0:
        return target.astype(float).copy()
    held = None
    output = []
    for desired in target.fillna(0.0).astype(float):
        desired = min(max(desired, 0.0), TARGET_WEIGHT)
        if held is None or desired <= 1e-12 or held <= 1e-12:
            held = desired
        elif abs(desired - held) >= threshold:
            held = desired
        output.append(held)
    return pd.Series(output, index=target.index, dtype=float)


def apply_update_schedule(target: pd.Series, sessions: int) -> pd.Series:
    if sessions <= 1:
        return target.astype(float).copy()
    held = 0.0
    output = []
    for position, desired in enumerate(target.fillna(0.0).astype(float)):
        if position == 0 or position % sessions == 0 or desired <= 1e-12:
            held = desired
        output.append(held)
    return pd.Series(output, index=target.index, dtype=float)


def _risk_core_target(frame: pd.DataFrame, params: dict) -> pd.Series:
    close = frame["close"].astype(float)
    trend_period = int(params.get("trend_period", 200))
    vol_period = int(params.get("vol_period", 60))
    target_vol = float(params.get("target_vol", 0.15))
    moving_average = close.rolling(trend_period, min_periods=trend_period).mean()
    buffer = float(params.get("buffer", 0.0))
    if buffer > 0.0:
        trend_on = hysteresis_state(close, moving_average, buffer)
    else:
        trend_on = close > moving_average
    slope_sessions = int(params.get("slope_sessions", 0))
    if slope_sessions > 0:
        trend_on &= moving_average > moving_average.shift(slope_sessions)
    realized_volatility = (
        close.pct_change().rolling(vol_period, min_periods=vol_period).std(ddof=1)
        * math.sqrt(TRADING_DAYS)
    )
    raw = (target_vol / realized_volatility.replace(0.0, np.nan)).clip(
        lower=0.0,
        upper=TARGET_WEIGHT,
    )
    target = raw.where(trend_on, 0.0).fillna(0.0)
    smooth_span = int(params.get("smooth_span", 0))
    if smooth_span > 1:
        target = target.ewm(span=smooth_span, adjust=False).mean()
    target = apply_update_schedule(target, int(params.get("schedule_sessions", 1)))
    target = apply_rebalance_threshold(target, float(params.get("rebalance_threshold", 0.0)))
    return target.clip(lower=0.0, upper=TARGET_WEIGHT)


def _engine_config(family: str, name: str, params: dict):
    return engine.StrategyConfig(
        family=family,
        name=name,
        params=params,
        canonical=False,
    )


def _macd_gate(frame: pd.DataFrame) -> pd.Series:
    config = _engine_config(
        "macd-cross",
        "production-macd",
        {"fast": 12, "slow": 26, "signal": 9},
    )
    return engine.generate_target(frame, config).div(TARGET_WEIGHT).clip(0.0, 1.0)


def _keltner_gate(frame: pd.DataFrame, multiplier: float = 2.0) -> pd.Series:
    config = _engine_config(
        "keltner-breakout",
        "production-keltner",
        {"period": 20, "multiplier": multiplier},
    )
    return engine.generate_target(frame, config).div(TARGET_WEIGHT).clip(0.0, 1.0)


def _fixed_ensemble_target(frame: pd.DataFrame) -> pd.Series:
    core = _risk_core_target(frame, _canonical_core_params())
    macd = core * (0.25 + 0.75 * _macd_gate(frame))
    keltner = core * (0.25 + 0.75 * _keltner_gate(frame, 2.0))
    return pd.concat([core, macd, keltner], axis=1).mean(axis=1)


def generate_production_target(
    frame: pd.DataFrame,
    config: ProductionConfig,
) -> pd.Series:
    params = config.params
    kind = params["kind"]
    if kind == "risk-core":
        target = _risk_core_target(frame, params)
    elif kind == "macd-overlay":
        core = _risk_core_target(frame, _canonical_core_params())
        floor = float(params["floor"])
        target = core * (floor + (1.0 - floor) * _macd_gate(frame))
    elif kind == "keltner-overlay":
        core = _risk_core_target(frame, _canonical_core_params())
        floor = float(params["floor"])
        gate = _keltner_gate(frame, float(params["multiplier"]))
        target = core * (floor + (1.0 - floor) * gate)
    elif kind == "fixed-ensemble":
        target = _fixed_ensemble_target(frame)
        target = apply_rebalance_threshold(
            target,
            float(params.get("rebalance_threshold", 0.0)),
        )
    elif kind == "volatility-shock":
        target = _risk_core_target(frame, _canonical_core_params())
        realized = (
            frame["close"].pct_change().rolling(20).std(ddof=1) * math.sqrt(TRADING_DAYS)
        )
        target = target * pd.Series(np.where(realized > 0.60, 0.5, 1.0), index=frame.index)
    elif kind == "drawdown-guard":
        target = _risk_core_target(frame, _canonical_core_params())
        drawdown = frame["close"] / frame["close"].rolling(63).max() - 1.0
        target = target * pd.Series(np.where(drawdown < -0.12, 0.5, 1.0), index=frame.index)
    else:
        raise ValueError(f"未知实盘扩展类型：{kind}")
    return target.astype(float).clip(0.0, TARGET_WEIGHT).fillna(0.0).rename(config.name)


def pareto_front(metrics: pd.DataFrame) -> pd.DataFrame:
    required = {
        "annualized_return",
        "maximum_drawdown",
        "sharpe",
        "turnover",
    }
    if missing := required.difference(metrics.columns):
        raise ValueError(f"Pareto指标缺失：{sorted(missing)}")
    keep = []
    for index, row in metrics.iterrows():
        dominated = False
        for other_index, other in metrics.iterrows():
            if index == other_index:
                continue
            no_worse = (
                other["annualized_return"] >= row["annualized_return"]
                and other["maximum_drawdown"] <= row["maximum_drawdown"]
                and other["sharpe"] >= row["sharpe"]
                and other["turnover"] <= row["turnover"]
            )
            strictly_better = (
                other["annualized_return"] > row["annualized_return"]
                or other["maximum_drawdown"] < row["maximum_drawdown"]
                or other["sharpe"] > row["sharpe"]
                or other["turnover"] < row["turnover"]
            )
            if no_worse and strictly_better:
                dominated = True
                break
        keep.append(not dominated)
    return metrics.loc[keep].copy()


def evaluate_objective_gate(
    objective: str,
    metrics: dict,
    benchmark: dict,
) -> dict:
    common = {
        "quarters": metrics["positive_fold_ratio"] >= 0.55
        and metrics["worst_fold_return"] >= -0.20,
        "delay": metrics["second_next_open_annualized"] > 0.0,
    }
    if objective == "risk":
        checks = {
            "return": metrics["annualized_return"] >= 0.50 * benchmark["annualized_return"],
            "drawdown": metrics["maximum_drawdown"] <= 0.70 * benchmark["maximum_drawdown"],
            "sharpe": metrics["sharpe"] >= benchmark["sharpe"] + 0.25,
            "calmar": metrics["calmar"] >= 1.0,
            "cost": metrics["slippage_20bp_annualized"] > 0.0,
            "turnover": metrics["turnover"] <= 15.0,
            **common,
        }
    elif objective == "return":
        checks = {
            "return": metrics["annualized_return"] >= benchmark["annualized_return"] + 0.03,
            "drawdown": metrics["maximum_drawdown"] <= benchmark["maximum_drawdown"],
            "sharpe": metrics["sharpe"] >= benchmark["sharpe"],
            "cost": metrics["slippage_20bp_annualized"]
            >= benchmark["annualized_return"],
            "turnover": metrics["turnover"] <= 30.0,
            **common,
        }
    elif objective == "balanced":
        checks = {
            "return": metrics["annualized_return"] >= 0.70 * benchmark["annualized_return"],
            "drawdown": metrics["maximum_drawdown"] <= 0.70 * benchmark["maximum_drawdown"],
            "sharpe": metrics["sharpe"] >= benchmark["sharpe"] + 0.25,
            "cost": metrics["slippage_20bp_annualized"] > 0.0,
            "turnover": metrics["turnover"] <= 20.0,
            **common,
        }
    else:
        raise ValueError(f"未知实盘目标：{objective}")
    return {**checks, "candidate": all(checks.values())}


def _return_series(result, dates: pd.DatetimeIndex) -> pd.Series:
    equity = result.equity.copy()
    equity["trade_date"] = pd.to_datetime(equity["trade_date"])
    return (
        equity.set_index("trade_date")["daily_return"]
        .astype(float)
        .reindex(dates)
        .fillna(0.0)
    )


def _quarter_slices(dates: pd.DatetimeIndex) -> list[tuple[int, pd.DatetimeIndex]]:
    slices = []
    position = 0
    fold = 1
    while position < len(dates):
        remaining = len(dates) - position
        if remaining < MINIMUM_FINAL_TEST_SESSIONS:
            break
        end = min(len(dates), position + TEST_SESSIONS)
        slices.append((fold, dates[position:end]))
        position = end
        fold += 1
    return slices


def _numpy_metrics(values: np.ndarray) -> tuple[float, float, float]:
    returns = np.asarray(values, dtype=float)
    mean = float(np.mean(returns))
    standard_deviation = float(np.std(returns, ddof=1))
    sharpe = mean / standard_deviation * math.sqrt(TRADING_DAYS) if standard_deviation > 0 else 0.0
    curve = np.cumprod(1.0 + returns)
    annualized = float(curve[-1] ** (TRADING_DAYS / len(returns)) - 1.0)
    full_curve = np.r_[1.0, curve]
    drawdown = full_curve / np.maximum.accumulate(full_curve) - 1.0
    return annualized, float(-np.min(drawdown)), sharpe


def paired_metric_bootstrap(
    strategy_returns: pd.Series,
    benchmark_returns: pd.Series,
    block_length: int,
    repetitions: int,
    seed: int,
) -> dict:
    aligned = pd.concat(
        [strategy_returns.rename("strategy"), benchmark_returns.rename("benchmark")],
        axis=1,
    ).dropna()
    strategy = aligned["strategy"].to_numpy(dtype=float)
    benchmark = aligned["benchmark"].to_numpy(dtype=float)
    annualized_differences = []
    drawdown_differences = []
    sharpe_differences = []
    for indices in engine._moving_block_indices(
        len(aligned),
        block_length,
        repetitions,
        seed,
    ):
        strategy_metrics = _numpy_metrics(strategy[indices])
        benchmark_metrics = _numpy_metrics(benchmark[indices])
        annualized_differences.append(strategy_metrics[0] - benchmark_metrics[0])
        drawdown_differences.append(strategy_metrics[1] - benchmark_metrics[1])
        sharpe_differences.append(strategy_metrics[2] - benchmark_metrics[2])
    annualized_array = np.asarray(annualized_differences)
    drawdown_array = np.asarray(drawdown_differences)
    sharpe_array = np.asarray(sharpe_differences)
    return {
        "block_length": block_length,
        "repetitions": repetitions,
        "annualized_difference_ci_low": float(np.quantile(annualized_array, 0.025)),
        "annualized_difference_ci_high": float(np.quantile(annualized_array, 0.975)),
        "probability_return_above_benchmark": float(np.mean(annualized_array > 0.0)),
        "probability_drawdown_below_benchmark": float(np.mean(drawdown_array < 0.0)),
        "probability_sharpe_above_benchmark": float(np.mean(sharpe_array > 0.0)),
    }


def run_live_extension(frame: pd.DataFrame, bootstrap_repetitions: int = 1000) -> dict:
    minimum = WARMUP_SESSIONS + INITIAL_TRAIN_SESSIONS + MINIMUM_FINAL_TEST_SESSIONS
    if len(frame) < minimum:
        raise ValueError("历史不足以执行实盘扩展研究")
    configs = build_production_configs()
    oos_start = pd.Timestamp(frame.index[WARMUP_SESSIONS + INITIAL_TRAIN_SESSIONS])
    oos_dates = pd.DatetimeIndex(frame.index[frame.index >= oos_start])
    years = len(oos_dates) / TRADING_DAYS
    targets = {}
    results = {}
    metric_rows = []
    for position, config in enumerate(configs, start=1):
        print(f"[G0-G3 {position}/{len(configs)}] {config.name}", flush=True)
        target = generate_production_target(frame, config)
        result = engine.simulate_target(config.name, frame, target, oos_start)
        targets[config.name] = target
        results[config.name] = result
        metrics = result.metrics.copy()
        total_turnover = float(metrics["turnover"])
        metrics["total_turnover"] = total_turnover
        metrics["turnover"] = total_turnover / years
        returns = _return_series(result, oos_dates)
        positive_returns = returns[returns > 0.0]
        top_five_share = (
            float(positive_returns.nlargest(5).sum() / positive_returns.sum())
            if positive_returns.sum() > 0.0
            else np.nan
        )
        metric_rows.append(
            {
                "generation": config.generation,
                "config": config.name,
                "archetype": config.archetype,
                "objective": config.objective,
                "params": json.dumps(config.params, ensure_ascii=False, sort_keys=True),
                "top_five_positive_day_share": top_five_share,
                **metrics,
            }
        )
    metrics = pd.DataFrame(metric_rows)

    buy_hold_target = pd.Series(TARGET_WEIGHT, index=frame.index, name="buy-hold")
    buy_hold = engine.simulate_target("buy-hold", frame, buy_hold_target, oos_start)
    benchmark = buy_hold.metrics.copy()
    benchmark["total_turnover"] = float(benchmark["turnover"])
    benchmark["turnover"] = benchmark["total_turnover"] / years
    buy_hold_returns = _return_series(buy_hold, oos_dates)

    print("[验证] 固定季度与执行压力", flush=True)
    fold_rows = []
    quarter_slices = _quarter_slices(oos_dates)
    for config in configs:
        returns = _return_series(results[config.name], oos_dates)
        for fold, dates in quarter_slices:
            fold_rows.append(
                {
                    "generation": config.generation,
                    "config": config.name,
                    "fold": fold,
                    "test_start": dates.min(),
                    "test_end": dates.max(),
                    **engine._metrics_from_returns(returns.reindex(dates)),
                }
            )
    fold_metrics = pd.DataFrame(fold_rows)
    fold_summary = (
        fold_metrics.groupby("config")
        .agg(
            positive_fold_ratio=("total_return", lambda value: float(value.gt(0.0).mean())),
            worst_fold_return=("total_return", "min"),
            median_fold_return=("total_return", "median"),
        )
        .reset_index()
    )
    metrics = metrics.merge(fold_summary, on="config", how="left", validate="one_to_one")

    robustness_rows = []
    robustness_results = {}
    cases = (
        ("base", BASE_SLIPPAGE, 1, "open"),
        ("slippage-10bp", 0.0010, 1, "open"),
        ("slippage-20bp", 0.0020, 1, "open"),
        ("next-close", BASE_SLIPPAGE, 1, "close"),
        ("second-next-open", BASE_SLIPPAGE, 2, "open"),
    )
    for config in configs:
        for case, slippage, delay, execution in cases:
            if case == "base":
                result = results[config.name]
            else:
                result = engine.simulate_target(
                    f"{case}__{config.name}",
                    frame,
                    targets[config.name],
                    oos_start,
                    slippage=slippage,
                    delay=delay,
                    execution=execution,
                )
            robustness_results[(config.name, case)] = result
            robustness_rows.append(
                {
                    "generation": config.generation,
                    "config": config.name,
                    "case": case,
                    **result.metrics,
                }
            )
    robustness = pd.DataFrame(robustness_rows)
    robustness_pivot = robustness.pivot(
        index="config",
        columns="case",
        values="annualized_return",
    )
    metrics = metrics.merge(
        robustness_pivot[
            ["slippage-10bp", "slippage-20bp", "next-close", "second-next-open"]
        ].rename(
            columns={
                "slippage-10bp": "slippage_10bp_annualized",
                "slippage-20bp": "slippage_20bp_annualized",
                "next-close": "next_close_annualized",
                "second-next-open": "second_next_open_annualized",
            }
        ),
        left_on="config",
        right_index=True,
        how="left",
        validate="one_to_one",
    )

    gate_rows = []
    for row in metrics.to_dict(orient="records"):
        gate_rows.append(
            {
                "generation": row["generation"],
                "config": row["config"],
                "objective": row["objective"],
                **evaluate_objective_gate(row["objective"], row, benchmark),
            }
        )
    gates = pd.DataFrame(gate_rows)
    metrics = metrics.merge(
        gates[["config", "candidate"]],
        on="config",
        how="left",
        validate="one_to_one",
    )
    frontier = pareto_front(metrics)
    metrics["pareto"] = metrics["config"].isin(frontier["config"])

    print("[验证] 区块 bootstrap、DSR 与 Reality Check", flush=True)
    returns_frame = pd.DataFrame(
        {
            config.name: _return_series(results[config.name], oos_dates)
            for config in configs
        },
        index=oos_dates,
    )
    bootstrap_rows = []
    for position, config in enumerate(configs):
        for block_length in (20, 60):
            bootstrap_rows.append(
                {
                    "generation": config.generation,
                    "config": config.name,
                    **paired_metric_bootstrap(
                        returns_frame[config.name],
                        buy_hold_returns,
                        block_length,
                        bootstrap_repetitions,
                        20260902 + position * 10 + block_length,
                    ),
                }
            )
    bootstrap = pd.DataFrame(bootstrap_rows)
    matrix = returns_frame.to_numpy(dtype=float).T
    dsr_rows = []
    for index, config in enumerate(configs):
        dsr_rows.append(
            {
                "generation": config.generation,
                "config": config.name,
                **engine.deflated_sharpe_probability(matrix[index], matrix),
            }
        )
    dsr = pd.DataFrame(dsr_rows)
    excess = returns_frame.sub(buy_hold_returns, axis=0)
    reality_checks = {
        "block_20": engine.white_reality_check(excess, 20, 2000, 20260902),
        "block_60": engine.white_reality_check(excess, 60, 2000, 20260962),
    }

    print("[诊断] 市场状态、代际增量与当前目标", flush=True)
    regimes = engine._regime_labels(frame).reindex(oos_dates)
    regime_rows = []
    sources = {"buy-hold": buy_hold_returns, **{
        config.name: returns_frame[config.name] for config in configs
    }}
    for name, returns in sources.items():
        for dimension in ("trend_regime", "volatility_regime"):
            for regime, indices in regimes.groupby(dimension).groups.items():
                selected = returns.reindex(indices).dropna()
                if selected.empty:
                    continue
                regime_rows.append(
                    {
                        "model": name,
                        "dimension": dimension,
                        "regime": regime,
                        **engine._metrics_from_returns(selected),
                    }
                )
    regime_metrics = pd.DataFrame(regime_rows)
    generation_summary = (
        metrics.groupby("generation")
        .agg(
            config_count=("config", "size"),
            candidate_count=("candidate", "sum"),
            best_annualized_return=("annualized_return", "max"),
            best_sharpe=("sharpe", "max"),
            lowest_maximum_drawdown=("maximum_drawdown", "min"),
            median_annualized_return=("annualized_return", "median"),
            median_turnover=("turnover", "median"),
        )
        .reset_index()
    )
    current_signals = pd.DataFrame(
        [
            {
                "generation": config.generation,
                "config": config.name,
                "objective": config.objective,
                "observation_date": frame.index.max(),
                "next_session_target_weight": float(targets[config.name].iloc[-1]),
                "last_target_change": targets[config.name].index[
                    targets[config.name].ne(targets[config.name].shift(1))
                ].max(),
            }
            for config in configs
        ]
    )
    finalists = metrics[metrics["candidate"] & metrics["pareto"]].copy()
    bootstrap_primary = bootstrap[bootstrap["block_length"].eq(20)][
        [
            "config",
            "probability_return_above_benchmark",
            "probability_drawdown_below_benchmark",
            "probability_sharpe_above_benchmark",
        ]
    ]
    finalists = finalists.merge(bootstrap_primary, on="config", how="left")
    finalists = finalists.merge(
        dsr[["config", "deflated_sharpe_probability"]],
        on="config",
        how="left",
    )

    return {
        "configs": configs,
        "oos_start": oos_start,
        "oos_end": frame.index.max(),
        "targets": targets,
        "results": results,
        "metrics": metrics,
        "buy_hold": buy_hold,
        "benchmark_metrics": benchmark,
        "fold_metrics": fold_metrics,
        "robustness": robustness,
        "robustness_results": robustness_results,
        "gates": gates,
        "pareto": frontier,
        "bootstrap": bootstrap,
        "dsr": dsr,
        "reality_checks": reality_checks,
        "regime_metrics": regime_metrics,
        "generation_summary": generation_summary,
        "current_signals": current_signals,
        "finalists": finalists,
    }


def _percent(value) -> str:
    return "—" if value is None or not np.isfinite(value) else f"{value:.2%}"


def _number(value) -> str:
    return "—" if value is None or not np.isfinite(value) else f"{value:.2f}"


def choose_shadow_specs(bundle: dict) -> pd.DataFrame:
    finalists = bundle["finalists"].copy()
    selected = []
    for objective in ("risk", "return", "balanced"):
        rows = finalists[finalists["objective"].eq(objective)]
        if rows.empty:
            continue
        if objective == "return":
            rows = rows.sort_values(
                ["annualized_return", "sharpe", "maximum_drawdown"],
                ascending=[False, False, True],
            )
        else:
            rows = rows.sort_values(
                ["sharpe", "maximum_drawdown", "annualized_return"],
                ascending=[False, True, False],
            )
        selected.append(rows.iloc[0])
    return pd.DataFrame(selected).reset_index(drop=True) if selected else pd.DataFrame()


def build_report(bundle: dict, frame: pd.DataFrame) -> str:
    metrics = bundle["metrics"].copy()
    gates = bundle["gates"]
    finalists = bundle["finalists"].copy()
    shadow_specs = choose_shadow_specs(bundle)
    benchmark = bundle["benchmark_metrics"]
    reality = bundle["reality_checks"]
    lines = [
        "# 科创 50 ETF G0-G3 实盘化扩展研究",
        "",
        "## 结论",
        "",
        f"输入固定为 {frame.index.min().date()} 至 {frame.index.max().date()} 的 {len(frame):,} 个"
        f"真实交易日；历史模拟检验为 {bundle['oos_start'].date()} 至 {bundle['oos_end'].date()}。",
        "这段历史已被首轮研究看过，因此全部结果只是事后开发证据，不是真正未见样本。",
        f"38 个预注册配置中有 {int(gates['candidate'].sum())} 个通过各自的工程门槛，"
        f"其中 {len(finalists)} 个同时位于四维 Pareto 前沿。",
        f"同期买入持有年化 {_percent(benchmark['annualized_return'])}、最大回撤 "
        f"{_percent(benchmark['maximum_drawdown'])}、Sharpe {_number(benchmark['sharpe'])}。",
        f"全体配置对买入持有的 White Reality Check：20日块 p="
        f"{reality['block_20']['p_value']:.4f}，60日块 p="
        f"{reality['block_60']['p_value']:.4f}。",
        "无论工程门槛是否通过，本轮结束后停止在同一历史上新增规则；通过者只进入冻结的影子运行。",
        "",
        "## 代际结果",
        "",
        "| 代际 | 配置数 | 工程候选 | 最好年化 | 最好Sharpe | 最低回撤 | 中位年化 | 中位年换手 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in bundle["generation_summary"].itertuples(index=False):
        lines.append(
            f"| {row.generation} | {int(row.config_count)} | {int(row.candidate_count)} | "
            f"{_percent(row.best_annualized_return)} | {_number(row.best_sharpe)} | "
            f"{_percent(row.lowest_maximum_drawdown)} | {_percent(row.median_annualized_return)} | "
            f"{_number(row.median_turnover)} |"
        )

    lines.extend(
        [
            "",
            "## 全部配置排序",
            "",
            "| 配置 | 目标 | 年化 | 回撤 | Sharpe | Calmar | 年换手 | 正收益季度 | 20bp年化 | 延迟年化 | 门槛 | Pareto |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in metrics.sort_values(
        ["candidate", "sharpe", "annualized_return"],
        ascending=[False, False, False],
    ).itertuples(index=False):
        lines.append(
            f"| `{row.config}` | {row.objective} | {_percent(row.annualized_return)} | "
            f"{_percent(row.maximum_drawdown)} | {_number(row.sharpe)} | {_number(row.calmar)} | "
            f"{_number(row.turnover)} | {_percent(row.positive_fold_ratio)} | "
            f"{_percent(row.slippage_20bp_annualized)} | "
            f"{_percent(row.second_next_open_annualized)} | "
            f"{'通过' if row.candidate else '失败'} | {'是' if row.pareto else '否'} |"
        )

    lines.extend(
        [
            "",
            "## 影子运行冻结规格",
            "",
        ]
    )
    if shadow_specs.empty:
        lines.append("没有配置同时通过工程门槛并进入 Pareto 前沿，本轮不生成影子运行规格。")
    else:
        lines.extend(
            [
                "以下规格是按预注册目标从工程候选中机械选择，不代表统计显著或可以直接满额实盘。",
                "",
                "| 目标 | 配置 | 年化 | 回撤 | Sharpe | 20日块收益胜率 | 回撤改善概率 | DSR概率 | 下一目标 |",
                "|---|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        current = bundle["current_signals"].set_index("config")
        for row in shadow_specs.itertuples(index=False):
            lines.append(
                f"| {row.objective} | `{row.config}` | {_percent(row.annualized_return)} | "
                f"{_percent(row.maximum_drawdown)} | {_number(row.sharpe)} | "
                f"{_percent(row.probability_return_above_benchmark)} | "
                f"{_percent(row.probability_drawdown_below_benchmark)} | "
                f"{_percent(row.deflated_sharpe_probability)} | "
                f"{_percent(current.loc[row.config, 'next_session_target_weight'])} |"
            )

    lines.extend(
        [
            "",
            "## 门槛失败诊断",
            "",
            "下表统计每个目标中最常见的失败项。它用于决定停止什么，而不是据此继续修改同一历史。",
            "",
            "| 目标 | 配置数 | 收益失败 | 回撤失败 | Sharpe失败 | 成本失败 | 换手失败 | 季度失败 | 延迟失败 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for objective, rows in gates.groupby("objective"):
        lines.append(
            f"| {objective} | {len(rows)} | {int((~rows['return']).sum())} | "
            f"{int((~rows['drawdown']).sum())} | {int((~rows['sharpe']).sum())} | "
            f"{int((~rows['cost']).sum())} | {int((~rows['turnover']).sum())} | "
            f"{int((~rows['quarters']).sum())} | {int((~rows['delay']).sum())} |"
        )

    lines.extend(
        [
            "",
            "## 实盘治理边界",
            "",
            "- 影子运行至少先验证三个月的数据、信号、下单、成交和对账，期间不以收益决定改规则。",
            "- 真实统计晋级需要冻结规则后的8个新季度；在此之前只能称历史开发候选。",
            "- 每日监控双源价格差异、目标与实际仓位、拒单、成交量占比、滑点、换手和模型净值偏差。",
            "- 数据缺失、持仓无法对账、订单状态未知或实际滑点持续超过压力假设时停止新增仓位。",
            "- G0-G3失败配置全部保留；下一轮若使用新信息，必须另建协议，不能回写本轮。",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, encoding="utf-8")


def _write_json(value, path: Path) -> None:
    path.write_text(
        json.dumps(engine._json_safe(value), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def archive_result(
    bundle: dict,
    frame: pd.DataFrame,
    archived_at: str,
    run_id: str,
) -> Path:
    target = STUDY_DIR / "results" / f"{archived_at}__live-extension-g0-g3__{run_id}"
    if target.exists():
        raise FileExistsError(f"结果目录已存在，拒绝覆盖：{target}")
    raw = target / "raw"
    raw.mkdir(parents=True)
    shutil.copy2(SOURCE_PATH, target / "source.py")
    shutil.copy2(ENGINE_PATH, target / "engine.py")
    _write_csv(frame.reset_index(), raw / "input-sh588000.csv")
    registry = pd.DataFrame(
        [
            {
                "generation": config.generation,
                "config": config.name,
                "archetype": config.archetype,
                "objective": config.objective,
                "params": json.dumps(config.params, ensure_ascii=False, sort_keys=True),
            }
            for config in bundle["configs"]
        ]
    )
    _write_csv(registry, raw / "config-registry.csv")
    _write_csv(bundle["metrics"], raw / "all-config-metrics.csv")
    _write_csv(bundle["fold_metrics"], raw / "quarter-metrics.csv")
    _write_csv(bundle["robustness"], raw / "execution-robustness.csv")
    _write_csv(bundle["gates"], raw / "objective-gates.csv")
    _write_csv(bundle["pareto"], raw / "pareto-front.csv")
    _write_csv(bundle["bootstrap"], raw / "paired-block-bootstrap.csv")
    _write_csv(bundle["dsr"], raw / "deflated-sharpe.csv")
    _write_json(bundle["reality_checks"], raw / "white-reality-check.json")
    _write_csv(bundle["regime_metrics"], raw / "regime-metrics.csv")
    _write_csv(bundle["generation_summary"], raw / "generation-summary.csv")
    _write_csv(bundle["current_signals"], raw / "current-signals.csv")
    _write_csv(bundle["finalists"], raw / "engineering-finalists.csv")
    shadow_specs = choose_shadow_specs(bundle)
    _write_csv(shadow_specs, raw / "frozen-shadow-specs.csv")

    all_equity = [bundle["buy_hold"].equity.assign(config="buy-hold")]
    all_trades = []
    all_decisions = []
    for config in bundle["configs"]:
        result = bundle["results"][config.name]
        all_equity.append(result.equity.assign(config=config.name))
        if not result.trades.empty:
            all_trades.append(result.trades.assign(config=config.name))
        if not result.decisions.empty:
            all_decisions.append(result.decisions.assign(config=config.name))
    _write_csv(pd.concat(all_equity, ignore_index=True), raw / "all-config-equity.csv")
    _write_csv(pd.concat(all_trades, ignore_index=True), raw / "all-config-trades.csv")
    _write_csv(pd.concat(all_decisions, ignore_index=True), raw / "all-config-decisions.csv")
    (target / "report.md").write_text(build_report(bundle, frame), encoding="utf-8")

    artifacts = {}
    for path in sorted(target.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            artifacts[path.relative_to(target).as_posix()] = {
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
            }
    manifest = {
        "schema_version": 2,
        "study_id": "star50-single-asset-timing-live-extension",
        "archived_at": archived_at,
        "run_id": run_id,
        "symbol": engine.SYMBOL,
        "evidence_class": "post-selection historical development; not untouched OOS",
        "data": {
            "input_file": "raw/input-sh588000.csv",
            "input_sha256": artifacts["raw/input-sh588000.csv"]["sha256"],
            "start": frame.index.min(),
            "end": frame.index.max(),
            "sessions": len(frame),
            "source_phase1_archive": PHASE1_RESULT.relative_to(ROOT).as_posix(),
        },
        "protocol": {
            "generations": ["G0", "G1", "G2", "G3"],
            "config_count": len(bundle["configs"]),
            "oos_start": bundle["oos_start"],
            "oos_end": bundle["oos_end"],
            "future_confirmation_quarters": 8,
            "historical_stop_rule": "no new rules after G3 results",
        },
        "benchmark_metrics": bundle["benchmark_metrics"],
        "white_reality_check": bundle["reality_checks"],
        "engineering_candidate_count": int(bundle["gates"]["candidate"].sum()),
        "pareto_candidate_count": len(bundle["finalists"]),
        "shadow_specs": choose_shadow_specs(bundle)["config"].tolist()
        if not choose_shadow_specs(bundle).empty
        else [],
        "source_file": "source.py",
        "source_sha256": _sha256(target / "source.py"),
        "engine_file": "engine.py",
        "engine_sha256": _sha256(target / "engine.py"),
        "artifacts": artifacts,
    }
    _write_json(manifest, target / "manifest.json")
    return target


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--bootstrap-repetitions", type=int, default=1000)
    parser.add_argument("--archived-at", default=None)
    parser.add_argument("--run-id", default="tencent-yahoo-2020-2026-v1")
    parser.add_argument("--no-archive", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    frame = engine.load_input_csv(args.input_csv)
    bundle = run_live_extension(frame, bootstrap_repetitions=args.bootstrap_repetitions)
    columns = [
        "generation",
        "config",
        "objective",
        "annualized_return",
        "maximum_drawdown",
        "sharpe",
        "turnover",
        "candidate",
        "pareto",
    ]
    print(
        bundle["metrics"][columns]
        .sort_values(["candidate", "sharpe"], ascending=[False, False])
        .to_string(index=False)
    )
    if not args.no_archive:
        archived_at = args.archived_at or pd.Timestamp.today().date().isoformat()
        target = archive_result(bundle, frame, archived_at, args.run_id)
        print(f"归档完成：{target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
