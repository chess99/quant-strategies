"""ETF Core Rotation v1 第二阶段本地诊断与聚宽黄金对照准备。"""

from __future__ import annotations

import argparse
import itertools
import json
from dataclasses import asdict, replace
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

import local_backtest as engine


matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


MODULE_FLAGS = (
    "use_absolute_momentum",
    "use_inverse_vol",
    "use_vol_target",
    "use_rank_buffer",
    "use_correlation_guard",
    "use_capacity",
)

PROBE_DATES = (
    "2014-01-03",
    "2015-06-12",
    "2015-08-21",
    "2016-01-29",
    "2018-06-29",
    "2018-12-28",
    "2020-03-20",
    "2020-07-10",
    "2021-02-19",
    "2022-04-29",
    "2022-10-28",
    "2023-12-29",
    "2024-02-02",
    "2024-09-27",
    "2025-04-03",
    "2025-12-26",
    "2026-07-24",
)

PERIODS = (
    ("full", "2014-01-02", "2026-07-24"),
    ("era_2014_2017", "2014-01-02", "2017-12-29"),
    ("era_2018_2021", "2018-01-02", "2021-12-31"),
    ("era_2022_2026", "2022-01-04", "2026-07-24"),
)


def local_to_joinquant(symbol: str) -> str:
    if symbol.startswith("SH"):
        return f"{symbol[2:]}.XSHG"
    if symbol.startswith("SZ"):
        return f"{symbol[2:]}.XSHE"
    return symbol


def module_factorial_configs(base: engine.StrategyConfig) -> list[engine.StrategyConfig]:
    configs = []
    for bits in itertools.product((False, True), repeat=len(MODULE_FLAGS)):
        flags = dict(zip(MODULE_FLAGS, bits))
        bit_text = "".join("1" if value else "0" for value in bits)
        configs.append(
            replace(
                base,
                name=f"factorial_{bit_text}",
                use_top_k=True,
                **flags,
            )
        )
    return configs


def _metric_row(
    result: engine.SimulationResult,
    period: str,
    config: engine.StrategyConfig,
) -> dict:
    return {
        "period": period,
        "trial": config.name,
        **{flag: bool(getattr(config, flag)) for flag in MODULE_FLAGS},
        **result.metrics,
    }


def paired_module_effects(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    metrics = (
        "annualized_return",
        "maximum_drawdown",
        "sharpe",
        "annualized_turnover",
        "average_risk_weight",
    )
    for period, period_frame in frame.groupby("period", sort=False):
        for module in MODULE_FLAGS:
            other_flags = [flag for flag in MODULE_FLAGS if flag != module]
            deltas = []
            for _, pair in period_frame.groupby(other_flags, dropna=False):
                enabled = pair[pair[module]]
                disabled = pair[~pair[module]]
                if len(enabled) != 1 or len(disabled) != 1:
                    continue
                on = enabled.iloc[0]
                off = disabled.iloc[0]
                deltas.append({metric: float(on[metric] - off[metric]) for metric in metrics})
            delta_frame = pd.DataFrame(deltas)
            row = {"period": period, "module": module, "pair_count": len(delta_frame)}
            for metric in metrics:
                row[f"mean_delta_{metric}"] = float(delta_frame[metric].mean())
                row[f"median_delta_{metric}"] = float(delta_frame[metric].median())
            row["positive_sharpe_pair_ratio"] = float(delta_frame["sharpe"].gt(0).mean())
            rows.append(row)
    return pd.DataFrame(rows)


def run_factorial(
    data: engine.MarketData,
    cache: engine.SnapshotCache,
    base: engine.StrategyConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    configs = module_factorial_configs(base)
    for period, start, end in PERIODS:
        for config in configs:
            result = engine.run_simulation_fast(data, cache, config, start, end)
            rows.append(_metric_row(result, period, config))
    frame = pd.DataFrame(rows)
    return frame, paired_module_effects(frame)


def run_allocation_decomposition(
    data: engine.MarketData,
    cache: engine.SnapshotCache,
    base: engine.StrategyConfig,
) -> pd.DataFrame:
    rows = []
    for period, start, end in PERIODS:
        for mode in ("full", "risk_cash", "risk_normalized", "defensive_only"):
            config = replace(base, name=mode, allocation_mode=mode)
            result = engine.run_simulation_fast(data, cache, config, start, end)
            rows.append(
                {
                    "period": period,
                    "allocation_mode": mode,
                    **result.metrics,
                }
            )
    return pd.DataFrame(rows)


def run_execution_delay(
    data: engine.MarketData,
    cache: engine.SnapshotCache,
    base: engine.StrategyConfig,
) -> pd.DataFrame:
    rows = []
    for period, start, end in PERIODS:
        for lag in (1, 2, 3, 5):
            config = replace(
                base,
                name=f"execution_lag_{lag}",
                execution_lag_sessions=lag,
            )
            result = engine.run_simulation_fast(data, cache, config, start, end)
            rows.append({"period": period, "lag_sessions": lag, **result.metrics})
    return pd.DataFrame(rows)


def buy_and_hold(
    data: engine.MarketData,
    weights: dict[str, float],
    base: engine.StrategyConfig,
    start: str,
    end: str,
) -> tuple[pd.DataFrame, dict]:
    dates = data.trade_dates[
        (data.trade_dates >= pd.Timestamp(start)) & (data.trade_dates <= pd.Timestamp(end))
    ]
    symbols = sorted(weights)
    valid = data.adjusted_open.reindex(index=dates, columns=symbols).notna().all(axis=1)
    if not valid.any():
        raise ValueError(f"no common price date for {symbols}")
    first_date = pd.Timestamp(valid[valid].index[0])
    dates = dates[dates >= first_date]
    first_location = data.trade_dates.get_loc(first_date)
    observation = data.trade_dates[max(0, first_location - 1)]
    config = replace(
        base,
        use_capacity=False,
        enforce_trade_adv_participation=False,
        min_trade_value=0.0,
        min_weight_change=0.0,
    )
    cash, positions, _, _, traded, cost = engine._execute_targets(
        first_date,
        observation,
        weights,
        config.initial_cash,
        config.initial_cash,
        {},
        data,
        config,
        False,
    )
    closes = data.adjusted_close.reindex(index=dates, columns=sorted(positions)).ffill()
    shares = np.array([positions[symbol] for symbol in closes.columns], dtype=float)
    position_value = closes.to_numpy(dtype=float) @ shares
    total_value = cash + position_value
    previous = np.concatenate(([config.initial_cash], total_value[:-1]))
    risk_symbols = set(data.risk_symbols)
    risk_shares = np.array(
        [positions[symbol] if symbol in risk_symbols else 0 for symbol in closes.columns],
        dtype=float,
    )
    risk_value = closes.to_numpy(dtype=float) @ risk_shares
    equity = pd.DataFrame(
        {
            "trade_date": dates,
            "cash": cash,
            "positions_value": position_value,
            "total_value": total_value,
            "daily_return": total_value / previous - 1.0,
            "cash_ratio": cash / total_value,
            "risk_weight": risk_value / total_value,
            "gross_traded": 0.0,
            "transaction_cost": 0.0,
            "holdings": ";".join(sorted(positions)),
            "unattributed_pnl": np.nan,
        }
    )
    equity.loc[equity.index[0], "gross_traded"] = traded
    equity.loc[equity.index[0], "transaction_cost"] = cost
    return equity, engine.performance_metrics(equity)


def run_benchmarks(
    data: engine.MarketData,
    base: engine.StrategyConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    specifications = {
        "csi300_buy_hold": {engine.BENCHMARK: 1.0},
        "csi300_bond_60_40_buy_hold": {
            engine.BENCHMARK: 0.6,
            engine.DEFENSIVE_BONDS[0]: 0.4,
        },
        "government_bond_buy_hold": {engine.DEFENSIVE_BONDS[0]: 1.0},
    }
    rows = []
    equity_rows = []
    for name, weights in specifications.items():
        equity, metrics = buy_and_hold(
            data,
            weights,
            base,
            engine.DEFAULT_START,
            engine.DEFAULT_END,
        )
        rows.append(
            {
                "benchmark": name,
                "weights": json.dumps(weights, ensure_ascii=False, sort_keys=True),
                "actual_start": pd.Timestamp(equity["trade_date"].iloc[0]).date().isoformat(),
                **metrics,
            }
        )
        copy = equity[["trade_date", "total_value", "daily_return"]].copy()
        copy["benchmark"] = name
        equity_rows.append(copy)
    return pd.DataFrame(rows), pd.concat(equity_rows, ignore_index=True)


def local_probe_snapshots(
    data: engine.MarketData,
    cache: engine.SnapshotCache,
    base: engine.StrategyConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    summaries = []
    members = []
    for requested in PROBE_DATES:
        eligible_dates = data.trade_dates[data.trade_dates <= pd.Timestamp(requested)]
        if len(eligible_dates) == 0:
            continue
        observation = pd.Timestamp(eligible_dates[-1])
        snapshot = cache.get(observation, base)
        ranked = snapshot.ranked.copy()
        selected = engine.select_assets(snapshot, [], data, base)
        risk_weights, _ = engine.build_risk_weights(
            selected,
            snapshot,
            observation,
            base.initial_cash,
            data,
            base,
        )
        target_weights = engine.compose_target_weights(
            risk_weights,
            observation,
            data,
            base.allocation_mode,
        )
        summaries.append(
            {
                "requested_date": requested,
                "observation_date": observation.date().isoformat(),
                "raw_eligible_count": snapshot.raw_eligible_count,
                "deduplicated_count": snapshot.deduplicated_count,
                "liquid_count": snapshot.liquid_count,
                "ranked_count": len(ranked),
                "selected": ";".join(local_to_joinquant(symbol) for symbol in selected),
                "target_weights": json.dumps(
                    {
                        local_to_joinquant(symbol): weight
                        for symbol, weight in target_weights.items()
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            }
        )
        for symbol, row in ranked.iterrows():
            members.append(
                {
                    "observation_date": observation.date().isoformat(),
                    "symbol": local_to_joinquant(symbol),
                    "tracking_key": str(row.get("tracking_key", "")),
                    "adv20": float(row["adv20"]),
                    "r63": float(row["r63"]),
                    "r126": float(row["r126"]),
                    "r252": float(row["r252"]),
                    "vol60": float(row["vol60"]),
                    "score": float(row["score"]),
                    "abs_pass": bool(row["abs_pass"]),
                    "rank": int(row["rank"]),
                    "selected": symbol in selected,
                }
            )
    return pd.DataFrame(summaries), pd.DataFrame(members)


def create_charts(
    effects: pd.DataFrame,
    allocations: pd.DataFrame,
    delays: pd.DataFrame,
    target: Path,
) -> None:
    target.mkdir(parents=True, exist_ok=True)
    full_effects = effects[effects["period"].eq("full")].copy()
    figure, axis = plt.subplots(figsize=(10, 5.5))
    axis.bar(full_effects["module"], full_effects["mean_delta_sharpe"])
    axis.axhline(0, color="black", linewidth=0.8)
    axis.tick_params(axis="x", rotation=35)
    axis.set_ylabel("Mean paired Sharpe delta")
    axis.set_title("64-run module factorial: average marginal effect")
    figure.tight_layout()
    figure.savefig(target / "module-factorial-effects.png", dpi=160)
    plt.close(figure)

    full_allocations = allocations[allocations["period"].eq("full")]
    full_delays = delays[delays["period"].eq("full")]
    figure, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    axes[0].bar(full_allocations["allocation_mode"], full_allocations["sharpe"])
    axes[0].tick_params(axis="x", rotation=30)
    axes[0].set_title("Risk/defensive sleeve decomposition")
    axes[0].set_ylabel("Sharpe")
    axes[1].plot(full_delays["lag_sessions"], full_delays["sharpe"], marker="o")
    axes[1].set_title("Execution delay sensitivity")
    axes[1].set_xlabel("Sessions after signal")
    axes[1].set_ylabel("Sharpe")
    figure.tight_layout()
    figure.savefig(target / "allocation-and-delay.png", dpi=160)
    plt.close(figure)


def run(output: Path, data_root: Path) -> dict:
    output = Path(output)
    raw = output / "raw" / "local"
    assets = output / "assets"
    raw.mkdir(parents=True, exist_ok=True)
    data = engine.load_market_data(data_root)
    cache = engine.SnapshotCache(data)
    base = engine.StrategyConfig()
    print("[1/5] 64-run module factorial across four periods", flush=True)
    factorial, effects = run_factorial(data, cache, base)
    print("[2/5] risk/defensive sleeve decomposition", flush=True)
    allocations = run_allocation_decomposition(data, cache, base)
    print("[3/5] execution delay sensitivity", flush=True)
    delays = run_execution_delay(data, cache, base)
    print("[4/5] low-complexity buy-and-hold benchmarks", flush=True)
    benchmarks, benchmark_equity = run_benchmarks(data, base)
    print("[5/5] local snapshots for JoinQuant golden comparison", flush=True)
    probes, probe_members = local_probe_snapshots(data, cache, base)
    frames = {
        "module-factorial.csv": factorial,
        "module-marginal-effects.csv": effects,
        "allocation-decomposition.csv": allocations,
        "execution-delay.csv": delays,
        "benchmarks.csv": benchmarks,
        "benchmark-equity.csv": benchmark_equity,
        "local-probe-summary.csv": probes,
        "local-probe-members.csv": probe_members,
    }
    for filename, frame in frames.items():
        frame.to_csv(raw / filename, index=False, encoding="utf-8")
    create_charts(effects, allocations, delays, assets)
    summary = {
        "schema_version": 1,
        "experiment_protocol": {
            "module_factorial_trials": int(len(factorial)),
            "independent_module_combinations": 64,
            "periods": [period for period, _, _ in PERIODS],
            "allocation_runs": int(len(allocations)),
            "execution_delay_runs": int(len(delays)),
            "benchmark_runs": int(len(benchmarks)),
            "probe_dates": int(len(probes)),
        },
        "base_config": asdict(base),
        "best_full_period_factorial_sharpe": float(
            factorial[factorial["period"].eq("full")]["sharpe"].max()
        ),
    }
    (raw / "phase2-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=engine.DEFAULT_DATA_ROOT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = run(args.output, args.data_root)
    print(json.dumps(summary["experiment_protocol"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
