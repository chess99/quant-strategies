"""复现聚宽帖子 42673 的四资产 ETF 动量轮动。"""

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


STUDY_DIR = Path(__file__).resolve().parent
ROOT = STUDY_DIR.parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quant_research.data.store import ResearchDataStore, sha256_file  # noqa: E402


SOURCE_PATH = (
    ROOT
    / "joinquant_post_crawler"
    / "sources"
    / "2024年度精选策略"
    / "3.【回顾3】ETF策略之核心资产轮动.py"
)
ETF_SYMBOLS = ("SH518880", "SH513100", "SZ159915", "SH510180")
START_DATE = pd.Timestamp("2014-01-01")
END_DATE = pd.Timestamp("2023-06-09")
INITIAL_CASH = 100_000.0
JQ_METRICS = {
    "total_return": 16.95179316,
    "annualized_return": 0.3692858,
    "benchmark_total_return": 0.64663116,
    "benchmark_annualized_return": 0.05578097,
    "max_drawdown": 0.30612221,
    "sharpe": 1.337019315484,
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def momentum_score(close: pd.Series) -> float:
    values = close.dropna().to_numpy(dtype=float)
    if len(values) != 25 or np.any(values <= 0.0):
        return np.nan
    y = np.log(values)
    x = np.arange(len(y), dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    fitted = slope * x + intercept
    denominator = float(np.sum((y - y.mean()) ** 2))
    if denominator <= 0.0:
        return np.nan
    r_squared = 1.0 - float(np.sum((y - fitted) ** 2)) / denominator
    annualized_return = math.exp(slope * 250.0) - 1.0
    return float(annualized_return * r_squared)


def build_daily_targets(bars: pd.DataFrame) -> tuple[pd.Series, pd.DataFrame]:
    close = bars.pivot(index="trade_date", columns="symbol", values="adjusted_close")
    score_rows = []
    observation_target = []
    for date in close.index:
        scores = {
            symbol: momentum_score(close.loc[:date, symbol].tail(25))
            for symbol in ETF_SYMBOLS
        }
        valid = [(symbol, value) for symbol, value in scores.items() if np.isfinite(value)]
        valid.sort(key=lambda item: (-item[1], item[0]))
        observation_target.append(valid[0][0] if valid else None)
        score_rows.append({"trade_date": date, **scores})
    targets = pd.Series(observation_target, index=close.index, dtype="string")
    targets = targets.shift(1).rename("target")
    scores = pd.DataFrame(score_rows).set_index("trade_date")
    return targets, scores


def _commission(gross: float) -> float:
    return max(gross * 0.0002, 5.0) if gross > 0.0 else 0.0


def simulate_rotation(
    bars: pd.DataFrame,
    targets: pd.Series,
    initial_cash: float = INITIAL_CASH,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    opens = bars.pivot(index="trade_date", columns="symbol", values="adjusted_open")
    closes = bars.pivot(index="trade_date", columns="symbol", values="adjusted_close").ffill()
    dates = opens.index.intersection(targets.index)
    cash = float(initial_cash)
    held_symbol = None
    units = 0.0
    equity_rows = []
    trade_rows = []

    for date in dates:
        target = targets.loc[date]
        target = None if pd.isna(target) else str(target)
        gross_traded = 0.0
        if held_symbol and target != held_symbol:
            price = float(opens.loc[date, held_symbol])
            if np.isfinite(price) and price > 0.0:
                gross = units * price
                fee = _commission(gross)
                cash += gross - fee
                gross_traded += gross
                trade_rows.append(
                    {
                        "date": date,
                        "side": "sell",
                        "symbol": held_symbol,
                        "price": price,
                        "units": units,
                        "gross": gross,
                        "commission": fee,
                    }
                )
                held_symbol = None
                units = 0.0
        if target and held_symbol is None:
            price = float(opens.loc[date, target])
            if np.isfinite(price) and price > 0.0:
                affordable = max(cash - 5.0, 0.0) / (price * 1.0002)
                buy_units = math.floor(affordable / 100.0) * 100.0
                gross = buy_units * price
                fee = _commission(gross)
                if buy_units > 0.0 and gross + fee <= cash:
                    cash -= gross + fee
                    held_symbol = target
                    units = buy_units
                    gross_traded += gross
                    trade_rows.append(
                        {
                            "date": date,
                            "side": "buy",
                            "symbol": target,
                            "price": price,
                            "units": units,
                            "gross": gross,
                            "commission": fee,
                        }
                    )
        market_value = (
            units * float(closes.loc[date, held_symbol]) if held_symbol else 0.0
        )
        equity_rows.append(
            {
                "date": date,
                "equity": cash + market_value,
                "cash": cash,
                "market_value": market_value,
                "held_symbol": held_symbol,
                "units": units,
                "gross_traded": gross_traded,
            }
        )
    return (
        pd.DataFrame(equity_rows).set_index("date"),
        pd.DataFrame(trade_rows),
    )


def load_benchmark(data_root: Path, dates: pd.DatetimeIndex) -> pd.Series:
    import qlib
    from qlib.data import D

    qlib_dir = data_root.parent / "qlib" / "cn_data"
    if not qlib_dir.is_dir():
        qlib_dir = Path("D:/code/_open-source/_data/qlib/cn_data")
    qlib.init(
        provider_uri=str(qlib_dir),
        region="cn",
        kernels=1,
        joblib_backend="threading",
    )
    prefix = "$"
    frame = D.features(
        ["SH000300"],
        [prefix + "open", prefix + "close"],
        start_time=dates.min(),
        end_time=dates.max(),
        freq="day",
    ).xs("SH000300", level="instrument")
    frame.index = pd.DatetimeIndex(frame.index).normalize()
    frame = frame.reindex(dates).ffill()
    return (frame[prefix + "close"] / float(frame[prefix + "open"].iloc[0])).rename(
        "benchmark_value"
    )


def calculate_metrics(equity: pd.DataFrame, benchmark: pd.Series) -> dict:
    values = equity["equity"]
    returns = values.pct_change(fill_method=None)
    returns.iloc[0] = values.iloc[0] / INITIAL_CASH - 1.0
    total_return = float(values.iloc[-1] / INITIAL_CASH - 1.0)
    annualized = float((1.0 + total_return) ** (250.0 / len(values)) - 1.0)
    drawdown = values / values.cummax() - 1.0
    volatility = float(returns.std(ddof=1) * math.sqrt(250.0))
    sharpe = float(returns.mean() / returns.std(ddof=1) * math.sqrt(250.0))
    benchmark_total = float(benchmark.iloc[-1] - 1.0)
    benchmark_annual = float(
        (1.0 + benchmark_total) ** (250.0 / len(benchmark)) - 1.0
    )
    underwater = drawdown < -1e-12
    longest = current = 0
    for flag in underwater:
        current = current + 1 if flag else 0
        longest = max(longest, current)
    return {
        "trading_days": len(values),
        "total_return": total_return,
        "annualized_return": annualized,
        "benchmark_total_return": benchmark_total,
        "benchmark_annualized_return": benchmark_annual,
        "max_drawdown": float(-drawdown.min()),
        "sharpe": sharpe,
        "annualized_volatility": volatility,
        "turnover": float(equity["gross_traded"].sum() / values.mean()),
        "average_cash_ratio": float((equity["cash"] / values).mean()),
        "longest_underwater_trading_days": longest,
    }


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    return value


def build_report(metrics: dict, trade_count: int, run_id: str) -> str:
    annual_delta = (metrics["annualized_return"] - JQ_METRICS["annualized_return"]) * 100
    drawdown_delta = (metrics["max_drawdown"] - JQ_METRICS["max_drawdown"]) * 100
    benchmark_delta = (
        metrics["benchmark_annualized_return"]
        - JQ_METRICS["benchmark_annualized_return"]
    ) * 100
    verdict = (
        "近似复现"
        if abs(annual_delta) <= 5.0 and abs(drawdown_delta) <= 5.0
        else "存在实质差异"
    )
    return f"""# 核心资产 ETF 轮动本地复现

## 结论

按年化收益与最大回撤各 ±5 个百分点的事前标准，本次判断为：**{verdict}**。

| 指标 | 聚宽 | 本地 | 差值 |
|---|---:|---:|---:|
| 年化收益 | {JQ_METRICS['annualized_return']:.2%} | {metrics['annualized_return']:.2%} | {annual_delta:+.2f} pp |
| 最大回撤 | {JQ_METRICS['max_drawdown']:.2%} | {metrics['max_drawdown']:.2%} | {drawdown_delta:+.2f} pp |
| Sharpe | {JQ_METRICS['sharpe']:.2f} | {metrics['sharpe']:.2f} | {metrics['sharpe'] - JQ_METRICS['sharpe']:+.2f} |
| 基准年化 | {JQ_METRICS['benchmark_annualized_return']:.2%} | {metrics['benchmark_annualized_return']:.2%} | {benchmark_delta:+.2f} pp |

## 事实

- 运行标识：`{run_id}`
- 区间：2014-01-01 至 2023-06-09
- 初始资金：100,000 元
- 交易指令：{trade_count}
- 换手：{metrics['turnover']:.2f}
- 最长水下期：{metrics['longest_underwater_trading_days']} 个交易日
- 平均现金比例：{metrics['average_cash_ratio']:.2%}
- ETF 行情：新浪日线；现金分红和常见份额拆分/合并构造总收益调整因子；质量 B。
- 基准：Qlib 沪深300。
- 信号只使用前一交易日及更早的 25 条收盘价，下一交易日开盘成交。

## 限制

- 新浪接口不直接提供 ETF 份额拆分因子；本地只识别能恢复正常收益的常见整数倍率。
- 聚宽动态复权与本地现金分红总收益因子不保证逐日完全一致。
- 本地使用 100 份整数手、万二佣金和最低 5 元；聚宽订单成交细节不可逐笔导出。
- 能复现历史结果不证明固定资产池没有幸存者或事后选择偏差。
"""


def archive(
    store: ResearchDataStore,
    equity: pd.DataFrame,
    trades: pd.DataFrame,
    scores: pd.DataFrame,
    metrics: dict,
    run_id: str,
    archived_at: str,
) -> Path:
    target = STUDY_DIR / "results" / f"{archived_at}__{run_id}"
    if target.exists():
        raise FileExistsError(f"archive already exists: {target}")
    raw = target / "raw"
    raw.mkdir(parents=True)
    equity.reset_index().to_csv(raw / "equity.csv", index=False, encoding="utf-8")
    trades.to_csv(raw / "trades.csv", index=False, encoding="utf-8")
    scores.reset_index().to_csv(raw / "scores.csv", index=False, encoding="utf-8")
    shutil.copy2(Path(__file__).resolve(), target / "engine.py")
    shutil.copy2(SOURCE_PATH, target / "source.py")
    etf_manifest = store.manifest_path("etf_daily")
    master_manifest = store.manifest_path("security_master")
    manifest = {
        "schema_version": 1,
        "study_id": "joinquant-etf-rotation-replication",
        "run_id": run_id,
        "archived_at": archived_at,
        "source_file": "source.py",
        "source_sha256": file_sha256(target / "source.py"),
        "engine_file": "engine.py",
        "engine_sha256": file_sha256(target / "engine.py"),
        "period": {"start": "2014-01-01", "end": "2023-06-09"},
        "data_manifests": {
            "etf_daily": {
                "path": str(etf_manifest),
                "sha256": sha256_file(etf_manifest),
            },
            "security_master": {
                "path": str(master_manifest),
                "sha256": sha256_file(master_manifest),
            },
        },
        "joinquant_metrics": JQ_METRICS,
        "local_metrics": _json_safe(metrics),
        "artifacts": {
            "equity": "raw/equity.csv",
            "trades": "raw/trades.csv",
            "scores": "raw/scores.csv",
        },
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (target / "report.md").write_text(
        build_report(metrics, len(trades), run_id),
        encoding="utf-8",
    )
    return target


def parse_args():
    parser = argparse.ArgumentParser(description="本地复现聚宽核心资产 ETF 轮动")
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("D:/code/_open-source/_data/quant-research"),
    )
    parser.add_argument("--run-id", default="local-sina-qlib-v1")
    parser.add_argument("--archived-at", default="2026-07-27")
    parser.add_argument("--no-archive", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    store = ResearchDataStore(args.data_root)
    bars = store.read_parquet("etf_daily")
    targets, scores = build_daily_targets(bars)
    mask = (targets.index >= START_DATE) & (targets.index <= END_DATE)
    period_dates = targets.index[mask]
    period_bars = bars[bars["trade_date"].isin(period_dates)]
    equity, trades = simulate_rotation(period_bars, targets.loc[period_dates])
    benchmark = load_benchmark(store.root, equity.index)
    equity["benchmark_value"] = benchmark
    metrics = calculate_metrics(equity, benchmark)
    print(json.dumps(_json_safe(metrics), ensure_ascii=False, indent=2))
    if not args.no_archive:
        target = archive(
            store,
            equity,
            trades,
            scores.loc[period_dates],
            metrics,
            args.run_id,
            args.archived_at,
        )
        print(f"结果已归档：{target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
