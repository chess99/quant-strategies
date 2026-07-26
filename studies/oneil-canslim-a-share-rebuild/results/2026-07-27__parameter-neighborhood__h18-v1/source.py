"""对冻结 h18 执行质量权重、持股数、年报新鲜度和流动性邻域验收。"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quant_research.data.store import ResearchDataStore  # noqa: E402


def _load_selection_module():
    path = Path(__file__).with_name("run_selection_alpha.py")
    if not path.is_file():
        path = Path(__file__).with_name("selection_engine.py")
    spec = importlib.util.spec_from_file_location("oneil_parameter_selection", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SELECTION = _load_selection_module()


def parameter_grid():
    base = {
        "positions": 30,
        "quality_maximum_age_days": 550,
        "liquidity_keep": 0.80,
        "growth_weight": 1.0 / 3.0,
        "momentum_weight": 1.0 / 3.0,
        "quality_weight": 1.0 / 3.0,
    }
    return {
        "base": dict(base),
        "quality-25pct": {
            **base,
            "growth_weight": 0.375,
            "momentum_weight": 0.375,
            "quality_weight": 0.25,
        },
        "quality-40pct": {
            **base,
            "growth_weight": 0.30,
            "momentum_weight": 0.30,
            "quality_weight": 0.40,
        },
        "positions-20": {**base, "positions": 20},
        "positions-40": {**base, "positions": 40},
        "quality-age-450": {**base, "quality_maximum_age_days": 450},
        "quality-age-650": {**base, "quality_maximum_age_days": 650},
        "liquidity-70pct": {**base, "liquidity_keep": 0.70},
        "liquidity-90pct": {**base, "liquidity_keep": 0.90},
    }


def build_parameter_selections(schedule, master, growth_rows, price_features):
    frames = []
    for name, config in parameter_grid().items():
        print(f"生成参数候选 {name}", flush=True)
        selected = SELECTION.build_selections(
            schedule,
            master,
            growth_rows,
            price_features,
            ("quality-growth-momentum",),
            config["positions"],
            quality_maximum_age_days=config["quality_maximum_age_days"],
            selection_options={
                "quality-growth-momentum": {
                    "liquidity_keep": config["liquidity_keep"],
                    "growth_weight": config["growth_weight"],
                    "momentum_weight": config["momentum_weight"],
                    "quality_weight": config["quality_weight"],
                }
            },
        )
        selected["model"] = name
        selected["experiment_id"] = "robustness-01"
        frames.append(selected)
    return pd.concat(frames, ignore_index=True)


def segment_metrics(outputs, benchmark_returns, calendar):
    rows = []
    for name, output in outputs.items():
        strategy_returns = (
            output["equity"].set_index("trade_date")["daily_return"].reindex(calendar).fillna(0.0)
        )
        for period, start, end in (
            ("development", "2010-01-01", "2017-12-31"),
            ("selection-validation", "2018-01-01", "2021-12-31"),
            ("full", "2010-01-01", "2021-12-31"),
        ):
            dates = calendar[(calendar >= start) & (calendar <= end)]
            strategy = SELECTION._period_metrics(strategy_returns.reindex(dates))
            benchmark = SELECTION._period_metrics(benchmark_returns.reindex(dates))
            rows.append(
                {
                    "configuration": name,
                    "period": period,
                    **strategy,
                    "benchmark_total_return": benchmark["total_return"],
                    "benchmark_annualized_return": benchmark["annualized_return"],
                    "annualized_excess_return": strategy["annualized_return"]
                    - benchmark["annualized_return"],
                }
            )
    return pd.DataFrame(rows)


def archive(args, selections, outputs, segments):
    result_dir = Path(args.result_dir)
    if result_dir.exists():
        raise FileExistsError(f"不可覆盖已有验收：{result_dir}")
    raw_dir = result_dir / "raw"
    raw_dir.mkdir(parents=True)
    selections.to_csv(raw_dir / "selections.csv", index=False)
    segments.to_csv(raw_dir / "segments.csv", index=False)
    comparison = []
    for name, output in outputs.items():
        output["equity"].to_csv(raw_dir / f"{name}__equity.csv", index=False)
        output["trades"].to_csv(raw_dir / f"{name}__trades.csv", index=False)
        comparison.append({"configuration": name, **output["metrics"]})
    pd.DataFrame(comparison).to_csv(raw_dir / "comparison.csv", index=False)
    source = Path(__file__).resolve()
    selection_source = Path(__file__).with_name("run_selection_alpha.py")
    shutil.copy2(source, result_dir / "source.py")
    shutil.copy2(selection_source, result_dir / "selection_engine.py")
    manifest = {
        "schema_version": 1,
        "study": "oneil-canslim-a-share-rebuild",
        "stage": "parameter-neighborhood",
        "candidate": "h18",
        "period": "2010-01-01/2021-12-31",
        "grid": parameter_grid(),
        "metrics": {name: output["metrics"] for name, output in outputs.items()},
        "source_file": "source.py",
        "source_sha256": SELECTION.sha256_file(result_dir / "source.py"),
    }
    (result_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# h18 参数邻域验收",
        "",
        "每次只扰动一个参数，未重新选择默认点。",
        "",
        "| 配置 | 阶段 | 年化 | 年化超额 | 最大回撤 | Sharpe |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in segments.itertuples(index=False):
        lines.append(
            f"| {row.configuration} | {row.period} | {row.annualized_return:.2%} | "
            f"{row.annualized_excess_return:.2%} | {row.maximum_drawdown:.2%} | "
            f"{row.sharpe:.3f} |"
        )
    (result_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result_dir


def parse_args():
    base = Path(__file__).resolve().parent / "results"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qlib-dir", type=Path, default=Path("D:/code/_open-source/_data/qlib/cn_data"))
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument(
        "--financials", type=Path, default=Path("D:/code/_open-source/_data/oneil-all-a/financials.parquet")
    )
    parser.add_argument(
        "--price-feature-caches",
        nargs="+",
        type=Path,
        default=[
            Path("D:/code/_open-source/_data/oneil-rebuild/monthly-price-features-2010-2014.parquet"),
            Path("D:/code/_open-source/_data/oneil-rebuild/monthly-price-features.parquet"),
        ],
    )
    parser.add_argument("--benchmark", default="SH000905")
    parser.add_argument("--initial-cash", type=float, default=10_000_000.0)
    parser.add_argument("--slippage-rate", type=float, default=0.001)
    parser.add_argument("--maximum-volume-ratio", type=float, default=0.10)
    parser.add_argument(
        "--result-dir",
        type=Path,
        default=base / "2026-07-27__parameter-neighborhood__h18-v1",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    store = ResearchDataStore(args.data_root)
    master = store.read_parquet("security_master")
    reader = SELECTION.DirectQlibReader(args.qlib_dir)
    calendar = reader.dates("2010-01-01", "2021-12-31")
    full_calendar = reader.dates("2009-01-01", "2021-12-31")
    schedule = SELECTION.monthly_schedule(full_calendar, "2010-01-01", "2021-12-31")
    price_features = pd.concat(
        [pd.read_parquet(path) for path in args.price_feature_caches], ignore_index=True
    )
    price_features["observation_date"] = pd.to_datetime(
        price_features["observation_date"]
    ).dt.normalize()
    price_features = price_features[
        price_features["observation_date"].isin(schedule["observation_date"])
    ].drop_duplicates(["observation_date", "symbol"])
    growth_rows = SELECTION.prepare_growth_rows(pd.read_parquet(args.financials))
    selections = build_parameter_selections(
        schedule, master, growth_rows, price_features
    )
    run_args = SimpleNamespace(
        qlib_dir=args.qlib_dir,
        benchmark=args.benchmark,
        models=list(parameter_grid()),
        initial_cash=args.initial_cash,
        maximum_volume_ratio=args.maximum_volume_ratio,
        slippage_rate=args.slippage_rate,
    )
    market_feature = SELECTION.build_market_feature(
        args.qlib_dir, schedule["observation_date"]
    )
    outputs = SELECTION.run_models(
        run_args,
        schedule,
        master,
        selections,
        market_feature,
        calendar,
        reader,
    )
    benchmark_bars = reader.bars([args.benchmark], calendar[0], calendar[-1], adjustment="pre")
    benchmark_returns = (
        benchmark_bars.set_index("trade_date")["close"].reindex(calendar).ffill().pct_change().fillna(0.0)
    )
    segments = segment_metrics(outputs, benchmark_returns, calendar)
    result = archive(args, selections, outputs, segments)
    print(f"参数邻域归档：{result}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
