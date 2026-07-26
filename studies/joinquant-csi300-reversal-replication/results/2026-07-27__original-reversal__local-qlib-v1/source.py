"""复现聚宽帖子 30350 中启用的沪深300中期反转策略。"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quant_research.backtest import BacktestConfig, DailyBacktester, performance_metrics  # noqa: E402
from quant_research.data.market_state import build_market_state  # noqa: E402
from quant_research.data.store import ResearchDataStore  # noqa: E402
from quant_research.portal import LocalDataPortal, QlibDailyBarSource  # noqa: E402


POST_URL = "https://www.joinquant.com/post/30350"
SOURCE_PATH = (
    ROOT
    / "joinquant_post_crawler"
    / "sources"
    / "2023年度精选策略"
    / "66.基于动量和反转效应的沪深300成分股策略.py"
)
JQ_METRICS = {
    "period": ["2008-11-01", "2009-11-01"],
    "initial_cash": 10_000_000.0,
    "total_return": 2.31510508,
    "annualized_return": 2.43155566,
    "maximum_drawdown": 0.19882631,
    "sharpe": 5.466020,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rebalance_dates(calendar: pd.DatetimeIndex) -> set[pd.Timestamp]:
    """复刻原策略的 6 个交易日计一周、30 周重置逻辑。"""
    result = set()
    days = 0
    weeks = 0
    flag = True
    for date in calendar:
        if days < 5:
            days += 1
        elif days == 5:
            days = 0
            weeks += 1
        if weeks == 30:
            weeks = 0
            flag = True
        if flag:
            result.add(pd.Timestamp(date).normalize())
            flag = False
    return result


def reversal_scores(
    adjusted_close: pd.DataFrame,
    members: list[str],
    observation_date,
) -> pd.Series:
    """近似 history(30, '5d') 后用倒数第二根与第二根计算收益。"""
    observation_date = pd.Timestamp(observation_date).normalize()
    history = adjusted_close.loc[:observation_date, members].tail(150)
    scores = {}
    for symbol in members:
        series = history[symbol].dropna()
        if len(series) >= 145:
            scores[symbol] = float(series.iloc[-6] / series.iloc[-145] - 1.0)
    return pd.Series(scores, dtype=float).sort_values()


def build_report(local_metrics, turnover, rejections, selected_counts) -> str:
    difference = {
        key: local_metrics[key] - JQ_METRICS[key]
        for key in ("total_return", "annualized_return", "maximum_drawdown", "sharpe")
    }
    return f"""# 沪深300中期反转策略本地复现

## 事实

- 原帖：{POST_URL}
- 回测区间：2008-11-03 至 2009-10-30（原框填写 2008-11-01 至 2009-11-01）
- 初始资金：10,000,000 元；日线开盘撮合；买卖佣金万三、最低 5 元，卖出印花税千一。
- 历史成分：Qlib 沪深300有效区间，未使用当前成分回填。
- 原策略实际启用反转分支：约每 180 个交易日，买入 150 日窗口收益最低的 25 只。
- 本地结果：累计收益 {local_metrics['total_return']:.2%}，年化 {local_metrics['annualized_return']:.2%}，
  最大回撤 {local_metrics['maximum_drawdown']:.2%}，Sharpe {local_metrics['sharpe']:.3f}。
- 聚宽策略框：累计收益 {JQ_METRICS['total_return']:.2%}，年化 {JQ_METRICS['annualized_return']:.2%}，
  最大回撤 {JQ_METRICS['maximum_drawdown']:.2%}，Sharpe {JQ_METRICS['sharpe']:.3f}。
- 本地减聚宽：累计收益 {difference['total_return']:+.2%}，年化 {difference['annualized_return']:+.2%}，
  最大回撤 {difference['maximum_drawdown']:+.2%}，Sharpe {difference['sharpe']:+.3f}。
- 累计单边成交额/平均资产：{turnover:.2f}；拒单 {rejections} 次；每次有效候选数：{selected_counts}。

## 推断

两边不会逐笔相同。主要差异来自免费 Qlib 复权因子与聚宽价格源、`5d` 聚合边界、
历史 ST 缺失，以及聚宽订单撮合细节。本地引擎额外执行 100 股整手、停牌/涨跌停和
10% 日成交量限制，因此结果应视为“机制复现”，不能视为平台结果的字节级重放。

## 下一步实验

若要缩小差异，应先从聚宽导出同区间每日净值、两次调仓候选和成交记录，再逐层对齐
信号、复权价格、订单数量与费用。本归档保持不变；修订应新增 run-id。
"""


def run(args) -> Path:
    store = ResearchDataStore(args.data_root)
    source = QlibDailyBarSource(args.qlib_dir)
    portal = LocalDataPortal(store, source)
    full_calendar = portal.calendar("2008-01-01", args.end_date)
    run_calendar = full_calendar[
        (full_calendar >= pd.Timestamp(args.start_date))
        & (full_calendar <= pd.Timestamp(args.end_date))
    ]
    membership = store.read_parquet("index_membership")
    overlapping = membership[
        membership["index_symbol"].eq("SH000300")
        & pd.to_datetime(membership["start_date"]).le(pd.Timestamp(args.end_date))
        & pd.to_datetime(membership["end_date"]).ge(full_calendar[0])
    ]
    symbols = sorted(overlapping["symbol"].unique())
    raw_bars = portal.bars(
        symbols,
        full_calendar[0],
        run_calendar[-1],
        fields=("open", "high", "low", "close", "volume"),
        adjustment="raw",
    )
    adjusted = portal.bars(
        symbols,
        full_calendar[0],
        run_calendar[-1],
        fields=("close",),
        adjustment="pre",
    )
    adjusted_close = adjusted.pivot(index="trade_date", columns="symbol", values="close")
    master = store.read_parquet("security_master")
    state_features = raw_bars.copy()
    state_features["factor"] = 1.0
    state = build_market_state(state_features, run_calendar, master, symbols)
    engine = DailyBacktester(
        raw_bars[raw_bars["trade_date"].isin(run_calendar)],
        state,
        asset_types={symbol: "stock" for symbol in symbols},
        config=BacktestConfig(
            initial_cash=args.initial_cash,
            maximum_volume_ratio=0.10,
            allow_unknown_st=True,
        ),
    )
    scheduled = rebalance_dates(run_calendar)
    signals = []
    selected_counts = []
    previous_date = full_calendar[full_calendar.get_loc(run_calendar[0]) - 1]
    for trade_date in run_calendar:
        if trade_date in scheduled:
            members = portal.index_members("SH000300", previous_date)
            scores = reversal_scores(adjusted_close, members, previous_date)
            selected = scores.head(25)
            selected_counts.append(len(selected))
            for rank, (symbol, score) in enumerate(scores.items(), start=1):
                signals.append(
                    {
                        "execution_date": trade_date,
                        "observation_date": previous_date,
                        "symbol": symbol,
                        "score": score,
                        "rank": rank,
                        "selected": rank <= 25,
                    }
                )
            if not selected.empty:
                engine.rebalance_to_weights(
                    trade_date,
                    {symbol: 1.0 / len(selected) for symbol in selected.index},
                )
        engine.mark_close(trade_date)
        previous_date = trade_date
    local_metrics = performance_metrics(engine.equity)
    turnover = (
        float(engine.trades["gross_value"].sum() / engine.equity["total_value"].mean())
        if not engine.trades.empty
        else 0.0
    )
    rejected = int(engine.orders["filled_shares"].eq(0).sum()) if not engine.orders.empty else 0
    benchmark = portal.bars(
        "SH000300",
        run_calendar[0],
        run_calendar[-1],
        fields=("close",),
        adjustment="pre",
    )
    benchmark["equity"] = (
        args.initial_cash * benchmark["close"] / benchmark["close"].iloc[0]
    )
    result_dir = Path(__file__).resolve().parent / "results" / args.run_id
    if result_dir.exists():
        raise FileExistsError(f"immutable result directory already exists: {result_dir}")
    raw_dir = result_dir / "raw"
    raw_dir.mkdir(parents=True)
    engine.equity.to_csv(raw_dir / "equity.csv", index=False)
    engine.orders.to_csv(raw_dir / "orders.csv", index=False)
    engine.trades.to_csv(raw_dir / "trades.csv", index=False)
    engine.holdings.to_csv(raw_dir / "holdings.csv", index=False)
    pd.DataFrame(signals).to_csv(raw_dir / "signals.csv", index=False)
    benchmark.to_csv(raw_dir / "benchmark.csv", index=False)
    source_copy = result_dir / "source.py"
    engine_copy = result_dir / "engine.py"
    shutil.copy2(Path(__file__), source_copy)
    shutil.copy2(ROOT / "src" / "quant_research" / "backtest.py", engine_copy)
    manifest = {
        "schema_version": 1,
        "platform": "local-qlib",
        "study": "joinquant-csi300-reversal-replication",
        "variant": "original-reversal-branch",
        "run_id": args.run_id,
        "period": {"start": str(run_calendar[0].date()), "end": str(run_calendar[-1].date())},
        "benchmark": "SH000300",
        "initial_cash": args.initial_cash,
        "costs": {
            "buy_commission": 0.0003,
            "sell_commission": 0.0003,
            "minimum_commission": 5.0,
            "sell_stamp_tax": 0.001,
            "maximum_volume_ratio": 0.10,
        },
        "quality": {"bars": "B", "index_membership": "B", "market_state": "C"},
        "local_metrics": local_metrics,
        "joinquant_metrics": JQ_METRICS,
        "turnover": turnover,
        "rejected_orders": rejected,
        "source_post": POST_URL,
        "source_strategy_path": str(SOURCE_PATH.relative_to(ROOT)).replace("\\", "/"),
        "source_strategy_sha256": sha256_file(SOURCE_PATH),
        "source_sha256": sha256_file(source_copy),
        "engine_sha256": sha256_file(engine_copy),
        "limitations": [
            "历史 ST 缺失，按非 ST 涨跌停规则进行探索性复现。",
            "聚宽 5d 聚合边界以 150 日窗口近似。",
            "免费 Qlib 价格、复权与聚宽数据可能不同。",
        ],
    }
    (result_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (result_dir / "report.md").write_text(
        build_report(local_metrics, turnover, rejected, selected_counts), encoding="utf-8"
    )
    return result_dir


def parse_args():
    parser = argparse.ArgumentParser(description="复现沪深300中期反转策略")
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument(
        "--qlib-dir",
        type=Path,
        default=Path("D:/code/_open-source/_data/qlib/cn_data"),
    )
    parser.add_argument("--start-date", default="2008-11-01")
    parser.add_argument("--end-date", default="2009-11-01")
    parser.add_argument("--initial-cash", type=float, default=10_000_000.0)
    parser.add_argument(
        "--run-id",
        default="2026-07-27__original-reversal__local-qlib-v1",
    )
    return parser.parse_args()


if __name__ == "__main__":
    output = run(parse_args())
    print(output)
