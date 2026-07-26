"""冻结 h18 选股、直接入场和月度持有后，比较三种市场风险覆盖层。"""

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

from quant_research.backtest import BacktestConfig, DailyBacktester, performance_metrics  # noqa: E402
from quant_research.data.market_state import build_market_state  # noqa: E402
from quant_research.data.store import ResearchDataStore  # noqa: E402


def _load_holding_module():
    path = Path(__file__).with_name("run_holding_ablation.py")
    if not path.is_file():
        path = Path(__file__).with_name("holding_engine.py")
    spec = importlib.util.spec_from_file_location("oneil_holding_helpers", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


HOLDING = _load_holding_module()
MODELS = ("market-control", "market-block-new", "market-scale-50", "market-cash")
MODEL_TO_EXPERIMENT = {
    "market-control": "h18-control",
    "market-block-new": "h28",
    "market-scale-50": "h29",
    "market-cash": "h30",
}
INDEX_SYMBOLS = ("SH000300", "SH000905", "SH000852", "SZ399006", "SH000688")
ALL_A_BOARDS = {"main", "chinext", "star", "beijing"}


def market_risk_on(breadth_above_200, index_above_200) -> bool:
    if breadth_above_200 is None or not np.isfinite(breadth_above_200):
        return False
    available = [bool(value) for value in index_above_200 if not pd.isna(value)]
    if not available:
        return False
    return float(breadth_above_200) >= 0.50 and np.mean(available) >= 0.50


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_market_regime(reader, master, observation_dates):
    observations = pd.DatetimeIndex(observation_dates).normalize().sort_values().unique()
    start = observations.min() - pd.Timedelta(days=400)
    calendar = reader.dates(start, observations.max())
    frame = master.copy()
    frame["start_date"] = pd.to_datetime(frame["start_date"])
    frame["end_date"] = pd.to_datetime(frame["end_date"])
    frame = frame[
        frame["asset_type"].eq("stock")
        & frame["board"].isin(ALL_A_BOARDS)
        & frame["start_date"].le(observations.max())
        & frame["end_date"].ge(observations.min())
    ]
    above_count = pd.Series(0.0, index=observations)
    valid_count = pd.Series(0.0, index=observations)
    total = len(frame)
    for number, row in enumerate(frame.itertuples(index=False), 1):
        if number == 1 or number % 1000 == 0 or number == total:
            print(f"全A宽度 {number}/{total}", flush=True)
        close = reader.feature(row.symbol, "close").reindex(calendar)
        moving_average = close.rolling(200, min_periods=180).mean()
        sampled_close = close.reindex(observations)
        sampled_average = moving_average.reindex(observations)
        active = (
            (observations >= pd.Timestamp(row.start_date))
            & (observations <= pd.Timestamp(row.end_date))
        )
        valid = active & sampled_close.notna().to_numpy() & sampled_average.notna().to_numpy()
        above = valid & sampled_close.ge(sampled_average).to_numpy()
        valid_count += valid.astype(float)
        above_count += above.astype(float)
    result = pd.DataFrame(
        {
            "observation_date": observations,
            "breadth_above_200": above_count / valid_count.replace(0, np.nan),
            "breadth_valid_count": valid_count,
        }
    )
    index_flag_columns = []
    for symbol in INDEX_SYMBOLS:
        close = reader.feature(symbol, "close").reindex(calendar)
        moving_average = close.rolling(200, min_periods=180).mean()
        column = f"{symbol}_above_200"
        index_flag_columns.append(column)
        sampled_close = close.reindex(observations)
        sampled_average = moving_average.reindex(observations)
        values = sampled_close.ge(sampled_average).astype("boolean")
        values[sampled_close.isna() | sampled_average.isna()] = pd.NA
        result[column] = values.to_numpy()
    result["risk_on"] = [
        market_risk_on(row.breadth_above_200, [getattr(row, col) for col in index_flag_columns])
        for row in result.itertuples(index=False)
    ]
    return result


def run_model(
    model,
    selections,
    market_regime,
    bars,
    market_state,
    calendar,
    benchmark_returns,
    args,
):
    symbols = sorted(selections["symbol"].unique())
    engine = DailyBacktester(
        bars,
        market_state,
        asset_types={symbol: "stock" for symbol in symbols},
        config=BacktestConfig(
            initial_cash=args.initial_cash,
            maximum_volume_ratio=args.maximum_volume_ratio,
            slippage_rate=args.slippage_rate,
            allow_unknown_st=True,
        ),
    )
    candidates = {
        pd.Timestamp(date): group.sort_values("rank")["symbol"].tolist()
        for date, group in selections.groupby("trade_date")
    }
    observation_map = selections.drop_duplicates("trade_date").set_index("trade_date")[
        "observation_date"
    ].to_dict()
    regime_map = market_regime.set_index("observation_date")["risk_on"].to_dict()

    def targets(_, trade_date):
        if trade_date not in candidates:
            return None
        ranked = candidates[trade_date][: args.positions]
        observation = pd.Timestamp(observation_map[trade_date])
        risk_on = bool(regime_map.get(observation, False))
        if model == "market-control" or risk_on:
            return HOLDING.target_weights(ranked, exposure=0.95, maximum_weight=0.05)
        if model == "market-scale-50":
            return HOLDING.target_weights(ranked, exposure=0.50, maximum_weight=0.05)
        if model == "market-cash":
            return {}
        retained = set(engine.positions).intersection(ranked)
        sells = set(engine.positions).difference(retained)
        return HOLDING._preserve_other_positions(engine, trade_date, sells)

    equity = engine.run(calendar, targets)
    returns = equity.set_index("trade_date")["daily_return"].reindex(calendar).fillna(0.0)
    metrics = performance_metrics(equity)
    gross_turnover = engine.trades["gross_value"].sum() if not engine.trades.empty else 0.0
    metrics["annualized_turnover"] = float(
        gross_turnover / equity["total_value"].mean() / (len(calendar) / 252.0)
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
                "model": model,
                "experiment_id": MODEL_TO_EXPERIMENT[model],
                "period": period,
                **strategy_metrics,
                "benchmark_total_return": benchmark_metrics["total_return"],
                "benchmark_annualized_return": benchmark_metrics["annualized_return"],
                "annualized_excess_return": strategy_metrics["annualized_return"]
                - benchmark_metrics["annualized_return"],
            }
        )
    return {
        "metrics": metrics,
        "segments": pd.DataFrame(segments),
        "equity": equity,
        "orders": engine.orders,
        "trades": engine.trades,
        "holdings": engine.holdings,
    }


def archive(args, selections, market_regime, outputs):
    result_dir = Path(args.result_dir)
    if result_dir.exists():
        raise FileExistsError(f"不可覆盖已有实验：{result_dir}")
    raw_dir = result_dir / "raw"
    raw_dir.mkdir(parents=True)
    selections.to_csv(raw_dir / "frozen-selections.csv", index=False)
    market_regime.to_csv(raw_dir / "market-regime.csv", index=False)
    comparison = []
    segments = []
    for model, output in outputs.items():
        output["equity"].to_csv(raw_dir / f"{model}__equity.csv", index=False)
        output["orders"].to_csv(raw_dir / f"{model}__orders.csv", index=False)
        output["trades"].to_csv(raw_dir / f"{model}__trades.csv", index=False)
        output["holdings"].to_csv(raw_dir / f"{model}__holdings.csv", index=False)
        comparison.append({"model": model, **output["metrics"]})
        segments.append(output["segments"])
    comparison_frame = pd.DataFrame(comparison)
    segment_frame = pd.concat(segments, ignore_index=True)
    comparison_frame.to_csv(raw_dir / "comparison.csv", index=False)
    segment_frame.to_csv(raw_dir / "segments.csv", index=False)
    source = Path(__file__).resolve()
    holding_source = Path(__file__).with_name("run_holding_ablation.py")
    shutil.copy2(source, result_dir / "source.py")
    shutil.copy2(holding_source, result_dir / "holding_engine.py")
    shutil.copy2(ROOT / "src" / "quant_research" / "backtest.py", result_dir / "engine.py")
    manifest = {
        "schema_version": 1,
        "study": "oneil-canslim-a-share-rebuild",
        "stage": "market-ablation",
        "candidate_model": "h18 quality-growth-momentum, direct monthly entry and exit",
        "period": "2010-01-01/2021-12-31",
        "models": list(outputs),
        "market_rule": "all-A MA200 breadth >=50% and >=50% of available CSI300/500/1000/ChiNext/STAR50 above MA200",
        "metrics": {model: output["metrics"] for model, output in outputs.items()},
        "source_file": "source.py",
        "source_sha256": sha256_file(result_dir / "source.py"),
        "selection_inputs": [
            {"path": str(Path(path).resolve()), "sha256": sha256_file(Path(path))}
            for path in args.selections
        ],
        "limitations": [
            "historical ST is unavailable and treated as unknown",
            "breadth uses securities with valid Qlib close and 200-day history on each observation date",
            "2018-2021 is selection validation, not a pristine final holdout",
        ],
    }
    (result_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# h18 市场风险层独立消融",
        "",
        "所有模型共享同一 h18 候选、直接买入、月度持有、成本与撮合。市场状态只使用月末",
        "观察日已知的跨指数 200 日线和全 A 宽度。",
        "",
        "| 阶段 | 模型 | 年化 | 年化超额 | 最大回撤 | Sharpe | Calmar |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in segment_frame.itertuples(index=False):
        lines.append(
            f"| {row.period} | {row.model} | {row.annualized_return:.2%} | "
            f"{row.annualized_excess_return:.2%} | {row.maximum_drawdown:.2%} | "
            f"{row.sharpe:.3f} | {row.calmar:.3f} |"
        )
    (result_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result_dir


def parse_args():
    base = Path(__file__).resolve().parent / "results"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--qlib-dir", type=Path, default=Path("D:/code/_open-source/_data/qlib/cn_data")
    )
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
    parser.add_argument("--models", nargs="+", choices=MODELS, default=list(MODELS))
    parser.add_argument("--positions", type=int, default=30)
    parser.add_argument("--initial-cash", type=float, default=10_000_000.0)
    parser.add_argument("--slippage-rate", type=float, default=0.001)
    parser.add_argument("--maximum-volume-ratio", type=float, default=0.10)
    parser.add_argument(
        "--result-dir",
        type=Path,
        default=base / "2026-07-27__market-ablation__h18-v1",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    selections = HOLDING.load_frozen_selections(args.selections)
    symbols = sorted(selections["symbol"].unique())
    reader = HOLDING.DirectQlibReader(args.qlib_dir)
    calendar = reader.dates("2010-01-01", "2021-12-31")
    store = ResearchDataStore(args.data_root)
    master = store.read_parquet("security_master")
    market_regime = build_market_regime(reader, master, selections["observation_date"])
    print(f"加载 {len(symbols)} 只候选股票的撮合数据", flush=True)
    bars = reader.bars(symbols, calendar[0], calendar[-1], adjustment="pre")
    raw = reader.bars(symbols, calendar[0], calendar[-1], adjustment="qlib")
    market_state = build_market_state(raw, calendar, master, symbols)
    benchmark_bars = reader.bars([args.benchmark], calendar[0], calendar[-1], adjustment="pre")
    benchmark_returns = (
        benchmark_bars.set_index("trade_date")["close"].reindex(calendar).ffill().pct_change().fillna(0.0)
    )
    outputs = {}
    for model in args.models:
        print(f"运行 {model}", flush=True)
        outputs[model] = run_model(
            model,
            selections,
            market_regime,
            bars,
            market_state,
            calendar,
            benchmark_returns,
            args,
        )
        print(json.dumps(outputs[model]["metrics"], ensure_ascii=False, default=str), flush=True)
    result = archive(args, selections, market_regime, outputs)
    print(f"市场层消融归档：{result}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
