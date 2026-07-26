"""汇总 h18 的滚动验证、Deflated Sharpe Ratio 与参数邻域 PBO。"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kurtosis, norm, skew


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sharpe(returns):
    values = pd.to_numeric(pd.Series(returns), errors="coerce").dropna()
    standard_deviation = values.std(ddof=1)
    return float(values.mean() / standard_deviation) if standard_deviation > 0 else np.nan


def deflated_sharpe(returns, trials=30):
    values = pd.to_numeric(pd.Series(returns), errors="coerce").dropna()
    observed = _sharpe(values)
    sample_size = len(values)
    sample_skew = float(skew(values, bias=False))
    sample_kurtosis = float(kurtosis(values, fisher=False, bias=False))
    variance = (
        1.0
        - sample_skew * observed
        + ((sample_kurtosis - 1.0) / 4.0) * observed * observed
    ) / max(sample_size - 1, 1)
    standard_error = math.sqrt(max(variance, 1.0e-16))
    euler_gamma = 0.5772156649015329
    expected_maximum = (1.0 - euler_gamma) * norm.ppf(1.0 - 1.0 / trials)
    expected_maximum += euler_gamma * norm.ppf(
        1.0 - 1.0 / (trials * math.e)
    )
    deflated_threshold = expected_maximum * standard_error
    probability = norm.cdf((observed - deflated_threshold) / standard_error)
    return {
        "daily_sharpe": observed,
        "annualized_sharpe": observed * math.sqrt(252),
        "deflated_threshold_daily": deflated_threshold,
        "probability": float(probability),
        "trials": int(trials),
        "observations": sample_size,
        "skew": sample_skew,
        "kurtosis": sample_kurtosis,
    }


def rolling_windows(start_year=2010, end_year=2026):
    windows = []
    anchor = start_year
    while anchor + 5 <= end_year:
        training = list(range(anchor, min(anchor + 5, end_year + 1)))
        validation = list(range(anchor + 5, min(anchor + 7, end_year + 1)))
        if len(training) == 5 and validation:
            windows.append(
                {"training_years": training, "validation_years": validation}
            )
        anchor += 2
    return windows


def period_metrics(returns):
    values = pd.to_numeric(pd.Series(returns), errors="coerce").fillna(0.0)
    curve = (1.0 + values).cumprod()
    years = max(len(values) / 252.0, 1.0 / 252.0)
    annualized = curve.iloc[-1] ** (1.0 / years) - 1.0
    drawdown = curve / curve.cummax() - 1.0
    volatility = values.std(ddof=1) * math.sqrt(252)
    return {
        "total_return": float(curve.iloc[-1] - 1.0),
        "annualized_return": float(annualized),
        "maximum_drawdown": float(-drawdown.min()),
        "sharpe": float(values.mean() * 252 / volatility) if volatility > 0 else None,
    }


def cscv_pbo(return_matrix: pd.DataFrame):
    years = sorted(return_matrix.index.year.unique())
    if len(years) < 4:
        raise ValueError("PBO requires at least four annual blocks")
    half = len(years) // 2
    records = []
    configurations = list(return_matrix.columns)
    for in_sample_years in itertools.combinations(years, half):
        in_sample_years = set(in_sample_years)
        out_sample_years = [year for year in years if year not in in_sample_years]
        in_sample = return_matrix[return_matrix.index.year.isin(in_sample_years)]
        out_sample = return_matrix[return_matrix.index.year.isin(out_sample_years)]
        in_scores = in_sample.apply(_sharpe)
        selected = in_scores.idxmax()
        out_scores = out_sample.apply(_sharpe).sort_values()
        ascending_rank = int(out_scores.index.get_loc(selected)) + 1
        relative_rank = ascending_rank / float(len(configurations) + 1)
        logit = math.log(relative_rank / (1.0 - relative_rank))
        records.append(
            {
                "selected": selected,
                "out_sample_rank_ascending": ascending_rank,
                "relative_rank": relative_rank,
                "logit": logit,
                "below_median": logit <= 0.0,
            }
        )
    frame = pd.DataFrame(records)
    return float(frame["below_median"].mean()), frame


def load_equity_returns(path):
    frame = pd.read_csv(path, parse_dates=["trade_date"])
    return frame.set_index("trade_date")["daily_return"].sort_index()


def parse_args():
    base = Path(__file__).resolve().parent / "results"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--standard-equity",
        type=Path,
        default=base / "2026-07-27__acceptance-stress__h18-v1" / "raw" / "standard__equity.csv",
    )
    parser.add_argument(
        "--extension-equity",
        type=Path,
        default=base / "2026-07-27__time-extension__h18-v5" / "raw" / "quality-growth-momentum__equity.csv",
    )
    parser.add_argument(
        "--parameter-result",
        type=Path,
        default=base / "2026-07-27__parameter-neighborhood__h18-v1",
    )
    parser.add_argument(
        "--qlib-dir", type=Path, default=Path("D:/code/_open-source/_data/qlib/cn_data")
    )
    parser.add_argument(
        "--result-dir",
        type=Path,
        default=base / "2026-07-27__validation-audit__h18-v1",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    standard = load_equity_returns(args.standard_equity)
    extension = load_equity_returns(args.extension_equity)
    strategy = pd.concat([standard, extension]).sort_index()
    strategy = strategy[~strategy.index.duplicated(keep="last")]
    calendar_path = Path(args.qlib_dir) / "calendars" / "day.txt"
    calendar = pd.DatetimeIndex(
        pd.to_datetime(calendar_path.read_text(encoding="utf-8").splitlines())
    )
    calendar = calendar[(calendar >= strategy.index.min()) & (calendar <= strategy.index.max())]
    # The benchmark return series is reconstructed from the archived yearly files to avoid
    # introducing a different price-adjustment implementation in the statistical audit.
    yearly_a = pd.read_csv(Path(args.standard_equity).with_name("yearly.csv")) if False else None
    parameter_files = sorted((Path(args.parameter_result) / "raw").glob("*__equity.csv"))
    parameter_returns = {
        path.name.replace("__equity.csv", ""): load_equity_returns(path)
        for path in parameter_files
    }
    matrix = pd.concat(parameter_returns, axis=1).dropna(how="all").fillna(0.0)
    pbo, pbo_records = cscv_pbo(matrix)
    dsr = deflated_sharpe(standard, trials=30)

    benchmark_yearly = pd.concat(
        [
            pd.read_csv(
                Path(args.standard_equity).parents[0] / "yearly.csv"
            )
            if (Path(args.standard_equity).parents[0] / "yearly.csv").is_file()
            else pd.DataFrame(),
            pd.read_csv(
                Path(args.extension_equity).with_name("quality-growth-momentum__yearly.csv")
            ),
        ],
        ignore_index=True,
    )
    if benchmark_yearly.empty or "benchmark_return" not in benchmark_yearly:
        acceptance_yearly = pd.read_csv(
            Path(args.standard_equity).with_name("yearly.csv")
        )
        benchmark_yearly = acceptance_yearly[
            acceptance_yearly["variant"].eq("standard")
        ]
    benchmark_by_year = benchmark_yearly.drop_duplicates("year").set_index("year")[
        "benchmark_return"
    ].to_dict()
    windows = rolling_windows(2010, int(strategy.index.max().year))
    validation_years = sorted(
        {year for window in windows for year in window["validation_years"]}
    )
    stitched = strategy[strategy.index.year.isin(validation_years)]
    stitched_metrics = period_metrics(stitched)
    strategy_yearly = stitched.groupby(stitched.index.year).agg(
        lambda values: (1.0 + values).prod() - 1.0
    )
    positive_excess = []
    rolling_rows = []
    for window in windows:
        years = window["validation_years"]
        values = strategy[strategy.index.year.isin(years)]
        metrics = period_metrics(values)
        benchmark_total = np.prod(
            [1.0 + benchmark_by_year.get(year, 0.0) for year in years]
        ) - 1.0
        rolling_rows.append(
            {
                "training_years": "-".join(map(str, window["training_years"])),
                "validation_years": "-".join(map(str, years)),
                **metrics,
                "benchmark_total_return": benchmark_total,
                "excess_total_return": metrics["total_return"] - benchmark_total,
            }
        )
    for year, value in strategy_yearly.items():
        positive_excess.append(value > benchmark_by_year.get(int(year), 0.0))
    stitched_metrics["positive_excess_year_ratio"] = float(np.mean(positive_excess))
    benchmark_stitched_total = np.prod(
        [1.0 + benchmark_by_year.get(year, 0.0) for year in validation_years]
    ) - 1.0
    stitched_years = max(len(stitched) / 252.0, 1.0 / 252.0)
    benchmark_stitched_annualized = (1.0 + benchmark_stitched_total) ** (
        1.0 / stitched_years
    ) - 1.0
    stitched_metrics["benchmark_total_return"] = float(benchmark_stitched_total)
    stitched_metrics["benchmark_annualized_return"] = float(
        benchmark_stitched_annualized
    )
    stitched_metrics["annualized_excess_return"] = (
        stitched_metrics["annualized_return"] - benchmark_stitched_annualized
    )

    result_dir = Path(args.result_dir)
    if result_dir.exists():
        raise FileExistsError(f"不可覆盖已有审计：{result_dir}")
    raw_dir = result_dir / "raw"
    raw_dir.mkdir(parents=True)
    pd.DataFrame(rolling_rows).to_csv(raw_dir / "rolling-windows.csv", index=False)
    pbo_records.to_csv(raw_dir / "pbo-records.csv", index=False)
    source = Path(__file__).resolve()
    shutil.copy2(source, result_dir / "source.py")
    manifest = {
        "schema_version": 1,
        "study": "oneil-canslim-a-share-rebuild",
        "stage": "validation-and-overfitting-audit",
        "rolling_stitched": stitched_metrics,
        "deflated_sharpe": dsr,
        "pbo": pbo,
        "pbo_splits": len(pbo_records),
        "source_file": "source.py",
        "source_sha256": sha256_file(result_dir / "source.py"),
        "limitations": [
            "rolling windows audit a fixed rule; early windows are not pristine researcher-level OOS",
            "PBO uses highly correlated local parameter-neighborhood configurations and is diagnostic",
            "2026 is a partial year through 2026-07-23",
        ],
    }
    (result_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# h18 滚动与过拟合风险审计",
        "",
        f"- 滚动拼接年化：{stitched_metrics['annualized_return']:.2%}；年化超额：{stitched_metrics['annualized_excess_return']:.2%}；正超额年份：{stitched_metrics['positive_excess_year_ratio']:.1%}。",
        f"- Deflated Sharpe 概率（30 次独立假设折扣）：{dsr['probability']:.2%}。",
        f"- 9 配置、12 年度区块 CSCV PBO：{pbo:.2%}（{len(pbo_records)} 个切分）。",
        "",
        "滚动窗口对固定规则做时间稳定性审计，但不能把研究人员已经看过的早期年份重新",
        "变成干净样本外；PBO 也只覆盖邻域配置，不能消除数据修订风险。",
    ]
    (result_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
