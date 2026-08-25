"""验证 ETF 动量 + EPO 的确定性等权安全回退工程版本。"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


STUDY_DIR = Path(__file__).resolve().parent
ROOT = STUDY_DIR.parents[1]
if str(STUDY_DIR) not in sys.path:
    sys.path.insert(0, str(STUDY_DIR))

import run_epo_deep_research as deep  # noqa: E402
import run_epo_oos as base  # noqa: E402


CANDIDATE_ID = "multi-asset-etf-momentum-epo-safe"
CANDIDATE_DIR = STUDY_DIR / "results" / CANDIDATE_ID
PARENT_DIR = STUDY_DIR / "results" / base.CANDIDATE_ID
PROTOCOL_PATH = CANDIDATE_DIR / "protocol.json"
FULL_START = deep.FULL_START
FULL_END = deep.FULL_END
BUILD_EVENTS: list[dict[str, Any]] = []
FALLBACK_EVENTS: list[dict[str, Any]] = []
original_build_target_weights = base.build_target_weights


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_build_target_weights(
    close: pd.DataFrame,
    observation_date,
    *,
    method: str,
    momentum_days: int = base.MOMENTUM_DAYS,
    stock_num: int = base.STOCK_NUM,
    epo_w: float = base.EPO_W,
    price_history_days: int = base.PRICE_HISTORY_DAYS,
) -> tuple[dict[str, float], dict[str, Any]]:
    try:
        weights, diagnostics = original_build_target_weights(
            close,
            observation_date,
            method=method,
            momentum_days=momentum_days,
            stock_num=stock_num,
            epo_w=epo_w,
            price_history_days=price_history_days,
        )
        diagnostics = {**diagnostics, "fallback_used": False}
    except ValueError as exc:
        if method != "epo" or str(exc) != "EPO produced no positive weights":
            raise
        observation = pd.Timestamp(observation_date).normalize()
        history = close.loc[close.index <= observation]
        available = [
            symbol
            for symbol in close.columns
            if history[symbol].notna().any()
            and history[symbol].dropna().index.max() == history.index[-1]
        ]
        scores = {
            symbol: base.momentum_score(history[symbol], momentum_days)
            for symbol in available
        }
        ranked = sorted(
            (
                (symbol, score)
                for symbol, score in scores.items()
                if np.isfinite(score) and score > 0.0
            ),
            key=lambda item: (-item[1], item[0]),
        )
        selected = [symbol for symbol, _ in ranked[:stock_num]]
        if not selected:
            raise ValueError("fallback has no selected momentum assets") from exc
        weights = {symbol: 1.0 / len(selected) for symbol in selected}
        diagnostics = {
            "observation_date": observation.strftime("%Y-%m-%d"),
            "method": method,
            "selected": selected,
            "scores": {
                symbol: float(score) if np.isfinite(score) else None
                for symbol, score in scores.items()
            },
            "weights": weights,
            "fallback_used": True,
            "fallback_reason": str(exc),
        }
        FALLBACK_EVENTS.append(
            {
                "observation_date": observation,
                "momentum_days": momentum_days,
                "stock_num": stock_num,
                "epo_w": epo_w,
                "selected": "|".join(selected),
            }
        )
    BUILD_EVENTS.append(
        {
            "observation_date": pd.Timestamp(observation_date).normalize(),
            "method": method,
            "momentum_days": momentum_days,
            "stock_num": stock_num,
            "epo_w": epo_w,
            "fallback_used": bool(diagnostics["fallback_used"]),
        }
    )
    return weights, diagnostics


def _install_safe_builder() -> None:
    deep.base.build_target_weights = safe_build_target_weights
    base.build_target_weights = safe_build_target_weights


def _events_since(build_start: int, fallback_start: int) -> tuple[int, int]:
    return len(BUILD_EVENTS) - build_start, len(FALLBACK_EVENTS) - fallback_start


def _simulate_tracked(*args, **kwargs):
    build_start = len(BUILD_EVENTS)
    fallback_start = len(FALLBACK_EVENTS)
    metrics, frames = deep.simulate(*args, **kwargs)
    build_count, fallback_count = _events_since(build_start, fallback_start)
    metrics = {
        **metrics,
        "weight_build_count": build_count,
        "fallback_count": fallback_count,
        "fallback_share": fallback_count / build_count if build_count else 0.0,
    }
    return metrics, frames


def verify_parent_oos_equivalence(
    bars: pd.DataFrame,
    market_state: pd.DataFrame,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, pd.DataFrame]]:
    metrics, frames = _simulate_tracked(
        bars,
        market_state,
        start=base.OOS_START,
        end=base.OOS_END,
        initial_cash=base.INITIAL_CASH,
        retry_sessions=0,
    )
    parent_equity = pd.read_csv(PARENT_DIR / "raw" / "causal-baseline-cost__equity.csv")
    parent_equity["trade_date"] = pd.to_datetime(parent_equity["trade_date"]).dt.normalize()
    frames["equity"]["trade_date"] = pd.to_datetime(
        frames["equity"]["trade_date"]
    ).dt.normalize()
    merged = parent_equity[["trade_date", "total_value"]].merge(
        frames["equity"][["trade_date", "total_value"]],
        on="trade_date",
        suffixes=("_parent", "_safe"),
        validate="one_to_one",
    )
    equity_max_difference = float(
        (merged["total_value_parent"] - merged["total_value_safe"]).abs().max()
    )
    parent_targets = pd.read_csv(PARENT_DIR / "raw" / "causal-baseline-cost__targets.csv")
    close = bars.pivot(
        index="trade_date", columns="symbol", values="adjusted_close"
    ).sort_index()
    target_matches = []
    fallback_start = len(FALLBACK_EVENTS)
    for row in parent_targets.itertuples(index=False):
        weights, _ = safe_build_target_weights(
            close,
            pd.Timestamp(row.observation_date),
            method="epo",
            momentum_days=base.MOMENTUM_DAYS,
            stock_num=base.STOCK_NUM,
            epo_w=base.EPO_W,
            price_history_days=base.PRICE_HISTORY_DAYS,
        )
        actual = json.dumps(weights, ensure_ascii=False, sort_keys=True)
        target_matches.append(actual == row.weights_json)
    target_check_fallbacks = len(FALLBACK_EVENTS) - fallback_start
    result = {
        "equity_max_absolute_difference": equity_max_difference,
        "target_count": len(target_matches),
        "exact_target_match_count": int(sum(target_matches)),
        "targets_match_exactly": bool(all(target_matches)),
        "simulation_fallback_count": metrics["fallback_count"],
        "target_check_fallback_count": target_check_fallbacks,
    }
    return result, metrics, frames


def _result_row(experiment: str, variant: str, metrics: dict[str, Any], **extra) -> dict:
    return {
        "experiment": experiment,
        "variant": variant,
        "status": "ok",
        "annualized_return": metrics.get("annualized_return"),
        "maximum_drawdown": metrics.get("maximum_drawdown"),
        "sharpe": metrics.get("sharpe"),
        "sortino": metrics.get("sortino"),
        "turnover": metrics.get("turnover"),
        "average_cash_ratio": metrics.get("average_cash_ratio"),
        "weight_build_count": metrics.get("weight_build_count"),
        "fallback_count": metrics.get("fallback_count"),
        "fallback_share": metrics.get("fallback_share"),
        **extra,
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    return value


def run_research(data_root: Path | None = None) -> dict[str, Any]:
    BUILD_EVENTS.clear()
    FALLBACK_EVENTS.clear()
    _install_safe_builder()
    store = base.ResearchDataStore(data_root)
    bars = base.load_bars(store)
    market_state = base.build_market_state(bars)
    robustness_rows = []
    experiment_count = 0

    equivalence, oos_metrics, oos_frames = verify_parent_oos_equivalence(
        bars, market_state
    )
    robustness_rows.append(
        {
            "experiment": "parent-oos-equivalence",
            "variant": "frozen-baseline",
            "status": "ok" if equivalence["targets_match_exactly"] else "failed",
            **equivalence,
        }
    )
    experiment_count += 1

    baseline_metrics, baseline_frames = _simulate_tracked(
        bars, market_state, start=FULL_START, end=FULL_END
    )
    robustness_rows.append(
        _result_row("safe-full-causal", "baseline", baseline_metrics)
    )
    experiment_count += 1

    parameter_returns = {}
    parameter_positive = 0
    parameter_pass = 0
    parameter_fallbacks = 0
    parameter_builds = 0
    for momentum_days, stock_num, epo_w in itertools.product(
        (30, 34, 40), (2, 3, 4), (0.1, 0.2, 0.3)
    ):
        variant = f"m{momentum_days}-n{stock_num}-w{epo_w:.1f}"
        metrics, frames = _simulate_tracked(
            bars,
            market_state,
            start=FULL_START,
            end=FULL_END,
            momentum_days=momentum_days,
            stock_num=stock_num,
            epo_w=epo_w,
        )
        parameter_returns[variant] = pd.Series(
            frames["equity"]["daily_return"].to_numpy(dtype=float),
            index=pd.DatetimeIndex(frames["equity"]["trade_date"]),
        )
        parameter_positive += metrics["annualized_return"] > 0.0
        parameter_pass += metrics["sharpe"] >= 0.5
        parameter_fallbacks += metrics["fallback_count"]
        parameter_builds += metrics["weight_build_count"]
        robustness_rows.append(
            _result_row(
                "parameter-neighborhood",
                variant,
                metrics,
                momentum_days=momentum_days,
                stock_num=stock_num,
                epo_w=epo_w,
                selected_for_promotion=False,
            )
        )
        experiment_count += 1

    delay_metrics = []
    for delay in (0, 1, 2, 3, 5):
        metrics, _ = _simulate_tracked(
            bars,
            market_state,
            start=FULL_START,
            end=FULL_END,
            delay_sessions=delay,
        )
        delay_metrics.append(metrics)
        robustness_rows.append(
            _result_row("execution-delay", f"delay-{delay}", metrics, delay_sessions=delay)
        )
        experiment_count += 1

    for label, commission, slippage in (
        ("published", 0.0002, 0.0),
        ("baseline", 0.0003, 0.0005),
        ("double", 0.0006, 0.0010),
    ):
        metrics, _ = _simulate_tracked(
            bars,
            market_state,
            start=FULL_START,
            end=FULL_END,
            commission_rate=commission,
            slippage_rate=slippage,
        )
        robustness_rows.append(
            _result_row(
                "cost-stress",
                label,
                metrics,
                commission_rate=commission,
                slippage_rate=slippage,
            )
        )
        experiment_count += 1

    for method in ("equal-top3", "equal-pool"):
        metrics, _ = _simulate_tracked(
            bars, market_state, start=FULL_START, end=FULL_END, method=method
        )
        robustness_rows.append(_result_row("module-ablation", method, metrics))
        experiment_count += 1

    for excluded in base.ETF_SYMBOLS:
        pool = tuple(symbol for symbol in base.ETF_SYMBOLS if symbol != excluded)
        metrics, _ = _simulate_tracked(
            bars, market_state, start=FULL_START, end=FULL_END, pool=pool
        )
        robustness_rows.append(
            _result_row(
                "pool-perturbation",
                f"drop-{excluded}",
                metrics,
                excluded_symbols=excluded,
                selected_for_promotion=False,
            )
        )
        experiment_count += 1

    baseline_returns = pd.Series(
        baseline_frames["equity"]["daily_return"].to_numpy(dtype=float),
        index=pd.DatetimeIndex(baseline_frames["equity"]["trade_date"]),
    )
    for year, group in baseline_returns.groupby(baseline_returns.index.year):
        curve = (1.0 + group).cumprod()
        drawdown = curve / curve.cummax() - 1.0
        robustness_rows.append(
            {
                "experiment": "year-slice",
                "variant": str(year),
                "status": "ok",
                "annualized_return": float((1.0 + group).prod() - 1.0),
                "maximum_drawdown": float(-drawdown.min()),
                "sharpe": deep._annualized_sharpe(group),
            }
        )
    for label, window in (("rolling-1y", 250), ("rolling-3y", 750), ("rolling-5y", 1250)):
        summary = deep.rolling_return_summary(baseline_returns, window)
        robustness_rows.append(
            {
                "experiment": "rolling-window",
                "variant": label,
                "status": summary["status"],
                "rolling_minimum_return": summary.get("minimum"),
                "rolling_median_return": summary.get("median"),
                "rolling_maximum_return": summary.get("maximum"),
                "rolling_observation_count": summary.get("observation_count", 0),
            }
        )

    bootstrap = deep.moving_block_bootstrap(baseline_returns, block_size=20, samples=1000)
    for quantile in (0.025, 0.5, 0.975):
        robustness_rows.append(
            {
                "experiment": "moving-block-bootstrap",
                "variant": f"q{quantile:.3f}",
                "status": "ok",
                "annualized_return": float(bootstrap["annualized_return"].quantile(quantile)),
                "maximum_drawdown": float(bootstrap["maximum_drawdown"].quantile(quantile)),
                "bootstrap_samples": len(bootstrap),
                "bootstrap_block_size": 20,
            }
        )
    parameter_return_frame = pd.DataFrame(parameter_returns).dropna(how="any")
    pbo = deep.probability_of_backtest_overfitting(parameter_return_frame, blocks=8)
    dsr = deep.deflated_sharpe_probability(baseline_returns, trials=27)
    robustness_rows.extend(
        [
            {
                "experiment": "multiple-testing",
                "variant": "pbo-27-neighborhood",
                "status": "ok",
                **pbo,
            },
            {
                "experiment": "multiple-testing",
                "variant": "deflated-sharpe-27-trials",
                "status": "ok",
                **dsr,
            },
        ]
    )

    attribution, ranked_contributors = deep.build_attribution(baseline_frames, bars)
    for count in (1, 3):
        excluded = ranked_contributors[:count]
        pool = tuple(symbol for symbol in base.ETF_SYMBOLS if symbol not in excluded)
        metrics, _ = _simulate_tracked(
            bars, market_state, start=FULL_START, end=FULL_END, pool=pool
        )
        robustness_rows.append(
            _result_row(
                "top-contributor-ablation",
                f"remove-top-{count}",
                metrics,
                excluded_symbols="|".join(excluded),
                selected_for_promotion=False,
            )
        )
        experiment_count += 1

    capacity_rows = []
    for capital, adv in itertools.product(deep.CAPITALS, deep.ADV_RATIOS):
        metrics, _ = _simulate_tracked(
            bars,
            market_state,
            start=base.OOS_START,
            end=base.OOS_END,
            initial_cash=float(capital),
            maximum_volume_ratio=adv,
            retry_sessions=5,
        )
        capacity_rows.append(
            {
                "capital_rmb": capital,
                "adv_participation": adv,
                "annualized_return": metrics["annualized_return"],
                "maximum_drawdown": metrics["maximum_drawdown"],
                "sharpe": metrics["sharpe"],
                "average_exposure": metrics["average_exposure"],
                "unfilled_value": metrics["unfilled_value"],
                "average_completion_delay": metrics["average_completion_delay"],
                "maximum_completion_delay": metrics["maximum_completion_delay"],
                "incomplete_rebalances": metrics["incomplete_rebalances"],
                "order_count": metrics["order_count"],
                "rejected_order_count": metrics["rejected_order_count"],
                "fallback_count": metrics["fallback_count"],
            }
        )
        experiment_count += 1

    parameter_completion_rate = len(parameter_returns) / 27.0
    parameter_positive_rate = parameter_positive / 27.0
    parameter_pass_rate = parameter_pass / 27.0
    parameter_fallback_share = (
        parameter_fallbacks / parameter_builds if parameter_builds else 0.0
    )
    delay_min_sharpe = min(item["sharpe"] for item in delay_metrics)
    capacity = pd.DataFrame(capacity_rows)
    primary_min_exposure = float(
        capacity[capacity["capital_rmb"].isin(deep.CAPITALS[:3])][
            "average_exposure"
        ].min()
    )
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    thresholds = protocol["R2_gates"]
    gates = {
        "parent_oos_equivalence_gate": bool(
            equivalence["equity_max_absolute_difference"]
            <= protocol["evidence_reuse_rule"]["maximum_equity_absolute_difference"]
            and equivalence["targets_match_exactly"]
            and equivalence["simulation_fallback_count"] == 0
            and equivalence["target_check_fallback_count"] == 0
        ),
        "parameter_completion_gate": parameter_completion_rate
        >= thresholds["parameter_completion_rate_min"],
        "parameter_positive_gate": parameter_positive_rate
        >= thresholds["parameter_positive_return_rate_min"],
        "parameter_sharpe_gate": parameter_pass_rate
        >= thresholds["parameter_sharpe_ge_0_5_rate_min"],
        "fallback_share_gate": parameter_fallback_share
        <= thresholds["fallback_rebalance_share_max"],
        "execution_delay_gate": delay_min_sharpe >= thresholds["minimum_delay_sharpe"],
        "primary_capacity_gate": primary_min_exposure
        >= thresholds["primary_capital_minimum_exposure"],
    }
    status = "R2" if all(gates.values()) else "R1"
    scorecard = {
        "schema_version": 1,
        "candidate_id": CANDIDATE_ID,
        "status": status,
        "source_vintage_grade": "B",
        "strict_natural_oos": False,
        "experiment_count": experiment_count,
        "parent_oos_equivalence": equivalence,
        "parameter_neighborhood_trials": 27,
        "parameter_completion_rate": parameter_completion_rate,
        "parameter_positive_return_rate": parameter_positive_rate,
        "parameter_sharpe_ge_0_5_rate": parameter_pass_rate,
        "parameter_fallback_share": parameter_fallback_share,
        "minimum_delay_sharpe": delay_min_sharpe,
        "primary_capital_minimum_exposure": primary_min_exposure,
        "pbo": pbo,
        "deflated_sharpe": dsr,
        "gates": gates,
        "blocking_gaps_for_R3": protocol["R3_blockers"],
        "decision": "historical R2 candidate; do not promote to R3" if status == "R2" else "remain R1 and stop this engineering version",
        "parameter_selection_used_parent_oos": False,
    }

    CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)
    raw_dir = CANDIDATE_DIR / "raw"
    raw_dir.mkdir(exist_ok=True)
    robustness = pd.DataFrame(robustness_rows)
    robustness.to_csv(CANDIDATE_DIR / "robustness.csv", index=False, encoding="utf-8-sig")
    capacity.to_csv(CANDIDATE_DIR / "capacity.csv", index=False, encoding="utf-8-sig")
    attribution.to_csv(CANDIDATE_DIR / "attribution.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(
        [
            {
                "scenario": "parent-causal-baseline-cost",
                "period_start": str(base.OOS_START.date()),
                "period_end": str(base.OOS_END.date()),
                "annualized_return": oos_metrics.get("annualized_return"),
                "equity_max_absolute_difference": equivalence["equity_max_absolute_difference"],
                "targets_match_exactly": equivalence["targets_match_exactly"],
                "fallback_count": equivalence["simulation_fallback_count"],
                "parameter_selection_used_oos": False,
            }
        ]
    ).to_csv(CANDIDATE_DIR / "oos.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(
        [
            {"version": "parent-frozen", "source_sha256": sha256_file(base.SOURCE_PATH)},
            {"version": "safe-fallback", "source_sha256": sha256_file(Path(__file__).resolve())},
        ]
    ).to_csv(CANDIDATE_DIR / "original-vs-causal.csv", index=False, encoding="utf-8-sig")
    (CANDIDATE_DIR / "live-readiness-scorecard.json").write_text(
        json.dumps(_json_safe(scorecard), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    baseline_frames["equity"].to_csv(raw_dir / "safe__baseline-equity.csv", index=False)
    baseline_frames["trades"].to_csv(raw_dir / "safe__baseline-trades.csv", index=False)
    baseline_frames["targets"].to_csv(raw_dir / "safe__baseline-targets.csv", index=False)
    oos_frames["equity"].to_csv(raw_dir / "safe__oos-equity.csv", index=False)
    parameter_return_frame.to_csv(raw_dir / "safe__parameter-returns.csv", index=True)
    bootstrap.to_csv(raw_dir / "safe__moving-block-bootstrap.csv", index=False)
    pd.DataFrame(BUILD_EVENTS).to_csv(raw_dir / "safe__weight-build-events.csv", index=False)
    pd.DataFrame(FALLBACK_EVENTS).to_csv(raw_dir / "safe__fallback-events.csv", index=False)
    manifest = {
        "schema_version": 1,
        "candidate_id": CANDIDATE_ID,
        "run_id": "safe-equal-fallback-v1",
        "created_at": "2026-08-25",
        "source_sha256": sha256_file(base.SOURCE_PATH),
        "engine_sha256": sha256_file(Path(__file__).resolve()),
        "protocol_sha256": sha256_file(PROTOCOL_PATH),
        "data_manifests": {
            name: {
                "path": str(store.manifest_path(name)),
                "sha256": sha256_file(store.manifest_path(name)),
            }
            for name in ("etf_daily", "etf_master")
        },
        "parameter_selection_used_parent_oos": False,
        "scorecard": scorecard,
        "artifacts": {
            "robustness": "robustness.csv",
            "capacity": "capacity.csv",
            "attribution": "attribution.csv",
            "oos": "oos.csv",
        },
    }
    (CANDIDATE_DIR / "safe-run-manifest.json").write_text(
        json.dumps(_json_safe(manifest), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    conclusion = f"""# ETF 动量 + EPO 安全回退：研究结论

## 事实

- 父版本发布后逐日净值最大绝对差为 {equivalence['equity_max_absolute_difference']:.12g}，
  {equivalence['exact_target_match_count']}/{equivalence['target_count']} 个目标权重完全一致，冻结路径回退次数为
  {equivalence['simulation_fallback_count']}。
- 27 个参数邻域完成率 {parameter_completion_rate:.1%}，年化为正比例 {parameter_positive_rate:.1%}，
  Sharpe 不低于 0.5 的比例 {parameter_pass_rate:.1%}。
- 邻域回退占全部权重构建的 {parameter_fallback_share:.1%}；0—5 日延迟最低 Sharpe 为
  {delay_min_sharpe:.2f}，20—200 万元最低平均风险暴露为 {primary_min_exposure:.1%}。

## 推断

安全回退只修复优化器无可执行解，不改变已有发布后基线路径。它是否足以把父版本从脆弱的动态集中器
提升为历史候选，由预注册邻域完成率、收益稳定性和回退占比共同决定，而不是由基线 CAGR 决定。

## 决定

当前等级：**{status}**。{scorecard['decision']}。即使达到 R2，平台订单对照、QDII 生产数据和冻结
模拟盘仍未完成，不能称为 R3/R4 或直接实盘。
"""
    (CANDIDATE_DIR / "conclusion.md").write_text(conclusion, encoding="utf-8")
    return scorecard


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_research(args.data_root)
    print(json.dumps(_json_safe(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
