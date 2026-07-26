"""对冻结的 h18 直接月度策略执行成本、时点、容量、股票和行业压力验收。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quant_research.backtest import (  # noqa: E402
    BacktestConfig,
    CostModel,
    DailyBacktester,
    performance_metrics,
)
from quant_research.data.market_state import build_market_state  # noqa: E402
from quant_research.data.store import ResearchDataStore  # noqa: E402


def _load_holding_module():
    path = Path(__file__).with_name("run_holding_ablation.py")
    if not path.is_file():
        path = Path(__file__).with_name("holding_engine.py")
    spec = importlib.util.spec_from_file_location("oneil_acceptance_holding", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


HOLDING = _load_holding_module()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assign_point_in_time_industry(selections: pd.DataFrame, history: pd.DataFrame):
    result = selections.copy()
    result["observation_date"] = pd.to_datetime(result["observation_date"]).dt.normalize()
    relevant = history[
        history["classification_standard_code"].astype(str).eq("008021")
    ].copy()
    relevant["change_date"] = pd.to_datetime(relevant["change_date"]).dt.normalize()
    industries = pd.Series("Unknown", index=result.index, dtype="object")
    for symbol, locations in result.groupby("symbol").groups.items():
        changes = relevant[relevant["symbol"].eq(symbol)].sort_values("change_date")
        if changes.empty:
            continue
        lookup = changes.drop_duplicates("change_date", keep="last").set_index("change_date")[
            "industry_major"
        ]
        dates = result.loc[locations, "observation_date"]
        positions = lookup.index.searchsorted(dates, side="right") - 1
        valid = positions >= 0
        if valid.any():
            target_locations = np.asarray(list(locations))[valid]
            industries.loc[target_locations] = lookup.iloc[positions[valid]].fillna(
                "Unknown"
            ).to_numpy()
    result["industry"] = industries
    return result


def cashflow_attribution(trades: pd.DataFrame, final_holdings: pd.DataFrame):
    contributions = {}
    for row in trades.itertuples(index=False):
        value = float(row.gross_value)
        costs = float(row.commission) + float(row.tax)
        cashflow = value - costs if row.side == "sell" else -(value + costs)
        contributions[row.symbol] = contributions.get(row.symbol, 0.0) + cashflow
    if not final_holdings.empty:
        for row in final_holdings.itertuples(index=False):
            contributions[row.symbol] = contributions.get(row.symbol, 0.0) + float(
                row.market_value
            )
    return pd.DataFrame(
        [
            {"symbol": symbol, "net_contribution": value}
            for symbol, value in contributions.items()
        ]
    ).sort_values("net_contribution", ascending=False, ignore_index=True)


def shifted_schedule(candidates, calendar, offset_sessions=0):
    mapping = {}
    for trade_date, symbols in candidates.items():
        location = calendar.searchsorted(pd.Timestamp(trade_date), side="left")
        shifted = location + int(offset_sessions)
        if shifted < len(calendar):
            mapping[calendar[shifted]] = symbols
    return mapping


def cap_industry(selections: pd.DataFrame, maximum_per_industry=7):
    kept = []
    for _, group in selections.sort_values(["trade_date", "rank"]).groupby("trade_date"):
        counts = {}
        for row in group.itertuples():
            count = counts.get(row.industry, 0)
            if count < maximum_per_industry:
                kept.append(row.Index)
                counts[row.industry] = count + 1
    return selections.loc[kept].copy()


def run_variant(
    name,
    selections,
    bars,
    market_state,
    calendar,
    benchmark_returns,
    args,
    *,
    offset_sessions=0,
    costs=None,
    slippage_rate=None,
    maximum_volume_ratio=None,
):
    symbols = sorted(selections["symbol"].unique())
    engine = DailyBacktester(
        bars,
        market_state,
        asset_types={symbol: "stock" for symbol in symbols},
        config=BacktestConfig(
            initial_cash=args.initial_cash,
            maximum_volume_ratio=(
                args.maximum_volume_ratio
                if maximum_volume_ratio is None
                else maximum_volume_ratio
            ),
            slippage_rate=(args.slippage_rate if slippage_rate is None else slippage_rate),
            allow_unknown_st=True,
        ),
        costs=costs,
    )
    candidates = {
        pd.Timestamp(date): group.sort_values("rank")["symbol"].tolist()
        for date, group in selections.groupby("trade_date")
    }
    schedule = shifted_schedule(candidates, calendar, offset_sessions)

    def targets(_, trade_date):
        ranked = schedule.get(trade_date)
        if ranked is None:
            return None
        return HOLDING.target_weights(ranked[: args.positions], 0.95, 0.05)

    equity = engine.run(calendar, targets)
    returns = equity.set_index("trade_date")["daily_return"].reindex(calendar).fillna(0.0)
    yearly_rows = []
    for year in sorted(set(calendar.year)):
        dates = calendar[calendar.year == year]
        strategy_year = HOLDING.period_metrics(returns.reindex(dates))
        benchmark_year = HOLDING.period_metrics(benchmark_returns.reindex(dates))
        yearly_rows.append(
            {
                "variant": name,
                "year": year,
                "strategy_return": strategy_year["total_return"],
                "benchmark_return": benchmark_year["total_return"],
                "excess_return": strategy_year["total_return"]
                - benchmark_year["total_return"],
            }
        )
    segments = []
    for period, start, end in (
        ("development", "2010-01-01", "2017-12-31"),
        ("selection-validation", "2018-01-01", "2021-12-31"),
        ("full", "2010-01-01", "2021-12-31"),
    ):
        dates = calendar[(calendar >= start) & (calendar <= end)]
        strategy_metrics = HOLDING.period_metrics(returns.reindex(dates))
        benchmark_metrics = HOLDING.period_metrics(benchmark_returns.reindex(dates))
        segments.append(
            {
                "variant": name,
                "period": period,
                **strategy_metrics,
                "benchmark_total_return": benchmark_metrics["total_return"],
                "benchmark_annualized_return": benchmark_metrics["annualized_return"],
                "annualized_excess_return": strategy_metrics["annualized_return"]
                - benchmark_metrics["annualized_return"],
            }
        )
    metrics = performance_metrics(equity)
    metrics["positive_excess_year_ratio"] = float(
        np.mean([row["excess_return"] > 0 for row in yearly_rows])
    )
    final_date = calendar[-1]
    final_holdings = engine.holdings
    if not final_holdings.empty:
        final_holdings = final_holdings[final_holdings["trade_date"].eq(final_date)][
            ["symbol", "market_value"]
        ]
    attribution = cashflow_attribution(engine.trades, final_holdings)
    return {
        "metrics": metrics,
        "segments": pd.DataFrame(segments),
        "yearly": pd.DataFrame(yearly_rows),
        "equity": equity,
        "orders": engine.orders,
        "trades": engine.trades,
        "holdings": engine.holdings,
        "attribution": attribution,
    }


def liquidity_layer_diagnostic(selections, direct_events):
    features = selections[["trade_date", "symbol", "amount_20"]].copy()
    features["liquidity_percentile"] = features.groupby("trade_date")["amount_20"].rank(
        pct=True, method="average"
    )
    features["liquidity_layer"] = pd.cut(
        features["liquidity_percentile"],
        bins=[0.0, 1 / 3, 2 / 3, 1.0],
        labels=["lower", "middle", "upper"],
        include_lowest=True,
    )
    events = direct_events[direct_events["entry_rule"].eq("direct")].copy()
    events["candidate_trade_date"] = pd.to_datetime(events["candidate_trade_date"])
    merged = events.merge(
        features,
        left_on=["candidate_trade_date", "symbol"],
        right_on=["trade_date", "symbol"],
        how="left",
    )
    return (
        merged.groupby(["period", "liquidity_layer"], observed=True)
        .agg(
            events=("symbol", "size"),
            mean_excess_20=("excess_return_20", "mean"),
            mean_excess_60=("excess_return_60", "mean"),
            mean_excess_120=("excess_return_120", "mean"),
            positive_excess_60=("excess_return_60", lambda x: x.gt(0).mean()),
        )
        .reset_index()
    )


def archive(args, selections, outputs, top_symbols, top_industry, liquidity_diagnostic):
    result_dir = Path(args.result_dir)
    if result_dir.exists():
        raise FileExistsError(f"不可覆盖已有验收：{result_dir}")
    raw_dir = result_dir / "raw"
    raw_dir.mkdir(parents=True)
    selections.to_csv(raw_dir / "selections-with-industry.csv", index=False)
    liquidity_diagnostic.to_csv(raw_dir / "liquidity-layers.csv", index=False)
    comparison = []
    segments = []
    yearly = []
    for name, output in outputs.items():
        output["equity"].to_csv(raw_dir / f"{name}__equity.csv", index=False)
        output["orders"].to_csv(raw_dir / f"{name}__orders.csv", index=False)
        output["trades"].to_csv(raw_dir / f"{name}__trades.csv", index=False)
        output["attribution"].to_csv(raw_dir / f"{name}__attribution.csv", index=False)
        comparison.append({"variant": name, **output["metrics"]})
        segments.append(output["segments"])
        yearly.append(output["yearly"])
    comparison_frame = pd.DataFrame(comparison)
    segments_frame = pd.concat(segments, ignore_index=True)
    yearly_frame = pd.concat(yearly, ignore_index=True)
    comparison_frame.to_csv(raw_dir / "comparison.csv", index=False)
    segments_frame.to_csv(raw_dir / "segments.csv", index=False)
    yearly_frame.to_csv(raw_dir / "yearly.csv", index=False)
    source = Path(__file__).resolve()
    holding_source = Path(__file__).with_name("run_holding_ablation.py")
    shutil.copy2(source, result_dir / "source.py")
    shutil.copy2(holding_source, result_dir / "holding_engine.py")
    manifest = {
        "schema_version": 1,
        "study": "oneil-canslim-a-share-rebuild",
        "stage": "acceptance-stress",
        "candidate": "h18 quality-growth-momentum, direct monthly entry and exit",
        "period": "2010-01-01/2021-12-31",
        "variants": list(outputs),
        "top_five_contributors": top_symbols,
        "top_contributing_industry": top_industry,
        "metrics": {name: output["metrics"] for name, output in outputs.items()},
        "source_file": "source.py",
        "source_sha256": sha256_file(result_dir / "source.py"),
        "industry_file": str(Path(args.industry_history).resolve()),
        "industry_sha256": sha256_file(Path(args.industry_history)),
        "limitations": [
            "CNInfo CSRC-2012 industry changes cover candidate symbols only; missing symbols are explicit Unknown",
            "liquidity layers use trailing amount as an investability/size proxy because full-A PIT market cap is unavailable",
            "historical ST remains unavailable and is a hard residual data risk",
            "2018-2021 is selection validation rather than a pristine final holdout",
        ],
    }
    (result_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# h18 强制验收：交易、集中度与时点压力",
        "",
        f"全样本最大贡献的五只股票：{', '.join(top_symbols)}；最大贡献行业：{top_industry}。",
        "行业使用巨潮历史变更生效日，不使用当前行业回填。",
        "",
        "| 变体 | 累计 | 年化 | 最大回撤 | Sharpe | 正超额年份 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in comparison_frame.itertuples(index=False):
        lines.append(
            f"| {row.variant} | {row.total_return:.2%} | {row.annualized_return:.2%} | "
            f"{row.maximum_drawdown:.2%} | {row.sharpe:.3f} | "
            f"{row.positive_excess_year_ratio:.1%} |"
        )
    (result_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result_dir


def parse_args():
    base = Path(__file__).resolve().parent / "results"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qlib-dir", type=Path, default=Path("D:/code/_open-source/_data/qlib/cn_data"))
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument("--benchmark", default="SH000905")
    parser.add_argument(
        "--selections",
        nargs="+",
        type=Path,
        default=[
            base / "2026-07-27__selection-alpha__quality-backward-confirmation-v4" / "raw" / "selections.csv",
            base / "2026-07-27__selection-alpha__quality-acceleration-v3" / "raw" / "selections.csv",
        ],
    )
    parser.add_argument(
        "--industry-history",
        type=Path,
        default=Path("D:/code/_open-source/_data/oneil-rebuild/cninfo-industry-history.parquet"),
    )
    parser.add_argument(
        "--entry-events",
        type=Path,
        default=base / "2026-07-27__entry-event-study__h18-v2" / "raw" / "events.csv",
    )
    parser.add_argument("--positions", type=int, default=30)
    parser.add_argument("--initial-cash", type=float, default=10_000_000.0)
    parser.add_argument("--slippage-rate", type=float, default=0.001)
    parser.add_argument("--maximum-volume-ratio", type=float, default=0.10)
    parser.add_argument(
        "--result-dir",
        type=Path,
        default=base / "2026-07-27__acceptance-stress__h18-v1",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    selections = HOLDING.load_frozen_selections(args.selections)
    industry_history = pd.read_parquet(args.industry_history)
    selections = assign_point_in_time_industry(selections, industry_history)
    symbols = sorted(selections["symbol"].unique())
    reader = HOLDING.DirectQlibReader(args.qlib_dir)
    calendar = reader.dates("2010-01-01", "2021-12-31")
    print(f"加载 {len(symbols)} 只候选股票的验收撮合数据", flush=True)
    bars = reader.bars(symbols, calendar[0], calendar[-1], adjustment="pre")
    raw = reader.bars(symbols, calendar[0], calendar[-1], adjustment="qlib")
    store = ResearchDataStore(args.data_root)
    master = store.read_parquet("security_master")
    market_state = build_market_state(raw, calendar, master, symbols)
    benchmark_bars = reader.bars([args.benchmark], calendar[0], calendar[-1], adjustment="pre")
    benchmark_returns = (
        benchmark_bars.set_index("trade_date")["close"].reindex(calendar).ffill().pct_change().fillna(0.0)
    )
    outputs = {}
    print("运行 standard", flush=True)
    outputs["standard"] = run_variant(
        "standard", selections, bars, market_state, calendar, benchmark_returns, args
    )
    attribution = outputs["standard"]["attribution"]
    top_symbols = attribution.head(5)["symbol"].tolist()
    dominant_industry = (
        selections.groupby("symbol")["industry"]
        .agg(lambda values: values.mode().iloc[0] if not values.mode().empty else "Unknown")
        .rename("industry")
    )
    industry_contribution = attribution.merge(
        dominant_industry, left_on="symbol", right_index=True, how="left"
    ).groupby("industry")["net_contribution"].sum().sort_values(ascending=False)
    top_industry = str(industry_contribution.index[0])
    variant_specs = {
        "double-cost": {
            "selections": selections,
            "costs": CostModel(
                buy_commission=0.0006,
                sell_commission=0.0006,
                minimum_commission=10.0,
                stock_stamp_tax_before_2023_08_28=0.002,
                stock_stamp_tax_from_2023_08_28=0.001,
            ),
            "slippage_rate": 0.002,
        },
        "delay-1": {"selections": selections, "offset_sessions": 1},
        "slippage-30bp": {"selections": selections, "slippage_rate": 0.003},
        "capacity-5pct": {"selections": selections, "maximum_volume_ratio": 0.05},
        "offset-5": {"selections": selections, "offset_sessions": 5},
        "offset-10": {"selections": selections, "offset_sessions": 10},
        "offset-15": {"selections": selections, "offset_sessions": 15},
        "exclude-top5": {
            "selections": selections[~selections["symbol"].isin(top_symbols)]
        },
        "exclude-top-industry": {
            "selections": selections[~selections["industry"].eq(top_industry)]
        },
        "industry-cap-25pct": {"selections": cap_industry(selections, 7)},
    }
    for name, spec in variant_specs.items():
        print(f"运行 {name}", flush=True)
        variant_selections = spec.pop("selections")
        outputs[name] = run_variant(
            name,
            variant_selections,
            bars,
            market_state,
            calendar,
            benchmark_returns,
            args,
            **spec,
        )
        print(json.dumps(outputs[name]["metrics"], ensure_ascii=False, default=str), flush=True)
    direct_events = pd.read_csv(args.entry_events, parse_dates=["candidate_trade_date"])
    liquidity_diagnostic = liquidity_layer_diagnostic(selections, direct_events)
    result = archive(
        args, selections, outputs, top_symbols, top_industry, liquidity_diagnostic
    )
    print(f"强制验收归档：{result}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
