"""冻结 h18 选股与直接入场后，独立比较止损、趋势退出和赢家持有。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
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
    DailyBacktester,
    performance_metrics,
)
from quant_research.data.market_state import build_market_state  # noqa: E402
from quant_research.data.store import ResearchDataStore  # noqa: E402


MODELS = (
    "monthly-control",
    "hard-stop-8pct",
    "trend-exit-50d",
    "winner-hold-50d",
)
MODEL_TO_EXPERIMENT = {
    "monthly-control": "h18-control",
    "hard-stop-8pct": "h25",
    "trend-exit-50d": "h26",
    "winner-hold-50d": "h27",
}


class DirectQlibReader:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.features_dir = self.root / "features"
        values = [
            line.strip()
            for line in (self.root / "calendars" / "day.txt").read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]
        self.calendar = pd.DatetimeIndex(pd.to_datetime(values)).normalize()

    def feature(self, symbol: str, field: str) -> pd.Series:
        path = self.features_dir / symbol.lower() / f"{field.lower()}.day.bin"
        if not path.is_file():
            return pd.Series(dtype="float32")
        payload = np.fromfile(path, dtype="<f4")
        if payload.size < 2 or not np.isfinite(payload[0]):
            return pd.Series(dtype="float32")
        start = int(payload[0])
        values = payload[1:]
        return pd.Series(values, index=self.calendar[start : start + len(values)])

    def dates(self, start_date, end_date) -> pd.DatetimeIndex:
        return self.calendar[
            (self.calendar >= pd.Timestamp(start_date))
            & (self.calendar <= pd.Timestamp(end_date))
        ]

    def bars(self, symbols, start_date, end_date, adjustment="pre") -> pd.DataFrame:
        dates = self.dates(start_date, end_date)
        frames = []
        for symbol in symbols:
            data = {
                field: self.feature(symbol, field).reindex(dates)
                for field in ("open", "high", "low", "close", "volume", "factor")
            }
            frame = pd.DataFrame(data, index=dates)
            if adjustment == "pre":
                valid_factor = frame["factor"].dropna()
                denominator = valid_factor.iloc[-1] if not valid_factor.empty else np.nan
                for field in ("open", "high", "low", "close"):
                    frame[field] = frame[field] / denominator
            elif adjustment != "qlib":
                raise ValueError(f"unsupported adjustment: {adjustment}")
            frame["volume"] = frame["volume"] * 100.0
            frame["symbol"] = symbol
            frame["trade_date"] = dates
            frames.append(frame.reset_index(drop=True))
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def hard_stop_trigger(previous_close, average_cost, stop_loss=0.08) -> bool:
    if previous_close is None or average_cost is None:
        return False
    if not np.isfinite(previous_close) or not np.isfinite(average_cost) or average_cost <= 0:
        return False
    return float(previous_close) <= float(average_cost) * (1.0 - float(stop_loss))


def trend_exit_trigger(previous_close, moving_average) -> bool:
    if previous_close is None or moving_average is None:
        return False
    if not np.isfinite(previous_close) or not np.isfinite(moving_average):
        return False
    return float(previous_close) < float(moving_average)


def winner_hold_selection(
    held_symbols,
    ranked_candidates,
    trend_ok,
    maximum_positions=30,
):
    retained = [
        symbol
        for symbol in sorted(set(held_symbols))
        if bool(trend_ok.get(symbol, False))
    ][:maximum_positions]
    selected = list(retained)
    for symbol in ranked_candidates:
        if symbol not in selected:
            selected.append(symbol)
        if len(selected) >= maximum_positions:
            break
    return selected


def target_weights(symbols, exposure=0.95, maximum_weight=0.05):
    symbols = list(dict.fromkeys(symbols))
    if not symbols:
        return {}
    weight = min(float(maximum_weight), float(exposure) / len(symbols))
    return {symbol: weight for symbol in symbols}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_frozen_selections(paths, model="quality-growth-momentum"):
    frames = []
    for path in paths:
        frame = pd.read_csv(path, parse_dates=["trade_date", "observation_date"])
        frames.append(frame[frame["model"].eq(model)].copy())
    result = pd.concat(frames, ignore_index=True)
    return (
        result.drop_duplicates(["trade_date", "symbol"])
        .sort_values(["trade_date", "rank", "symbol"])
        .reset_index(drop=True)
    )


def period_metrics(returns: pd.Series) -> dict:
    values = pd.to_numeric(returns, errors="coerce").fillna(0.0)
    if values.empty:
        return {}
    curve = (1.0 + values).cumprod()
    years = max(len(values) / 252.0, 1.0 / 252.0)
    annualized = curve.iloc[-1] ** (1.0 / years) - 1.0
    volatility = values.std(ddof=1) * math.sqrt(252)
    drawdown = curve / curve.cummax() - 1.0
    maximum_drawdown = float(-drawdown.min())
    return {
        "total_return": float(curve.iloc[-1] - 1.0),
        "annualized_return": float(annualized),
        "maximum_drawdown": maximum_drawdown,
        "sharpe": float(values.mean() * 252 / volatility) if volatility > 0 else None,
        "calmar": float(annualized / maximum_drawdown) if maximum_drawdown > 0 else None,
    }


def _preserve_other_positions(engine, trade_date, sell_symbols):
    date = pd.Timestamp(trade_date).normalize()
    equity = engine.total_value(date, field="open")
    targets = {}
    if equity <= 0:
        return targets
    for symbol, position in engine.positions.items():
        if symbol in sell_symbols:
            continue
        price = engine._price_for_equity(date, symbol, "open")
        targets[symbol] = position.shares * price / equity
    return targets


def run_model(
    model,
    selections,
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
    monthly_dates = set(candidates)
    close = bars.pivot(index="trade_date", columns="symbol", values="close").reindex(
        calendar
    )
    moving_average_50 = close.rolling(50, min_periods=45).mean()
    excluded_until_refresh = set()

    def signal_sells(previous_date):
        if previous_date is None or model == "monthly-control":
            return set()
        sells = set()
        for symbol, position in engine.positions.items():
            previous_close = close.at[previous_date, symbol]
            if model == "hard-stop-8pct":
                if hard_stop_trigger(previous_close, position.average_cost, 0.08):
                    sells.add(symbol)
            elif trend_exit_trigger(
                previous_close, moving_average_50.at[previous_date, symbol]
            ):
                sells.add(symbol)
        return sells

    def targets(previous_date, trade_date):
        nonlocal excluded_until_refresh
        sells = signal_sells(previous_date)
        if trade_date in monthly_dates:
            excluded_until_refresh = set(sells)
            ranked = [
                symbol
                for symbol in candidates[trade_date]
                if symbol not in excluded_until_refresh
            ]
            if model == "winner-hold-50d":
                trend_ok = {}
                for symbol in engine.positions:
                    trend_ok[symbol] = (
                        symbol not in sells
                        and previous_date is not None
                        and not trend_exit_trigger(
                            close.at[previous_date, symbol],
                            moving_average_50.at[previous_date, symbol],
                        )
                    )
                selected = winner_hold_selection(
                    engine.positions,
                    ranked,
                    trend_ok,
                    maximum_positions=args.positions,
                )
            else:
                selected = ranked[: args.positions]
            return target_weights(selected, exposure=0.95, maximum_weight=0.05)
        if sells:
            excluded_until_refresh.update(sells)
            return _preserve_other_positions(engine, trade_date, sells)
        return None

    equity = engine.run(calendar, targets)
    returns = equity.set_index("trade_date")["daily_return"].reindex(calendar).fillna(0.0)
    metrics = performance_metrics(equity)
    gross_turnover = (
        engine.trades["gross_value"].sum() if not engine.trades.empty else 0.0
    )
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
        strategy_metrics = period_metrics(returns.reindex(dates))
        benchmark_metrics = period_metrics(benchmark_returns.reindex(dates))
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


def archive(args, selections, outputs):
    result_dir = Path(args.result_dir)
    if result_dir.exists():
        raise FileExistsError(f"不可覆盖已有实验：{result_dir}")
    raw_dir = result_dir / "raw"
    raw_dir.mkdir(parents=True)
    selections.to_csv(raw_dir / "frozen-selections.csv", index=False)
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
    shutil.copy2(source, result_dir / "source.py")
    shutil.copy2(ROOT / "src" / "quant_research" / "backtest.py", result_dir / "engine.py")
    manifest = {
        "schema_version": 1,
        "study": "oneil-canslim-a-share-rebuild",
        "stage": "holding-ablation",
        "candidate_model": "h18 quality-growth-momentum with direct entry",
        "period": "2010-01-01/2021-12-31",
        "models": list(outputs),
        "costs": {
            "commission": 0.0003,
            "minimum_commission": 5.0,
            "stamp_tax": "0.1% in this period",
            "slippage_rate": args.slippage_rate,
            "maximum_volume_ratio": args.maximum_volume_ratio,
        },
        "metrics": {model: output["metrics"] for model, output in outputs.items()},
        "source_file": "source.py",
        "source_sha256": sha256_file(result_dir / "source.py"),
        "engine_file": "engine.py",
        "engine_sha256": sha256_file(result_dir / "engine.py"),
        "selection_inputs": [
            {"path": str(Path(path).resolve()), "sha256": sha256_file(Path(path))}
            for path in args.selections
        ],
        "limitations": [
            "historical ST is unavailable and treated as unknown",
            "price limits use non-ST board-rule approximations",
            "2018-2021 is selection validation, not a pristine final holdout",
            "2022-2025 is intentionally excluded from this model-selection experiment",
        ],
    }
    (result_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# h18 持仓管理独立消融",
        "",
        "选股、月度候选、直接入场、成本和撮合完全相同，只比较持仓管理。日频退出均使用",
        "前一交易日收盘信号，在下一交易日开盘执行。",
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
            base
            / "2026-07-27__selection-alpha__quality-backward-confirmation-v4"
            / "raw"
            / "selections.csv",
            base
            / "2026-07-27__selection-alpha__quality-acceleration-v3"
            / "raw"
            / "selections.csv",
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
        default=base / "2026-07-27__holding-ablation__h18-v1",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    selections = load_frozen_selections(args.selections)
    symbols = sorted(selections["symbol"].unique())
    reader = DirectQlibReader(args.qlib_dir)
    calendar = reader.dates("2010-01-01", "2021-12-31")
    print(f"加载 {len(symbols)} 只候选股票的日线与交易状态", flush=True)
    bars = reader.bars(symbols, calendar[0], calendar[-1], adjustment="pre")
    raw = reader.bars(symbols, calendar[0], calendar[-1], adjustment="qlib")
    store = ResearchDataStore(args.data_root)
    master = store.read_parquet("security_master")
    market_state = build_market_state(raw, calendar, master, symbols)
    benchmark_bars = reader.bars(
        [args.benchmark], calendar[0], calendar[-1], adjustment="pre"
    )
    benchmark_returns = (
        benchmark_bars.set_index("trade_date")["close"].reindex(calendar).ffill().pct_change().fillna(0.0)
    )
    outputs = {}
    for model in args.models:
        print(f"运行 {model}", flush=True)
        outputs[model] = run_model(
            model,
            selections,
            bars,
            market_state,
            calendar,
            benchmark_returns,
            args,
        )
        print(json.dumps(outputs[model]["metrics"], ensure_ascii=False, default=str), flush=True)
    result = archive(args, selections, outputs)
    print(f"持仓消融归档：{result}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
