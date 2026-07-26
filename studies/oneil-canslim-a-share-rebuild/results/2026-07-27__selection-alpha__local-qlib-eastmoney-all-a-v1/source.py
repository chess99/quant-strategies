"""预注册的 CANSLIM 选股 Alpha 第一阶段：不使用图形入场和主动止损。"""

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
    "pure-growth",
    "pure-momentum",
    "growth-momentum",
    "huachuang-2-lite",
    "huachuang-2-risk-scaled",
)
MODEL_TO_EXPERIMENT = {
    "pure-growth": "h10",
    "pure-momentum": "h11",
    "growth-momentum": "h12",
    "huachuang-2-lite": "h13",
    "huachuang-2-risk-scaled": "h14",
}
ALL_A_BOARDS = {"main", "chinext", "star", "beijing"}
PRICE_EXPRESSIONS = (
    "$close",
    "Ref($close, 21)",
    "Ref($close, 252)",
    "Mean($amount, 20)",
)


class DirectQlibReader:
    """直接读取 Qlib 二进制，避免全市场表达式查询在 Windows 启动大量进程。"""

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
            elif adjustment == "raw":
                factor = frame["factor"].replace(0.0, np.nan)
                for field in ("open", "high", "low", "close"):
                    frame[field] = frame[field] / factor
            elif adjustment != "qlib":
                raise ValueError(f"unsupported adjustment: {adjustment}")
            frame["volume"] = frame["volume"] * 100.0
            frame["symbol"] = symbol
            frame["trade_date"] = dates
            frames.append(frame.reset_index(drop=True))
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_growth_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """把每份单季财报与严格上一年同季度比较；负基数不计算虚假增速。"""
    required = {
        "symbol",
        "report_date",
        "notice_date",
        "quarter_parent_net_profit",
        "quarter_revenue",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"fundamentals are missing columns: {sorted(missing)}")
    result = frame.copy()
    result["symbol"] = result["symbol"].astype("string").str.upper()
    result["report_date"] = pd.to_datetime(result["report_date"]).dt.normalize()
    result["notice_date"] = pd.to_datetime(result["notice_date"]).dt.normalize()
    result["fiscal_year"] = result["report_date"].dt.year
    result["fiscal_quarter"] = result["report_date"].dt.quarter
    result = result.sort_values(["symbol", "fiscal_quarter", "fiscal_year", "notice_date"])
    grouped = result.groupby(["symbol", "fiscal_quarter"], sort=False)
    previous_year = grouped["fiscal_year"].shift(1)
    previous_profit = grouped["quarter_parent_net_profit"].shift(1)
    previous_revenue = grouped["quarter_revenue"].shift(1)
    exact_year = previous_year.eq(result["fiscal_year"] - 1)
    current_profit = pd.to_numeric(result["quarter_parent_net_profit"], errors="coerce")
    current_revenue = pd.to_numeric(result["quarter_revenue"], errors="coerce")
    profit_valid = exact_year & current_profit.gt(0) & previous_profit.gt(0)
    revenue_valid = exact_year & current_revenue.gt(0) & previous_revenue.gt(0)
    result["profit_growth"] = np.where(
        profit_valid, current_profit / previous_profit - 1.0, np.nan
    )
    result["revenue_growth"] = np.where(
        revenue_valid, current_revenue / previous_revenue - 1.0, np.nan
    )
    return result.sort_values(["symbol", "report_date", "notice_date"]).reset_index(drop=True)


def latest_growth_snapshot(
    prepared: pd.DataFrame, observation_date, maximum_age_days: int = 220
) -> pd.DataFrame:
    date = pd.Timestamp(observation_date).normalize()
    visible = prepared[pd.to_datetime(prepared["notice_date"]).le(date)].copy()
    latest = (
        visible.sort_values(["symbol", "report_date", "notice_date"])
        .groupby("symbol", as_index=False)
        .tail(1)
    )
    age = (date - pd.to_datetime(latest["report_date"])).dt.days
    return latest.loc[age.le(maximum_age_days)].sort_values("symbol").reset_index(drop=True)


def _percentile(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").rank(pct=True, method="average")


def select_candidates(
    features: pd.DataFrame,
    model: str,
    positions: int = 30,
    percentile_cutoff: float = 0.80,
    liquidity_keep: float = 0.80,
) -> pd.DataFrame:
    if model not in MODELS:
        raise ValueError(f"unknown model: {model}")
    frame = features.copy()
    frame = frame.dropna(subset=["amount_20", "momentum_12_1"])
    frame["liquidity_rank"] = _percentile(frame["amount_20"])
    frame = frame[
        frame["liquidity_rank"].gt((1.0 - liquidity_keep) + 1e-12)
    ].copy()
    frame["profit_rank"] = _percentile(frame["profit_growth"])
    frame["revenue_rank"] = _percentile(frame["revenue_growth"])
    frame["growth_score"] = (frame["profit_rank"] + frame["revenue_rank"]) / 2.0
    frame["momentum_score"] = _percentile(frame["momentum_12_1"])
    frame["combined_score"] = (frame["growth_score"] + frame["momentum_score"]) / 2.0
    if model == "pure-growth":
        eligible = frame.dropna(subset=["growth_score"])
        score = "growth_score"
    elif model == "pure-momentum":
        eligible = frame
        score = "momentum_score"
    elif model == "growth-momentum":
        eligible = frame.dropna(subset=["combined_score"])
        score = "combined_score"
    else:
        eligible = frame[
            frame["growth_score"].ge(percentile_cutoff)
            & frame["momentum_score"].ge(percentile_cutoff)
        ]
        score = "combined_score"
    return (
        eligible.sort_values([score, "symbol"], ascending=[False, True])
        .head(positions)
        .reset_index(drop=True)
    )


def target_weights(symbols, exposure=0.95, maximum_weight=0.05) -> dict[str, float]:
    symbols = sorted(set(symbols))
    if not symbols:
        return {}
    weight = min(float(maximum_weight), float(exposure) / len(symbols))
    return {symbol: weight for symbol in symbols}


def market_exposure(close, moving_average, risk_on=0.95, risk_off=0.50) -> float:
    if pd.isna(close) or pd.isna(moving_average):
        return float(risk_off)
    return float(risk_on if float(close) >= float(moving_average) else risk_off)


def monthly_schedule(calendar: pd.DatetimeIndex, start_date, end_date) -> pd.DataFrame:
    calendar = pd.DatetimeIndex(calendar).normalize().sort_values().unique()
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    trade_dates = calendar[(calendar >= start) & (calendar <= end)]
    first = pd.Series(trade_dates, index=trade_dates).groupby(
        [trade_dates.year, trade_dates.month]
    ).first()
    rows = []
    for trade_date in first:
        location = calendar.searchsorted(trade_date, side="left") - 1
        if location >= 0:
            rows.append({"trade_date": trade_date, "observation_date": calendar[location]})
    return pd.DataFrame(rows)


def all_a_symbols(master: pd.DataFrame, start_date, end_date) -> list[str]:
    frame = master.copy()
    frame["start_date"] = pd.to_datetime(frame["start_date"])
    frame["end_date"] = pd.to_datetime(frame["end_date"])
    mask = (
        frame["asset_type"].eq("stock")
        & frame["board"].isin(ALL_A_BOARDS)
        & frame["start_date"].le(pd.Timestamp(end_date))
        & frame["end_date"].ge(pd.Timestamp(start_date))
    )
    return sorted(frame.loc[mask, "symbol"].unique().tolist())


def build_price_feature_cache(
    qlib_dir: Path,
    symbols: list[str],
    observation_dates,
    output_path: Path,
    chunk_size: int = 256,
) -> pd.DataFrame:
    reader = DirectQlibReader(qlib_dir)
    observations = pd.DatetimeIndex(observation_dates).normalize().sort_values().unique()
    frames = []
    for offset in range(0, len(symbols), chunk_size):
        chunk = symbols[offset : offset + chunk_size]
        print(
            f"读取价格特征：{offset + 1}-{min(offset + chunk_size, len(symbols))}/{len(symbols)}",
            flush=True,
        )
        for symbol in chunk:
            close = reader.feature(symbol, "close").reindex(reader.calendar)
            amount = reader.feature(symbol, "amount").reindex(reader.calendar)
            sample = pd.DataFrame(index=observations)
            sample["symbol"] = symbol
            sample["observation_date"] = observations
            sample["close"] = close.reindex(observations).to_numpy()
            sample["amount_20"] = amount.rolling(20, min_periods=15).mean().reindex(
                observations
            ).to_numpy()
            sample["momentum_12_1"] = (
                close.shift(21) / close.shift(252) - 1.0
            ).reindex(observations).to_numpy()
            frames.append(sample.reset_index(drop=True))
        print(f"价格特征：{min(offset + chunk_size, len(symbols))}/{len(symbols)}", flush=True)
    result = pd.concat(frames, ignore_index=True).sort_values(
        ["observation_date", "symbol"]
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(output_path, index=False)
    return result


def build_market_feature(qlib_dir: Path, observation_dates, index_symbol="SH000905"):
    reader = DirectQlibReader(qlib_dir)
    observations = pd.DatetimeIndex(observation_dates).normalize()
    close = reader.feature(index_symbol, "close").reindex(reader.calendar)
    return pd.DataFrame(
        {
            "observation_date": observations,
            "market_close": close.reindex(observations).to_numpy(),
            "market_ma200": close.rolling(200, min_periods=180).mean().reindex(
                observations
            ).to_numpy(),
        }
    )


def build_selections(
    schedule: pd.DataFrame,
    master: pd.DataFrame,
    growth_rows: pd.DataFrame,
    price_features: pd.DataFrame,
    models: tuple[str, ...],
    positions: int,
) -> pd.DataFrame:
    master = master.copy().set_index("symbol")
    master["start_date"] = pd.to_datetime(master["start_date"])
    master["end_date"] = pd.to_datetime(master["end_date"])
    price_by_date = {
        date: group.copy()
        for date, group in price_features.groupby("observation_date", sort=False)
    }
    records = []
    for row in schedule.itertuples(index=False):
        observation = pd.Timestamp(row.observation_date)
        price = price_by_date.get(observation, pd.DataFrame())
        if price.empty:
            continue
        active = master[
            master["start_date"].le(observation - pd.Timedelta(days=365))
            & master["end_date"].ge(observation)
        ].index
        growth = latest_growth_snapshot(growth_rows, observation, maximum_age_days=220)
        features = price[price["symbol"].isin(active)].merge(
            growth[
                [
                    "symbol",
                    "report_date",
                    "notice_date",
                    "profit_growth",
                    "revenue_growth",
                ]
            ],
            on="symbol",
            how="inner",
        )
        for model in models:
            selected = select_candidates(features, model, positions=positions)
            for rank, item in enumerate(selected.itertuples(index=False), 1):
                values = item._asdict()
                records.append(
                    {
                        "experiment_id": MODEL_TO_EXPERIMENT[model],
                        "model": model,
                        "trade_date": row.trade_date,
                        "observation_date": observation,
                        "rank": rank,
                        "candidate_count": len(selected),
                        **values,
                    }
                )
    return pd.DataFrame(records)


def _raw_market_features(qlib_dir: Path, symbols, start_date, end_date):
    return DirectQlibReader(qlib_dir).bars(
        list(symbols), start_date, end_date, adjustment="qlib"
    )


def _period_metrics(returns: pd.Series) -> dict:
    returns = pd.to_numeric(returns, errors="coerce").fillna(0.0)
    if returns.empty:
        return {}
    curve = (1.0 + returns).cumprod()
    years = max(len(returns) / 252.0, 1.0 / 252.0)
    annualized = curve.iloc[-1] ** (1.0 / years) - 1.0
    volatility = returns.std(ddof=1) * math.sqrt(252)
    drawdown = curve / curve.cummax() - 1.0
    return {
        "total_return": float(curve.iloc[-1] - 1.0),
        "annualized_return": float(annualized),
        "maximum_drawdown": float(-drawdown.min()),
        "sharpe": float(returns.mean() * 252 / volatility) if volatility > 0 else None,
    }


def run_models(args, schedule, master, selections, market_feature, calendar, reader):
    selected_symbols = sorted(selections["symbol"].unique())
    bars = reader.bars(selected_symbols, calendar[0], calendar[-1], adjustment="pre")
    bars = bars[["symbol", "trade_date", "open", "high", "low", "close", "volume"]]
    raw = _raw_market_features(args.qlib_dir, selected_symbols, calendar[0], calendar[-1])
    state = build_market_state(raw, calendar, master.reset_index(drop=True), selected_symbols)
    market_map = market_feature.set_index("observation_date").to_dict("index")
    selection_map = {
        (model, pd.Timestamp(date)): group.sort_values("rank")["symbol"].tolist()
        for (model, date), group in selections.groupby(["model", "trade_date"])
    }
    observation_map = schedule.set_index("trade_date")["observation_date"].to_dict()
    benchmark_bars = reader.bars(
        [args.benchmark], calendar[0], calendar[-1], adjustment="pre"
    )
    benchmark_close = (
        benchmark_bars.set_index("trade_date")["close"].reindex(calendar).ffill()
    )
    benchmark_returns = benchmark_close.pct_change().fillna(0.0)
    outputs = {}
    for model in args.models:
        engine = DailyBacktester(
            bars,
            state,
            asset_types={symbol: "stock" for symbol in selected_symbols},
            config=BacktestConfig(
                initial_cash=args.initial_cash,
                maximum_volume_ratio=args.maximum_volume_ratio,
                slippage_rate=args.slippage_rate,
                allow_unknown_st=True,
            ),
        )

        def targets(_, trade_date):
            symbols = selection_map.get((model, trade_date))
            if symbols is None:
                return None
            exposure = 0.95
            if model == "huachuang-2-risk-scaled":
                observation = observation_map[trade_date]
                market = market_map.get(observation, {})
                exposure = market_exposure(
                    market.get("market_close"), market.get("market_ma200")
                )
            return target_weights(symbols, exposure=exposure, maximum_weight=0.05)

        equity = engine.run(calendar, targets)
        metrics = performance_metrics(equity)
        strategy_returns = equity.set_index("trade_date")["daily_return"].reindex(calendar).fillna(0.0)
        yearly = []
        for year in sorted(set(calendar.year)):
            mask = calendar.year == year
            strategy_period = _period_metrics(strategy_returns.loc[calendar[mask]])
            benchmark_period = _period_metrics(benchmark_returns.loc[calendar[mask]])
            yearly.append(
                {
                    "model": model,
                    "year": year,
                    "strategy_return": strategy_period.get("total_return"),
                    "benchmark_return": benchmark_period.get("total_return"),
                    "excess_return": (
                        strategy_period.get("total_return", 0.0)
                        - benchmark_period.get("total_return", 0.0)
                    ),
                }
            )
        benchmark_metrics = _period_metrics(benchmark_returns)
        metrics["benchmark_total_return"] = benchmark_metrics["total_return"]
        metrics["benchmark_annualized_return"] = benchmark_metrics["annualized_return"]
        metrics["annualized_excess_return"] = (
            metrics["annualized_return"] - benchmark_metrics["annualized_return"]
        )
        metrics["positive_excess_year_ratio"] = float(
            np.mean([row["excess_return"] > 0 for row in yearly])
        )
        outputs[model] = {
            "metrics": metrics,
            "equity": equity,
            "orders": engine.orders,
            "trades": engine.trades,
            "holdings": engine.holdings,
            "yearly": pd.DataFrame(yearly),
        }
        print(model, json.dumps(metrics, ensure_ascii=False, default=str), flush=True)
    return outputs


def archive(args, outputs, selections, schedule, data_files) -> Path:
    result_dir = Path(args.result_dir)
    if result_dir.exists():
        raise FileExistsError(f"不可覆盖已有实验：{result_dir}")
    raw_dir = result_dir / "raw"
    raw_dir.mkdir(parents=True)
    comparison = []
    for model, output in outputs.items():
        output["equity"].to_csv(raw_dir / f"{model}__equity.csv", index=False)
        output["orders"].to_csv(raw_dir / f"{model}__orders.csv", index=False)
        output["trades"].to_csv(raw_dir / f"{model}__trades.csv", index=False)
        output["holdings"].to_csv(raw_dir / f"{model}__holdings.csv", index=False)
        output["yearly"].to_csv(raw_dir / f"{model}__yearly.csv", index=False)
        comparison.append({"model": model, **output["metrics"]})
    selections.to_csv(raw_dir / "selections.csv", index=False)
    schedule.to_csv(raw_dir / "schedule.csv", index=False)
    pd.DataFrame(comparison).to_csv(raw_dir / "comparison.csv", index=False)
    source = Path(__file__).resolve()
    shutil.copy2(source, result_dir / "source.py")
    source_hash = sha256_file(result_dir / "source.py")
    manifest = {
        "schema_version": 1,
        "study": "oneil-canslim-a-share-rebuild",
        "stage": "selection-alpha",
        "models": list(args.models),
        "period": {"start": args.start_date, "end": args.end_date},
        "benchmark": args.benchmark,
        "execution": "previous-session signal, next monthly open",
        "costs": {
            "commission": 0.0003,
            "minimum_commission": 5.0,
            "stamp_tax": "0.1% before 2023-08-28, 0.05% thereafter",
            "slippage_rate": args.slippage_rate,
            "maximum_volume_ratio": args.maximum_volume_ratio,
        },
        "metrics": {model: output["metrics"] for model, output in outputs.items()},
        "source_file": "source.py",
        "source_sha256": source_hash,
        "data_files": [
            {"path": str(Path(path).resolve()), "sha256": sha256_file(Path(path))}
            for path in data_files
        ],
        "limitations": [
            "historical ST is unavailable and treated as unknown",
            "price limits are derived under non-ST board rules",
            "financial revisions may be backfilled despite notice-date control",
            "earnings previews, quick reports, consensus and historical industry are unavailable",
            "2024-2025 is excluded from model selection",
        ],
    }
    (result_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# CANSLIM 重建：选股 Alpha 第一阶段",
        "",
        "本轮严格按预注册规则直接在次月首个交易日开盘买入，不使用图形突破、主动止损、",
        "加仓或行业条件。2024—2025 未参与本轮模型选择。",
        "",
        "| 模型 | 累计 | 年化 | 年化超额 | 最大回撤 | Sharpe | 正超额年份占比 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in comparison:
        lines.append(
            f"| {row['model']} | {row['total_return']:.2%} | {row['annualized_return']:.2%} | "
            f"{row['annualized_excess_return']:.2%} | {row['maximum_drawdown']:.2%} | "
            f"{row['sharpe']:.3f} | {row['positive_excess_year_ratio']:.1%} |"
        )
    lines.extend(
        [
            "",
            "本报告只判断选股层是否有继续研究价值。任何模型即使全区间领先，也必须继续完成",
            "滚动窗口、成本、前五贡献剔除、参数扰动和行业剔除，才能进入下一阶段。",
        ]
    )
    (result_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result_dir


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qlib-dir", type=Path, default=Path("D:/code/_open-source/_data/qlib/cn_data"))
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument(
        "--financials",
        type=Path,
        default=Path("D:/code/_open-source/_data/oneil-all-a/financials.parquet"),
    )
    parser.add_argument(
        "--price-feature-cache",
        type=Path,
        default=Path("D:/code/_open-source/_data/oneil-rebuild/monthly-price-features.parquet"),
    )
    parser.add_argument("--rebuild-price-cache", action="store_true")
    parser.add_argument("--start-date", default="2015-01-01")
    parser.add_argument("--end-date", default="2023-12-31")
    parser.add_argument("--benchmark", default="SH000905")
    parser.add_argument("--models", nargs="+", choices=MODELS, default=list(MODELS))
    parser.add_argument("--positions", type=int, default=30)
    parser.add_argument("--initial-cash", type=float, default=10_000_000.0)
    parser.add_argument("--slippage-rate", type=float, default=0.001)
    parser.add_argument("--maximum-volume-ratio", type=float, default=0.10)
    parser.add_argument(
        "--result-dir",
        type=Path,
        default=Path(__file__).resolve().parent
        / "results"
        / "2026-07-27__selection-alpha__local-qlib-eastmoney-all-a-v1",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print("加载证券主表与交易日历", flush=True)
    store = ResearchDataStore(args.data_root)
    master = store.read_parquet("security_master")
    reader = DirectQlibReader(args.qlib_dir)
    full_calendar = reader.dates("2009-01-01", args.end_date)
    schedule = monthly_schedule(full_calendar, args.start_date, args.end_date)
    symbols = all_a_symbols(master, args.start_date, args.end_date)
    print(f"月度观察日 {len(schedule)} 个，全A区间股票 {len(symbols)} 只", flush=True)
    if args.rebuild_price_cache or not args.price_feature_cache.is_file():
        price_features = build_price_feature_cache(
            args.qlib_dir,
            symbols,
            schedule["observation_date"],
            args.price_feature_cache,
        )
    else:
        price_features = pd.read_parquet(args.price_feature_cache)
        price_features["observation_date"] = pd.to_datetime(
            price_features["observation_date"]
        ).dt.normalize()
    fundamentals = pd.read_parquet(args.financials)
    print(f"加载财务 {len(fundamentals)} 行", flush=True)
    growth_rows = prepare_growth_rows(fundamentals)
    market_feature = build_market_feature(args.qlib_dir, schedule["observation_date"])
    selections = build_selections(
        schedule, master, growth_rows, price_features, tuple(args.models), args.positions
    )
    print(f"生成候选记录 {len(selections)} 行", flush=True)
    calendar = reader.dates(args.start_date, args.end_date)
    outputs = run_models(
        args,
        schedule,
        master,
        selections,
        market_feature,
        calendar,
        reader,
    )
    result = archive(
        args,
        outputs,
        selections,
        schedule,
        [args.financials, args.price_feature_cache, store.manifest_path("security_master")],
    )
    print(f"归档完成：{result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
