"""检验科创 50 ETF 冻结择时候选与买入持有的启动日起点敏感性。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd


SOURCE_PATH = Path(__file__).resolve()
LOCAL_MODEL = SOURCE_PATH.with_name("model.py")
MODEL_PATH = LOCAL_MODEL if LOCAL_MODEL.exists() else SOURCE_PATH.with_name("run_live_extension.py")
LOCAL_PROTOCOL = SOURCE_PATH.with_name("protocol.md")
PROTOCOL_PATH = (
    LOCAL_PROTOCOL
    if LOCAL_PROTOCOL.exists()
    else SOURCE_PATH.with_name("START_DATE_ROBUSTNESS.md")
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载研究模块：{path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


model = _load_module("star50_live_extension_for_start_dates", MODEL_PATH)
engine = model.engine
ROOT = engine.ROOT
STUDY_DIR = ROOT / "studies" / "star50-single-asset-timing"
PHASE1_RESULT = (
    STUDY_DIR
    / "results"
    / "2026-09-01__walk-forward-technical-families__tencent-yahoo-2020-2026-v1"
)
PHASE2_RESULT = (
    STUDY_DIR
    / "results"
    / "2026-09-02__live-extension-g0-g3__tencent-yahoo-2020-2026-v1"
)
DEFAULT_INPUT = PHASE1_RESULT / "raw" / "input-sh588000.csv"
HORIZONS = (63, 126, 252, 504)
PRIMARY_HORIZONS = (252, 504)
FROZEN_MODELS = (
    "risk-friction__threshold-0p05",
    "production-ensemble__threshold-0p1",
)
MODEL_LABELS = {
    "buy-hold": "买入持有",
    "risk-friction__threshold-0p05": "风险型",
    "production-ensemble__threshold-0p1": "平衡型",
}
OBJECTIVES = {
    "risk-friction__threshold-0p05": ("risk", 0.50),
    "production-ensemble__threshold-0p1": ("balanced", 0.70),
}
ORIGINAL_EVALUATION_START = pd.Timestamp("2023-12-25")
SEVERE_TERMINAL_LOSS = -0.20
SEVERE_MAXIMUM_DRAWDOWN = 0.25


def frozen_configs():
    registry = {config.name: config for config in model.build_production_configs()}
    missing = set(FROZEN_MODELS).difference(registry)
    if missing:
        raise ValueError(f"冻结候选定义缺失：{sorted(missing)}")
    return [registry[name] for name in FROZEN_MODELS]


def build_start_windows(
    frame: pd.DataFrame,
    warmup_sessions: int = engine.WARMUP_SESSIONS,
    horizons: tuple[int, ...] = HORIZONS,
) -> pd.DataFrame:
    dates = pd.DatetimeIndex(frame.index)
    if not dates.is_monotonic_increasing or dates.has_duplicates:
        raise ValueError("行情日期必须严格递增且不重复")
    if warmup_sessions < 1 or warmup_sessions >= len(dates):
        raise ValueError("预热长度超出行情范围")
    rows = []
    for horizon in horizons:
        if int(horizon) <= 1:
            raise ValueError("固定期限至少需要两个交易日")
        final_start_position = len(dates) - int(horizon)
        for start_position in range(warmup_sessions, final_start_position + 1):
            end_position = start_position + int(horizon) - 1
            rows.append(
                {
                    "horizon_sessions": int(horizon),
                    "start_position": start_position,
                    "start_date": dates[start_position],
                    "observation_date": dates[start_position - 1],
                    "end_date": dates[end_position],
                    "calendar_sessions": int(end_position - start_position + 1),
                }
            )
    if not rows:
        raise ValueError("没有满足完整固定期限的启动日")
    result = pd.DataFrame(rows)
    result["is_monthly_start"] = monthly_start_mask(result)
    return result


def monthly_start_mask(windows: pd.DataFrame) -> pd.Series:
    months = pd.to_datetime(windows["start_date"]).dt.to_period("M")
    first = windows.groupby(["horizon_sessions", months])["start_date"].transform("min")
    return pd.to_datetime(windows["start_date"]).eq(pd.to_datetime(first))


def _cached_simulation(
    name: str,
    frame: pd.DataFrame,
    desired_target: pd.Series,
    start_date,
    end_date,
    bars: pd.DataFrame,
    market_state: pd.DataFrame,
):
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    calendar = pd.DatetimeIndex(frame.index[(frame.index >= start) & (frame.index <= end)])
    if calendar.empty:
        raise ValueError("模拟区间为空")
    backtester = engine.DailyBacktester(
        bars=bars,
        market_state=market_state,
        asset_types={engine.SYMBOL: "etf"},
        config=engine.BacktestConfig(
            initial_cash=engine.INITIAL_CASH,
            maximum_volume_ratio=0.10,
            slippage_rate=engine.BASE_SLIPPAGE,
            minimum_state_quality="C",
        ),
        costs=engine.CostModel(
            etf_buy_commission=engine.BASE_COMMISSION,
            etf_sell_commission=engine.BASE_COMMISSION,
            etf_minimum_commission=5.0,
        ),
    )
    desired = desired_target.reindex(frame.index).ffill().fillna(0.0)
    last_weight = None

    def target_provider(_, trade_date):
        nonlocal last_weight
        weight = float(desired.loc[trade_date])
        if last_weight is None or not math.isclose(weight, last_weight, abs_tol=1e-12):
            last_weight = weight
            return {} if weight <= 0.0 else {engine.SYMBOL: weight}
        return None

    backtester.run(calendar, target_provider, frequency="daily", when="first", execution="open")
    equity = backtester.equity.copy()
    trades = backtester.trades.copy()
    metrics = engine.performance_metrics(equity, trades, trading_days=engine.TRADING_DAYS)
    metrics["calmar"] = (
        metrics["annualized_return"] / metrics["maximum_drawdown"]
        if metrics["maximum_drawdown"] > 0.0
        else np.nan
    )
    exposure = equity["positions_value"] / equity["total_value"].replace(0.0, np.nan)
    metrics["average_exposure"] = float(exposure.mean())
    metrics["invested_session_ratio"] = float(equity["positions_value"].gt(0.0).mean())
    metrics["filled_trade_count"] = int(len(trades))
    metrics["rejected_order_count"] = int(len(backtester.rejections))
    metrics["total_commission"] = (
        float(pd.to_numeric(trades["commission"], errors="coerce").fillna(0.0).sum())
        if not trades.empty
        else 0.0
    )
    return metrics, trades


def _result_row(
    model_name: str,
    window,
    metrics: dict,
    trades: pd.DataFrame,
    initial_target_weight: float,
    regimes: pd.DataFrame,
) -> dict:
    observation_date = pd.Timestamp(window.observation_date)
    first_trade = trades.iloc[0] if not trades.empty else None
    return {
        "model": model_name,
        "horizon_sessions": int(window.horizon_sessions),
        "start_date": pd.Timestamp(window.start_date),
        "observation_date": observation_date,
        "end_date": pd.Timestamp(window.end_date),
        "is_monthly_start": bool(window.is_monthly_start),
        "trend_regime": regimes.loc[observation_date, "trend_regime"],
        "volatility_regime": regimes.loc[observation_date, "volatility_regime"],
        "initial_target_weight": float(initial_target_weight),
        "total_return": float(metrics["total_return"]),
        "annualized_return": float(metrics["annualized_return"]),
        "maximum_drawdown": float(metrics["maximum_drawdown"]),
        "sharpe": float(metrics["sharpe"]) if np.isfinite(metrics["sharpe"]) else np.nan,
        "longest_underwater_trading_days": int(metrics["longest_underwater_trading_days"]),
        "average_exposure": float(metrics["average_exposure"]),
        "invested_session_ratio": float(metrics["invested_session_ratio"]),
        "filled_trade_count": int(metrics["filled_trade_count"]),
        "rejected_order_count": int(metrics["rejected_order_count"]),
        "total_commission": float(metrics["total_commission"]),
        "first_trade_date": (
            pd.Timestamp(first_trade["trade_date"]) if first_trade is not None else pd.NaT
        ),
        "first_trade_price": (
            float(first_trade["price"]) if first_trade is not None else np.nan
        ),
        "first_trade_shares": (
            int(first_trade["filled_shares"]) if first_trade is not None else 0
        ),
    }


def add_matched_benchmark_fields(results: pd.DataFrame) -> pd.DataFrame:
    keys = ["horizon_sessions", "start_date"]
    if results.duplicated(["model", *keys]).any():
        raise ValueError("模型、期限和启动日必须唯一")
    benchmark = results.loc[results["model"].eq("buy-hold"), [
        *keys,
        "total_return",
        "annualized_return",
        "maximum_drawdown",
        "sharpe",
    ]].rename(
        columns={
            "total_return": "benchmark_total_return",
            "annualized_return": "benchmark_annualized_return",
            "maximum_drawdown": "benchmark_maximum_drawdown",
            "sharpe": "benchmark_sharpe",
        }
    )
    merged = results.merge(benchmark, on=keys, how="left", validate="many_to_one")
    if merged["benchmark_total_return"].isna().any():
        raise ValueError("存在缺少同日起点买入持有基准的结果")
    merged["positive_return"] = merged["total_return"].gt(0.0)
    merged["severe_start"] = merged["total_return"].le(SEVERE_TERMINAL_LOSS) | merged[
        "maximum_drawdown"
    ].ge(SEVERE_MAXIMUM_DRAWDOWN)
    strategy = ~merged["model"].eq("buy-hold")
    merged["total_return_difference"] = np.where(
        strategy,
        merged["total_return"] - merged["benchmark_total_return"],
        np.nan,
    )
    merged["annualized_return_difference"] = np.where(
        strategy,
        merged["annualized_return"] - merged["benchmark_annualized_return"],
        np.nan,
    )
    merged["drawdown_difference"] = np.where(
        strategy,
        merged["maximum_drawdown"] - merged["benchmark_maximum_drawdown"],
        np.nan,
    )
    merged["sharpe_difference"] = np.where(
        strategy,
        merged["sharpe"] - merged["benchmark_sharpe"],
        np.nan,
    )
    merged["outperform_benchmark"] = pd.Series(np.nan, index=merged.index, dtype=object)
    merged["drawdown_improved"] = pd.Series(np.nan, index=merged.index, dtype=object)
    merged["sharpe_improved"] = pd.Series(np.nan, index=merged.index, dtype=object)
    merged.loc[strategy, "outperform_benchmark"] = merged.loc[
        strategy, "total_return_difference"
    ].gt(0.0)
    merged.loc[strategy, "drawdown_improved"] = merged.loc[
        strategy, "drawdown_difference"
    ].lt(0.0)
    valid_sharpe = strategy & merged["sharpe"].notna() & merged["benchmark_sharpe"].notna()
    merged.loc[valid_sharpe, "sharpe_improved"] = merged.loc[
        valid_sharpe, "sharpe_difference"
    ].gt(0.0)
    return merged.sort_values(["horizon_sessions", "start_date", "model"]).reset_index(drop=True)


def _rate(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return float(numeric.mean()) if not numeric.empty else np.nan


def summarize_start_results(results: pd.DataFrame, cohort: str) -> pd.DataFrame:
    if cohort not in {"daily", "monthly"}:
        raise ValueError("起点汇总只支持 daily 或 monthly")
    data = results.copy()
    if cohort == "monthly":
        mask = (
            data["is_monthly_start"].astype(bool)
            if "is_monthly_start" in data
            else monthly_start_mask(data)
        )
        data = data.loc[mask].copy()
    rows = []
    for (model_name, horizon), group in data.groupby(
        ["model", "horizon_sessions"], sort=False
    ):
        total_returns = pd.to_numeric(group["total_return"], errors="raise")
        annualized = pd.to_numeric(group["annualized_return"], errors="raise")
        drawdowns = pd.to_numeric(group["maximum_drawdown"], errors="raise")
        rows.append(
            {
                "cohort": cohort,
                "model": model_name,
                "horizon_sessions": int(horizon),
                "start_count": int(len(group)),
                "first_start": pd.Timestamp(group["start_date"].min()),
                "last_start": pd.Timestamp(group["start_date"].max()),
                "positive_return_rate": _rate(group["positive_return"]),
                "severe_start_rate": _rate(group["severe_start"]),
                "worst_total_return": float(total_returns.min()),
                "p10_total_return": float(total_returns.quantile(0.10)),
                "median_total_return": float(total_returns.median()),
                "best_total_return": float(total_returns.max()),
                "p10_annualized_return": float(annualized.quantile(0.10)),
                "median_annualized_return": float(annualized.median()),
                "median_maximum_drawdown": float(drawdowns.median()),
                "p90_maximum_drawdown": float(drawdowns.quantile(0.90)),
                "worst_maximum_drawdown": float(drawdowns.max()),
                "median_average_exposure": float(group["average_exposure"].median()),
                "median_filled_trade_count": float(group["filled_trade_count"].median()),
                "median_total_commission": float(group["total_commission"].median()),
                "outperform_benchmark_rate": _rate(group["outperform_benchmark"]),
                "drawdown_improvement_rate": _rate(group["drawdown_improved"]),
                "sharpe_improvement_rate": _rate(group["sharpe_improved"]),
                "median_total_return_difference": float(
                    pd.to_numeric(group["total_return_difference"], errors="coerce").median()
                ),
                "p10_total_return_difference": float(
                    pd.to_numeric(group["total_return_difference"], errors="coerce").quantile(0.10)
                ),
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["cohort", "horizon_sessions", "model"]
    ).reset_index(drop=True)


def evaluate_start_robustness_gates(summary: pd.DataFrame) -> pd.DataFrame:
    daily = summary.loc[summary["cohort"].eq("daily")].copy()
    rows = []
    for model_name, (objective, return_fraction) in OBJECTIVES.items():
        if not daily["model"].eq(model_name).any():
            continue
        row = {
            "model": model_name,
            "objective": objective,
            "required_benchmark_return_fraction": return_fraction,
        }
        risk_checks = []
        alpha_checks = []
        for horizon in PRIMARY_HORIZONS:
            candidate_rows = daily.loc[
                daily["model"].eq(model_name)
                & daily["horizon_sessions"].eq(horizon)
            ]
            benchmark_rows = daily.loc[
                daily["model"].eq("buy-hold")
                & daily["horizon_sessions"].eq(horizon)
            ]
            if len(candidate_rows) != 1 or len(benchmark_rows) != 1:
                raise ValueError(f"缺少 {model_name} 的 {horizon} 日主期限汇总")
            candidate = candidate_rows.iloc[0]
            benchmark = benchmark_rows.iloc[0]
            positive_floor = 0.60 if horizon == 252 else 0.70
            checks = {
                "severe": bool(candidate["severe_start_rate"] <= 0.10),
                "drawdown": bool(candidate["drawdown_improvement_rate"] >= 0.75),
                "sharpe": bool(candidate["sharpe_improvement_rate"] >= 0.60),
                "positive": bool(candidate["positive_return_rate"] >= positive_floor),
                "return_adequacy": bool(
                    candidate["median_annualized_return"]
                    >= return_fraction * benchmark["median_annualized_return"]
                ),
            }
            for name, passed in checks.items():
                row[f"h{horizon}_{name}"] = passed
            alpha = bool(
                candidate["outperform_benchmark_rate"] >= 0.60
                and candidate["median_total_return_difference"] > 0.0
            )
            row[f"h{horizon}_return_timing"] = alpha
            risk_checks.extend(checks.values())
            alpha_checks.append(alpha)
        row["risk_robust"] = bool(all(risk_checks))
        row["return_timing_robust"] = bool(all(alpha_checks))
        rows.append(row)
    if not rows:
        raise ValueError("没有可评价的冻结候选")
    return pd.DataFrame(rows)


def summarize_by_regime(results: pd.DataFrame) -> pd.DataFrame:
    strategies = results.loc[~results["model"].eq("buy-hold")].copy()
    rows = []
    for keys, group in strategies.groupby(
        ["model", "horizon_sessions", "trend_regime", "volatility_regime"],
        dropna=False,
    ):
        model_name, horizon, trend, volatility = keys
        rows.append(
            {
                "model": model_name,
                "horizon_sessions": int(horizon),
                "trend_regime": trend,
                "volatility_regime": volatility,
                "start_count": int(len(group)),
                "positive_return_rate": _rate(group["positive_return"]),
                "severe_start_rate": _rate(group["severe_start"]),
                "median_total_return": float(group["total_return"].median()),
                "median_maximum_drawdown": float(group["maximum_drawdown"].median()),
                "outperform_benchmark_rate": _rate(group["outperform_benchmark"]),
                "drawdown_improvement_rate": _rate(group["drawdown_improved"]),
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["horizon_sessions", "model", "trend_regime", "volatility_regime"]
    ).reset_index(drop=True)


def run_anchor_comparison(
    frame: pd.DataFrame,
    desired_targets: dict[str, pd.Series],
    bars: pd.DataFrame,
    market_state: pd.DataFrame,
) -> pd.DataFrame:
    if ORIGINAL_EVALUATION_START not in frame.index:
        raise ValueError("原始评价起点不在行情中")
    rows = []
    for model_name, desired in desired_targets.items():
        metrics, trades = _cached_simulation(
            model_name,
            frame,
            desired,
            ORIGINAL_EVALUATION_START,
            frame.index.max(),
            bars,
            market_state,
        )
        first_trade = trades.iloc[0] if not trades.empty else None
        rows.append(
            {
                "model": model_name,
                "start_date": ORIGINAL_EVALUATION_START,
                "end_date": frame.index.max(),
                "calendar_sessions": int((frame.index >= ORIGINAL_EVALUATION_START).sum()),
                "total_return": metrics["total_return"],
                "annualized_return": metrics["annualized_return"],
                "maximum_drawdown": metrics["maximum_drawdown"],
                "sharpe": metrics["sharpe"],
                "average_exposure": metrics["average_exposure"],
                "filled_trade_count": metrics["filled_trade_count"],
                "total_commission": metrics["total_commission"],
                "first_trade_date": (
                    pd.Timestamp(first_trade["trade_date"]) if first_trade is not None else pd.NaT
                ),
                "first_trade_price": (
                    float(first_trade["price"]) if first_trade is not None else np.nan
                ),
                "first_trade_shares": (
                    int(first_trade["filled_shares"]) if first_trade is not None else 0
                ),
                "first_trade_commission": (
                    float(first_trade["commission"]) if first_trade is not None else 0.0
                ),
            }
        )
    return pd.DataFrame(rows)


def run_start_date_robustness(frame: pd.DataFrame) -> dict:
    windows = build_start_windows(frame)
    configs = frozen_configs()
    observation_targets = {
        config.name: model.generate_production_target(frame, config) for config in configs
    }
    observation_targets["buy-hold"] = pd.Series(
        engine.TARGET_WEIGHT, index=frame.index, name="buy-hold"
    )
    desired_targets = {
        name: engine.execution_target(target, delay=1)
        for name, target in observation_targets.items()
    }
    ordered_models = ("buy-hold", *FROZEN_MODELS)
    bars, market_state = engine._engine_inputs(frame)
    regimes = engine._regime_labels(frame)
    rows = []
    total_windows = len(windows)
    for window_number, window in enumerate(windows.itertuples(index=False), start=1):
        for model_name in ordered_models:
            metrics, trades = _cached_simulation(
                model_name,
                frame,
                desired_targets[model_name],
                window.start_date,
                window.end_date,
                bars,
                market_state,
            )
            rows.append(
                _result_row(
                    model_name,
                    window,
                    metrics,
                    trades,
                    desired_targets[model_name].loc[pd.Timestamp(window.start_date)],
                    regimes,
                )
            )
        if window_number % 100 == 0 or window_number == total_windows:
            print(f"[逐日起点] {window_number:,}/{total_windows:,}", flush=True)
    results = add_matched_benchmark_fields(pd.DataFrame(rows))
    summaries = pd.concat(
        [
            summarize_start_results(results, cohort="daily"),
            summarize_start_results(results, cohort="monthly"),
        ],
        ignore_index=True,
    )
    gates = evaluate_start_robustness_gates(summaries)
    regime_summary = summarize_by_regime(results)
    worst_starts = (
        results.loc[results["horizon_sessions"].isin(PRIMARY_HORIZONS)]
        .sort_values(["model", "horizon_sessions", "total_return"])
        .groupby(["model", "horizon_sessions"], as_index=False, group_keys=False)
        .head(10)
        .reset_index(drop=True)
    )
    anchor = run_anchor_comparison(frame, desired_targets, bars, market_state)
    return {
        "windows": windows,
        "results": results,
        "summaries": summaries,
        "gates": gates,
        "regime_summary": regime_summary,
        "worst_starts": worst_starts,
        "anchor": anchor,
        "configs": configs,
    }


def _percent(value) -> str:
    return "—" if pd.isna(value) else f"{float(value):.2%}"


def _number(value) -> str:
    return "—" if pd.isna(value) else f"{float(value):.2f}"


def build_report(bundle: dict, frame: pd.DataFrame) -> str:
    summary = bundle["summaries"]
    daily = summary.loc[
        summary["cohort"].eq("daily")
        & summary["horizon_sessions"].isin(PRIMARY_HORIZONS)
    ].copy()
    monthly = summary.loc[
        summary["cohort"].eq("monthly")
        & summary["horizon_sessions"].isin(PRIMARY_HORIZONS)
    ].copy()
    gates = bundle["gates"].set_index("model")
    anchor = bundle["anchor"].set_index("model")
    buy_hold = anchor.loc["buy-hold"]
    lines = [
        "# 科创 50 ETF 启动日起点鲁棒性研究",
        "",
        "## 结论",
        "",
        f"输入固定为 {frame.index.min().date()} 至 {frame.index.max().date()} 的 {len(frame):,} 个交易日。",
        f"穷举 {bundle['windows']['start_date'].nunique():,} 个可用启动日、"
        f"{len(bundle['windows']):,} 个“启动日 × 固定期限”窗口；每个窗口均以新账户独立执行买入持有、风险型和平衡型。",
        "这些窗口高度重叠，且候选已经看过全部历史，所以比例只描述日历敏感性，不是独立样本显著性。",
        f"原研究起点 {ORIGINAL_EVALUATION_START.date()} 的买入持有得到年化 {_percent(buy_hold['annualized_return'])}、"
        f"最大回撤 {_percent(buy_hold['maximum_drawdown'])}、Sharpe {_number(buy_hold['sharpe'])}；"
        "下表说明换一个启动日后结果分布如何变化。",
        "",
    ]
    for model_name in FROZEN_MODELS:
        row = gates.loc[model_name]
        risk_word = "通过" if row["risk_robust"] else "未通过"
        alpha_word = "通过" if row["return_timing_robust"] else "未通过"
        lines.append(
            f"- {MODEL_LABELS[model_name]}：历史起点风险鲁棒门槛{risk_word}；收益择时鲁棒门槛{alpha_word}。"
        )
    lines.extend(
        [
            "",
            "## 原研究起点复算",
            "",
            "| 模型 | 区间 | 累计收益 | 年化 | 最大回撤 | Sharpe | 平均暴露 | 成交次数 | 佣金 | 首笔成交价 | 首笔份额 |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for model_name in ("buy-hold", *FROZEN_MODELS):
        row = anchor.loc[model_name]
        lines.append(
            f"| {MODEL_LABELS[model_name]} | {row['start_date'].date()}—{row['end_date'].date()} | "
            f"{_percent(row['total_return'])} | {_percent(row['annualized_return'])} | "
            f"{_percent(row['maximum_drawdown'])} | {_number(row['sharpe'])} | "
            f"{_percent(row['average_exposure'])} | {int(row['filled_trade_count'])} | "
            f"{float(row['total_commission']):.2f} | {_number(row['first_trade_price'])} | "
            f"{int(row['first_trade_shares']):,} |"
        )
    lines.extend(
        [
            "",
            "## 全部逐日起点：主要期限",
            "",
            "| 期限 | 模型 | 起点数 | 正收益 | 严重不利 | 最差收益 | 10%分位收益 | 中位年化 | 90%分位回撤 | 跑赢买持 | 改善回撤 | 改善Sharpe |",
            "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in daily.sort_values(["horizon_sessions", "model"]).itertuples(index=False):
        lines.append(
            f"| {int(row.horizon_sessions)}日 | {MODEL_LABELS[row.model]} | {int(row.start_count):,} | "
            f"{_percent(row.positive_return_rate)} | {_percent(row.severe_start_rate)} | "
            f"{_percent(row.worst_total_return)} | {_percent(row.p10_total_return)} | "
            f"{_percent(row.median_annualized_return)} | {_percent(row.p90_maximum_drawdown)} | "
            f"{_percent(row.outperform_benchmark_rate)} | {_percent(row.drawdown_improvement_rate)} | "
            f"{_percent(row.sharpe_improvement_rate)} |"
        )
    lines.extend(
        [
            "",
            "严重不利起点定义为期末亏损至少 20%，或区间最大回撤至少 25%。买入持有相对自身的三项比较留空。",
            "",
            "## 月初起点敏感性复核",
            "",
            "| 期限 | 模型 | 起点数 | 正收益 | 严重不利 | 中位年化 | 跑赢买持 | 改善回撤 | 改善Sharpe |",
            "|---:|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in monthly.sort_values(["horizon_sessions", "model"]).itertuples(index=False):
        lines.append(
            f"| {int(row.horizon_sessions)}日 | {MODEL_LABELS[row.model]} | {int(row.start_count):,} | "
            f"{_percent(row.positive_return_rate)} | {_percent(row.severe_start_rate)} | "
            f"{_percent(row.median_annualized_return)} | {_percent(row.outperform_benchmark_rate)} | "
            f"{_percent(row.drawdown_improvement_rate)} | {_percent(row.sharpe_improvement_rate)} |"
        )
    lines.extend(
        [
            "",
            "## 事前门槛",
            "",
            "| 模型 | 目标 | 1年风险条件 | 2年风险条件 | 历史起点风险鲁棒 | 1年收益择时 | 2年收益择时 | 历史收益择时鲁棒 |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in bundle["gates"].itertuples(index=False):
        h252_risk = all(
            getattr(row, f"h252_{name}")
            for name in ("severe", "drawdown", "sharpe", "positive", "return_adequacy")
        )
        h504_risk = all(
            getattr(row, f"h504_{name}")
            for name in ("severe", "drawdown", "sharpe", "positive", "return_adequacy")
        )
        yes_no = lambda value: "通过" if value else "失败"
        lines.append(
            f"| {MODEL_LABELS[row.model]} | {row.objective} | {yes_no(h252_risk)} | "
            f"{yes_no(h504_risk)} | {yes_no(row.risk_robust)} | "
            f"{yes_no(row.h252_return_timing)} | {yes_no(row.h504_return_timing)} | "
            f"{yes_no(row.return_timing_robust)} |"
        )
    lines.extend(
        [
            "",
            "## 解释边界",
            "",
            "- 每个启动日都从 100 万元现金重新开始，策略使用启动日前一交易日已知信号；不存在继承旧账户低成本持仓的问题。",
            "- 买入持有与策略逐窗口使用相同启动日、结束日、整数手、佣金和滑点，因此相对比较不受单一起点口径不一致影响。",
            "- 逐日起点穷举适合发现最坏日历路径，但相邻窗口共享绝大多数行情，不能把上千个窗口称为上千份独立证据。",
            "- 本实验只诊断冻结候选；结果无论好坏都不回写参数。真正外推仍依赖冻结后的未来季度。",
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
    target = STUDY_DIR / "results" / f"{archived_at}__start-date-robustness__{run_id}"
    if target.exists():
        raise FileExistsError(f"结果目录已存在，拒绝覆盖：{target}")
    raw = target / "raw"
    raw.mkdir(parents=True)
    shutil.copy2(SOURCE_PATH, target / "source.py")
    shutil.copy2(MODEL_PATH, target / "model.py")
    shutil.copy2(model.ENGINE_PATH, target / "engine.py")
    shutil.copy2(PROTOCOL_PATH, target / "protocol.md")
    _write_csv(frame.reset_index(), raw / "input-sh588000.csv")
    _write_csv(bundle["windows"], raw / "start-windows.csv")
    _write_csv(bundle["results"], raw / "start-date-metrics.csv")
    _write_csv(bundle["summaries"], raw / "start-date-summary.csv")
    _write_csv(bundle["gates"], raw / "start-date-gates.csv")
    _write_csv(bundle["regime_summary"], raw / "start-regime-summary.csv")
    _write_csv(bundle["worst_starts"], raw / "worst-starts.csv")
    _write_csv(bundle["anchor"], raw / "original-start-anchor.csv")
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
        "study_id": "star50-single-asset-timing-start-date-robustness",
        "archived_at": archived_at,
        "run_id": run_id,
        "symbol": engine.SYMBOL,
        "evidence_class": "post-selection start-date sensitivity; not untouched OOS",
        "data": {
            "input_file": "raw/input-sh588000.csv",
            "input_sha256": artifacts["raw/input-sh588000.csv"]["sha256"],
            "start": frame.index.min(),
            "end": frame.index.max(),
            "sessions": len(frame),
            "source_phase1_archive": PHASE1_RESULT.relative_to(ROOT).as_posix(),
            "source_phase2_archive": PHASE2_RESULT.relative_to(ROOT).as_posix(),
        },
        "protocol": {
            "warmup_sessions": engine.WARMUP_SESSIONS,
            "horizons": list(HORIZONS),
            "primary_horizons": list(PRIMARY_HORIZONS),
            "start_grid": "every eligible trading day; monthly first starts reported as sensitivity",
            "fresh_account_per_start": True,
            "initial_cash": engine.INITIAL_CASH,
            "maximum_target_weight": engine.TARGET_WEIGHT,
            "execution": "next-session open",
            "etf_commission": engine.BASE_COMMISSION,
            "minimum_commission": 5.0,
            "slippage": engine.BASE_SLIPPAGE,
            "stamp_tax": 0.0,
            "severe_terminal_loss": SEVERE_TERMINAL_LOSS,
            "severe_maximum_drawdown": SEVERE_MAXIMUM_DRAWDOWN,
            "overlap_warning": "start windows overlap and are not independent observations",
        },
        "frozen_models": list(FROZEN_MODELS),
        "window_count": len(bundle["windows"]),
        "simulation_count": len(bundle["results"]),
        "gate_results": bundle["gates"].to_dict(orient="records"),
        "source_file": "source.py",
        "source_sha256": artifacts["source.py"]["sha256"],
        "model_file": "model.py",
        "model_sha256": artifacts["model.py"]["sha256"],
        "engine_file": "engine.py",
        "engine_sha256": artifacts["engine.py"]["sha256"],
        "protocol_file": "protocol.md",
        "protocol_sha256": artifacts["protocol.md"]["sha256"],
        "artifacts": artifacts,
    }
    _write_json(manifest, target / "manifest.json")
    return target


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--archived-at", default=None)
    parser.add_argument("--run-id", default="tencent-yahoo-2020-2026-v1")
    parser.add_argument("--no-archive", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    frame = engine.load_input_csv(args.input_csv)
    bundle = run_start_date_robustness(frame)
    primary = bundle["summaries"].loc[
        bundle["summaries"]["cohort"].eq("daily")
        & bundle["summaries"]["horizon_sessions"].isin(PRIMARY_HORIZONS)
    ]
    print(
        primary[
            [
                "model",
                "horizon_sessions",
                "start_count",
                "positive_return_rate",
                "severe_start_rate",
                "median_annualized_return",
                "outperform_benchmark_rate",
                "drawdown_improvement_rate",
                "sharpe_improvement_rate",
            ]
        ].to_string(index=False)
    )
    print(bundle["gates"].to_string(index=False))
    if not args.no_archive:
        archived_at = args.archived_at or pd.Timestamp.today().date().isoformat()
        target = archive_result(bundle, frame, archived_at, args.run_id)
        print(f"归档完成：{target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
