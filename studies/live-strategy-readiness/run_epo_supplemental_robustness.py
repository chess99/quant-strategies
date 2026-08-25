"""补齐安全 EPO 的 walk-forward、市场状态和随机调仓日稳健性证据。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


STUDY_DIR = Path(__file__).resolve().parent
ROOT = STUDY_DIR.parents[1]
if str(STUDY_DIR) not in sys.path:
    sys.path.insert(0, str(STUDY_DIR))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import run_epo_deep_research as deep  # noqa: E402
import run_epo_oos as base  # noqa: E402
import run_epo_safe_research as safe  # noqa: E402


CANDIDATE_ID = "multi-asset-etf-momentum-epo-safe"
CANDIDATE_DIR = STUDY_DIR / "results" / CANDIDATE_ID
PROTOCOL_PATH = CANDIDATE_DIR / "supplemental-robustness-protocol.json"
PARAMETER_RETURNS_PATH = CANDIDATE_DIR / "raw/safe__parameter-returns.csv"
BASELINE_EQUITY_PATH = CANDIDATE_DIR / "raw/safe__baseline-equity.csv"
FORMAL_SOURCE = ROOT / "strategies/joinquant/multi-asset-etf-momentum-epo/baseline.py"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def randomized_monthly_plan(
    calendar: pd.DatetimeIndex,
    *,
    seed: int,
) -> list[dict[str, pd.Timestamp]]:
    dates = pd.DatetimeIndex(calendar).normalize().sort_values().unique()
    rng = np.random.default_rng(seed)
    plan = []
    months = pd.Series(dates, index=dates).groupby(dates.to_period("M"))
    for _, month_dates in months:
        choices = pd.DatetimeIndex(month_dates.to_numpy())[:6]
        execution_date = choices[int(rng.integers(0, len(choices)))]
        location = dates.get_loc(execution_date)
        if location == 0:
            continue
        plan.append(
            {
                "observation_date": dates[location - 1],
                "scheduled_date": choices[0],
                "execution_date": execution_date,
            }
        )
    return plan


def metrics_from_returns(returns: pd.Series) -> dict[str, float]:
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if clean.empty:
        raise ValueError("return sample is empty")
    curve = (1.0 + clean).cumprod()
    volatility = clean.std(ddof=1)
    return {
        "annualized_return": float(curve.iloc[-1] ** (250.0 / len(clean)) - 1.0),
        "maximum_drawdown": float(-(curve / curve.cummax() - 1.0).min()),
        "sharpe": (
            float(clean.mean() / volatility * math.sqrt(250.0))
            if volatility > 0.0
            else float("nan")
        ),
        "observation_count": len(clean),
    }


def build_walk_forward() -> tuple[pd.DataFrame, dict[str, Any]]:
    frame = pd.read_csv(PARAMETER_RETURNS_PATH, parse_dates=["trade_date"])
    frame = frame.set_index("trade_date").sort_index()
    baseline_variant = "m34-n3-w0.2"
    rows = []
    for test_year in (2023, 2024, 2025, 2026):
        train_end = pd.Timestamp(test_year - 1, 12, 31)
        train = frame.loc[frame.index <= train_end]
        test = frame.loc[frame.index.year == test_year]
        train_sharpes = {
            variant: deep._annualized_sharpe(train[variant]) for variant in frame.columns
        }
        selected = sorted(
            train_sharpes,
            key=lambda variant: (-train_sharpes[variant], variant),
        )[0]
        selected_metrics = metrics_from_returns(test[selected])
        baseline_metrics = metrics_from_returns(test[baseline_variant])
        rows.append(
            {
                "test_year": test_year,
                "train_start": train.index.min(),
                "train_end": train.index.max(),
                "train_observation_count": len(train),
                "selected_variant": selected,
                "selected_train_sharpe": train_sharpes[selected],
                "selected_test_annualized_return": selected_metrics["annualized_return"],
                "selected_test_maximum_drawdown": selected_metrics["maximum_drawdown"],
                "selected_test_sharpe": selected_metrics["sharpe"],
                "test_observation_count": selected_metrics["observation_count"],
                "frozen_baseline_variant": baseline_variant,
                "frozen_baseline_test_annualized_return": baseline_metrics["annualized_return"],
                "frozen_baseline_test_maximum_drawdown": baseline_metrics["maximum_drawdown"],
                "frozen_baseline_test_sharpe": baseline_metrics["sharpe"],
            }
        )
    result = pd.DataFrame(rows)
    summary = {
        "fold_count": len(result),
        "fold_completion_rate": float(result["selected_variant"].notna().mean()),
        "selected_test_positive_return_rate": float(
            result["selected_test_annualized_return"].gt(0.0).mean()
        ),
        "selected_test_positive_sharpe_rate": float(result["selected_test_sharpe"].gt(0.0).mean()),
        "frozen_baseline_positive_return_rate": float(
            result["frozen_baseline_test_annualized_return"].gt(0.0).mean()
        ),
        "frozen_baseline_sharpe_ge_0_5_rate": float(
            result["frozen_baseline_test_sharpe"].ge(0.5).mean()
        ),
    }
    return result, summary


def segment_row(name: str, returns: pd.Series) -> dict[str, Any]:
    metrics = metrics_from_returns(returns)
    return {
        "segment": name,
        **metrics,
        "cumulative_log_return_contribution": float(np.log1p(returns).sum()),
    }


def build_regime_attribution(bars: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    equity = pd.read_csv(BASELINE_EQUITY_PATH, parse_dates=["trade_date"])
    portfolio = equity.set_index("trade_date")["daily_return"].astype(float)
    market = bars[bars["symbol"].eq("SH510300")].sort_values("trade_date").set_index("trade_date")
    close = pd.to_numeric(market["adjusted_close"], errors="raise")
    amount = pd.to_numeric(market["amount"], errors="coerce")
    prior_trailing_return = close.shift(1).div(close.shift(251)).sub(1.0)
    prior_liquidity_ratio = (
        amount.shift(1).rolling(20).mean().div(amount.shift(1).rolling(250).median())
    )
    same_day_return = close.pct_change(fill_method=None)
    labels = pd.Series("warm-up", index=market.index, dtype=object)
    ready = prior_trailing_return.notna()
    labels.loc[ready & prior_trailing_return.ge(0.10)] = "bull"
    labels.loc[ready & prior_trailing_return.le(-0.10)] = "bear"
    labels.loc[ready & prior_trailing_return.gt(-0.10) & prior_trailing_return.lt(0.10)] = (
        "sideways"
    )
    aligned = pd.DataFrame(
        {
            "portfolio": portfolio,
            "primary_regime": labels,
            "liquidity_contraction": prior_liquidity_ratio.le(0.60),
            "extreme_market_day": same_day_return.abs().ge(0.03),
        }
    ).dropna(subset=["portfolio"])
    rows = []
    for regime in ("bull", "bear", "sideways"):
        rows.append(
            segment_row(regime, aligned.loc[aligned["primary_regime"].eq(regime), "portfolio"])
        )
    rows.append(
        segment_row(
            "liquidity-contraction",
            aligned.loc[aligned["liquidity_contraction"], "portfolio"],
        )
    )
    rows.append(
        segment_row(
            "extreme-market-day",
            aligned.loc[aligned["extreme_market_day"], "portfolio"],
        )
    )
    result = pd.DataFrame(rows)
    primary = result[result["segment"].isin(["bull", "bear", "sideways"])]
    summary = {
        "primary_regime_count": int(primary["observation_count"].gt(0).sum()),
        "minimum_primary_regime_observations": int(primary["observation_count"].min()),
        "liquidity_contraction_observations": int(
            result.loc[result["segment"].eq("liquidity-contraction"), "observation_count"].iloc[0]
        ),
        "extreme_market_day_observations": int(
            result.loc[result["segment"].eq("extreme-market-day"), "observation_count"].iloc[0]
        ),
        "warmup_observations": int(aligned["primary_regime"].eq("warm-up").sum()),
    }
    return result, summary


def build_placebo(
    bars: pd.DataFrame,
    market_state: pd.DataFrame,
    *,
    trial_count: int,
    seed: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    original_plan_builder = deep.build_execution_plan
    rows = []
    try:
        for trial in range(trial_count):
            trial_seed = seed + trial

            def plan_builder(calendar, delay_sessions=0, selected_seed=trial_seed):
                return randomized_monthly_plan(calendar, seed=selected_seed)

            deep.build_execution_plan = plan_builder
            metrics, _ = safe._simulate_tracked(
                bars,
                market_state,
                start=safe.FULL_START,
                end=safe.FULL_END,
            )
            rows.append(
                {
                    "trial": trial + 1,
                    "seed": trial_seed,
                    "status": "ok",
                    "annualized_return": metrics["annualized_return"],
                    "maximum_drawdown": metrics["maximum_drawdown"],
                    "sharpe": metrics["sharpe"],
                    "fallback_count": metrics["fallback_count"],
                    "weight_build_count": metrics["weight_build_count"],
                    "fallback_share": metrics["fallback_share"],
                }
            )
    finally:
        deep.build_execution_plan = original_plan_builder
    result = pd.DataFrame(rows)
    summary = {
        "trial_count": len(result),
        "completion_rate": float(result["status"].eq("ok").mean()),
        "positive_return_rate": float(result["annualized_return"].gt(0.0).mean()),
        "sharpe_ge_0_5_rate": float(result["sharpe"].ge(0.5).mean()),
        "maximum_fallback_share": float(result["fallback_share"].max()),
        "median_annualized_return": float(result["annualized_return"].median()),
        "median_sharpe": float(result["sharpe"].median()),
        "minimum_sharpe": float(result["sharpe"].min()),
    }
    return result, summary


def run_supplement(data_root: Path | None = None) -> dict[str, Any]:
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    safe.BUILD_EVENTS.clear()
    safe.FALLBACK_EVENTS.clear()
    safe._install_safe_builder()
    store = base.ResearchDataStore(data_root)
    bars = base.load_bars(store)
    market_state = base.build_market_state(bars)
    walk, walk_summary = build_walk_forward()
    regime, regime_summary = build_regime_attribution(bars)
    placebo_protocol = protocol["placebo"]
    placebo, placebo_summary = build_placebo(
        bars,
        market_state,
        trial_count=placebo_protocol["trial_count"],
        seed=placebo_protocol["seed"],
    )
    walk_thresholds = protocol["walk_forward"]["gates"]
    regime_thresholds = protocol["regime_attribution"]["gates"]
    placebo_thresholds = placebo_protocol["gates"]
    gates = {
        "walk_forward_completion_gate": walk_summary["fold_completion_rate"]
        >= walk_thresholds["fold_completion_rate_min"],
        "walk_forward_return_gate": walk_summary["selected_test_positive_return_rate"]
        >= walk_thresholds["selected_test_positive_return_rate_min"],
        "walk_forward_sharpe_gate": walk_summary["selected_test_positive_sharpe_rate"]
        >= walk_thresholds["selected_test_positive_sharpe_rate_min"],
        "primary_regime_coverage_gate": regime_summary["primary_regime_count"]
        >= regime_thresholds["primary_regime_count_min"],
        "primary_regime_observation_gate": regime_summary["minimum_primary_regime_observations"]
        >= regime_thresholds["minimum_observations_per_primary_regime"],
        "liquidity_regime_observation_gate": regime_summary["liquidity_contraction_observations"]
        >= regime_thresholds["minimum_liquidity_contraction_observations"],
        "extreme_regime_observation_gate": regime_summary["extreme_market_day_observations"]
        >= regime_thresholds["minimum_extreme_market_day_observations"],
        "placebo_completion_gate": placebo_summary["completion_rate"]
        >= placebo_thresholds["completion_rate_min"],
        "placebo_return_gate": placebo_summary["positive_return_rate"]
        >= placebo_thresholds["positive_return_rate_min"],
        "placebo_sharpe_gate": placebo_summary["sharpe_ge_0_5_rate"]
        >= placebo_thresholds["sharpe_ge_0_5_rate_min"],
        "placebo_fallback_gate": placebo_summary["maximum_fallback_share"]
        <= placebo_thresholds["fallback_rebalance_share_max"],
    }
    status = "R2" if all(gates.values()) else "R1"
    scorecard = {
        "schema_version": 1,
        "candidate_id": CANDIDATE_ID,
        "status_before_supplement": "R2",
        "status_after_supplement": status,
        "walk_forward": walk_summary,
        "regime_attribution": regime_summary,
        "placebo": placebo_summary,
        "gates": gates,
        "historical_parameters_changed": False,
        "decision": (
            "retain R2; supplemental mandatory diagnostics passed"
            if status == "R2"
            else "downgrade to R1; retain failed supplement and do not repair history"
        ),
    }
    walk.to_csv(
        CANDIDATE_DIR / "supplemental-walk-forward.csv",
        index=False,
        encoding="utf-8-sig",
    )
    regime.to_csv(
        CANDIDATE_DIR / "supplemental-regime-attribution.csv",
        index=False,
        encoding="utf-8-sig",
    )
    placebo.to_csv(
        CANDIDATE_DIR / "supplemental-placebo.csv",
        index=False,
        encoding="utf-8-sig",
    )
    (CANDIDATE_DIR / "supplemental-robustness-scorecard.json").write_text(
        json.dumps(safe._json_safe(scorecard), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "candidate_id": CANDIDATE_ID,
        "run_id": "walk-forward-regime-placebo-v1",
        "created_at": "2026-08-25",
        "engine_sha256": sha256_file(Path(__file__).resolve()),
        "protocol_sha256": sha256_file(PROTOCOL_PATH),
        "parameter_returns_sha256": sha256_file(PARAMETER_RETURNS_PATH),
        "baseline_equity_sha256": sha256_file(BASELINE_EQUITY_PATH),
        "formal_source_sha256": sha256_file(FORMAL_SOURCE),
        "data_manifests": {
            name: {
                "path": str(store.manifest_path(name)),
                "sha256": sha256_file(store.manifest_path(name)),
            }
            for name in ("etf_daily", "etf_master")
        },
        "artifacts": {
            "walk_forward": "supplemental-walk-forward.csv",
            "regime_attribution": "supplemental-regime-attribution.csv",
            "placebo": "supplemental-placebo.csv",
            "scorecard": "supplemental-robustness-scorecard.json",
        },
    }
    (CANDIDATE_DIR / "supplemental-robustness-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    conclusion = f"""# ETF 动量 + EPO：补充稳健性结论

## 事实

- 4 个 expanding walk-forward 折全部完成；训练期冠军在下一年收益为正的比例为
  {walk_summary["selected_test_positive_return_rate"]:.1%}，Sharpe 为正比例为
  {walk_summary["selected_test_positive_sharpe_rate"]:.1%}。冻结基线下一年收益为正比例为
  {walk_summary["frozen_baseline_positive_return_rate"]:.1%}。
- 牛市、熊市、震荡三类因果状态均有覆盖，单类最少
  {regime_summary["minimum_primary_regime_observations"]} 个交易日；流动性收缩与极端市场日分别有
  {regime_summary["liquidity_contraction_observations"]} 和
  {regime_summary["extreme_market_day_observations"]} 个观察。
- 24 个随机月内调仓日试验全部完成，年化为正比例 {placebo_summary["positive_return_rate"]:.1%}，
  Sharpe 不低于 0.5 的比例 {placebo_summary["sharpe_ge_0_5_rate"]:.1%}，最低 Sharpe
  {placebo_summary["minimum_sharpe"]:.2f}。

## 推断

这些试验只检查冻结骨架是否依赖特定历史切点，不选择新参数。市场状态归因是描述性证据；极端市场日
使用同日指数收益分类，不进入信号。walk-forward 训练冠军也不会替换冻结基线。

## 决定

补充诊断后的等级：**{status}**。{scorecard["decision"]}。真实聚宽导出、QDII 生产数据和前瞻模拟盘
仍分别是 R3/R4 的独立门槛。
"""
    (CANDIDATE_DIR / "supplemental-robustness-conclusion.md").write_text(
        conclusion, encoding="utf-8"
    )
    return scorecard


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_supplement(args.data_root)
    print(json.dumps(safe._json_safe(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
