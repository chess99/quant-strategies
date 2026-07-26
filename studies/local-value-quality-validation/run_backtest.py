"""使用公告日财务与日估值验收本地价值质量研究链路。"""

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
from quant_research.data.store import ResearchDataStore  # noqa: E402
from quant_research.portal import LocalDataPortal, QlibDailyBarSource  # noqa: E402


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def monthly_first_dates(calendar: pd.DatetimeIndex) -> set[pd.Timestamp]:
    series = pd.Series(calendar, index=calendar)
    return set(series.groupby([calendar.year, calendar.month]).first().tolist())


def _latest_by_symbol(frame: pd.DataFrame) -> pd.DataFrame:
    return (
        frame.sort_values(["symbol", "report_date", "notice_date"])
        .groupby("symbol", as_index=False)
        .tail(1)
    )


def value_quality_features(
    fundamentals: pd.DataFrame,
    valuation_by_date: pd.DataFrame,
    members: list[str],
    observation_date,
) -> pd.DataFrame:
    observation_date = pd.Timestamp(observation_date).normalize()
    members = sorted(set(members))
    visible = fundamentals[
        fundamentals["symbol"].isin(members)
        & pd.to_datetime(fundamentals["notice_date"]).le(observation_date)
    ].copy()
    latest = _latest_by_symbol(visible)
    annual = _latest_by_symbol(visible[visible["is_annual"]])[
        ["symbol", "report_date", "notice_date", "annual_roe"]
    ].rename(
        columns={
            "report_date": "annual_report_date",
            "notice_date": "annual_notice_date",
        }
    )
    previous = visible[["symbol", "report_date", "revenue", "parent_net_profit"]].copy()
    previous["report_date"] = previous["report_date"] + pd.DateOffset(years=1)
    previous.rename(
        columns={"revenue": "previous_revenue", "parent_net_profit": "previous_profit"},
        inplace=True,
    )
    latest = latest.merge(previous, on=["symbol", "report_date"], how="left")
    latest["revenue_growth"] = latest["revenue"] / latest["previous_revenue"] - 1.0
    latest["profit_growth"] = (
        latest["parent_net_profit"] / latest["previous_profit"] - 1.0
    )
    latest = latest.drop(columns=["annual_roe"], errors="ignore")
    latest = latest.merge(annual, on="symbol", how="left")
    window_start = observation_date - pd.Timedelta(days=10)
    try:
        valuation = valuation_by_date.loc[window_start:observation_date].reset_index()
    except KeyError:
        valuation = pd.DataFrame()
    if valuation.empty:
        return pd.DataFrame()
    valuation = (
        valuation[valuation["symbol"].isin(members)]
        .sort_values(["symbol", "trade_date"])
        .groupby("symbol", as_index=False)
        .tail(1)
    )
    frame = latest.merge(
        valuation[["symbol", "trade_date", "market_cap", "pe_ttm", "pb"]],
        on="symbol",
        how="inner",
    )
    frame = frame[
        frame["pb"].between(0.01, 10.0)
        & frame["pe_ttm"].between(0.01, 80.0)
        & frame["annual_roe"].ge(8.0)
        & frame["parent_net_profit"].gt(0.0)
        & frame["revenue_growth"].gt(-0.20)
    ].copy()
    if frame.empty:
        return frame
    frame["profit_growth"] = frame["profit_growth"].clip(-1.0, 3.0)
    frame["revenue_growth"] = frame["revenue_growth"].clip(-1.0, 2.0)
    frame["pb_score"] = frame["pb"].rank(pct=True, ascending=False)
    frame["pe_score"] = frame["pe_ttm"].rank(pct=True, ascending=False)
    frame["roe_score"] = frame["annual_roe"].rank(pct=True)
    frame["revenue_score"] = frame["revenue_growth"].rank(pct=True)
    frame["profit_score"] = frame["profit_growth"].rank(pct=True)
    frame["score"] = (
        0.30 * frame["pb_score"]
        + 0.20 * frame["pe_score"]
        + 0.30 * frame["roe_score"]
        + 0.10 * frame["revenue_score"]
        + 0.10 * frame["profit_score"]
    )
    return frame.sort_values(["score", "symbol"], ascending=[False, True]).reset_index(drop=True)


def build_report(metrics, benchmark_return, turnover, rejected, audits) -> str:
    return f"""# 本地价值质量策略验收

## 事实

- 区间：2019-01-02 至 2025-12-31；初始资金 1,000,000 元；月初开盘调仓。
- 股票池：观察日前一交易日有效的中证800历史成分，并要求至少上市 365 天。
- 选股：正 PE/PB、最近可见年报 ROE 不低于 8%、盈利为正、同期收入增速不低于 -20%，
  再按低 PB、低 PE、高 ROE、收入增长和利润增长合成排名，等权持有前 20 只。
- 财务只使用 `notice_date <= observation_date` 的记录；日估值最多向前找 10 个自然日。
- 本地累计收益 {metrics['total_return']:.2%}，年化 {metrics['annualized_return']:.2%}，
  最大回撤 {metrics['maximum_drawdown']:.2%}，Sharpe {metrics['sharpe']:.3f}，
  最长水下 {metrics['longest_underwater_trading_days']} 个交易日。
- 同期沪深300价格基准累计收益 {benchmark_return:.2%}。
- 累计单边成交额/平均资产 {turnover:.2f}；拒单 {rejected} 次。
- 点时审计：{json.dumps(audits, ensure_ascii=False)}。

## 推断

本实验的目的不是证明这组因子最优，而是验收财务公告日、估值、历史指数成分、月度信号
和多股票撮合能贯通。财务与估值均为 B 级：数据商可能用后来修订值回填历史。历史 ST
缺失使交易状态整体为 C 级，因此结果适合研究筛选，不应直接当作实盘级精确收益。

当前行业快照只从 2026-07-26 起有效且为 C 级，本策略故意不使用行业中性或行业上限；
这证明接口会暴露能力缺口，而不是把当前行业回填到历史。

## 下一步实验

如需提升到正式 B 级回测，优先采购或自行维护历史 ST、除权除息事件和历史申万行业。
随后在保持本归档不变的前提下新增实验，对齐聚宽逐月候选、成交和净值。
"""


def run(args) -> Path:
    store = ResearchDataStore(args.data_root)
    portal = LocalDataPortal(store, QlibDailyBarSource(args.qlib_dir))
    calendar = portal.calendar(args.start_date, args.end_date)
    rebalance = monthly_first_dates(calendar)
    fundamentals = store.read_parquet("fundamentals_pit")
    fundamentals["report_date"] = pd.to_datetime(fundamentals["report_date"])
    fundamentals["notice_date"] = pd.to_datetime(fundamentals["notice_date"])
    valuation = store.read_parquet("daily_valuation")
    valuation["trade_date"] = pd.to_datetime(valuation["trade_date"]).dt.normalize()
    valuation_by_date = valuation.set_index("trade_date").sort_index()
    membership = store.read_parquet("index_membership")
    overlapping = membership[
        membership["index_symbol"].eq("SH000906")
        & pd.to_datetime(membership["start_date"]).le(calendar[-1])
        & pd.to_datetime(membership["end_date"]).ge(calendar[0])
    ]
    financial_symbols = set(fundamentals["symbol"].unique())
    valuation_symbols = set(valuation["symbol"].unique())
    symbols = sorted(set(overlapping["symbol"]).intersection(financial_symbols, valuation_symbols))
    bars = portal.bars(
        symbols,
        calendar[0],
        calendar[-1],
        fields=("open", "close", "volume"),
        adjustment="pre",
    )
    state = store.read_parquet("daily_market_state")
    state = state[
        state["symbol"].isin(symbols)
        & pd.to_datetime(state["trade_date"]).between(calendar[0], calendar[-1])
    ]
    master = store.read_parquet("security_master").set_index("symbol")
    engine = DailyBacktester(
        bars,
        state,
        asset_types={symbol: "stock" for symbol in symbols},
        config=BacktestConfig(
            initial_cash=args.initial_cash,
            maximum_volume_ratio=0.10,
            slippage_rate=0.002,
            allow_unknown_st=True,
        ),
    )
    signals = []
    audits = {
        "rebalance_count": 0,
        "future_notice_rows": 0,
        "future_report_rows": 0,
        "industry_rows_used": 0,
        "minimum_candidates": None,
    }
    previous_date = None
    for trade_date in calendar:
        if trade_date in rebalance and previous_date is not None:
            members = portal.index_members("SH000906", previous_date)
            members = [
                symbol
                for symbol in members
                if symbol in master.index
                and pd.Timestamp(master.loc[symbol, "start_date"])
                <= previous_date - pd.Timedelta(days=365)
            ]
            features = value_quality_features(
                fundamentals,
                valuation_by_date,
                members,
                previous_date,
            )
            selected = features.head(args.holdings)
            audits["rebalance_count"] += 1
            count = len(features)
            audits["minimum_candidates"] = (
                count
                if audits["minimum_candidates"] is None
                else min(audits["minimum_candidates"], count)
            )
            audits["future_notice_rows"] += int(
                pd.to_datetime(features.get("notice_date", pd.Series(dtype="datetime64[ns]") )).gt(previous_date).sum()
            )
            audits["future_report_rows"] += int(
                pd.to_datetime(features.get("report_date", pd.Series(dtype="datetime64[ns]") )).gt(previous_date).sum()
            )
            for rank, row in enumerate(features.itertuples(index=False), start=1):
                payload = row._asdict()
                payload.update(
                    {
                        "execution_date": trade_date,
                        "observation_date": previous_date,
                        "rank": rank,
                        "selected": rank <= args.holdings,
                    }
                )
                signals.append(payload)
            if not selected.empty:
                engine.rebalance_to_weights(
                    trade_date,
                    {symbol: 1.0 / len(selected) for symbol in selected["symbol"]},
                )
        engine.mark_close(trade_date)
        previous_date = trade_date
    metrics = performance_metrics(engine.equity)
    turnover = (
        float(engine.trades["gross_value"].sum() / engine.equity["total_value"].mean())
        if not engine.trades.empty
        else 0.0
    )
    rejected = int(engine.orders["filled_shares"].eq(0).sum()) if not engine.orders.empty else 0
    benchmark = portal.bars(
        "SH000300", calendar[0], calendar[-1], fields=("close",), adjustment="pre"
    )
    benchmark["equity"] = args.initial_cash * benchmark["close"] / benchmark["close"].iloc[0]
    benchmark_return = float(benchmark["equity"].iloc[-1] / args.initial_cash - 1.0)
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
        "platform": "local-qlib-eastmoney",
        "study": "local-value-quality-validation",
        "variant": "pit-value-quality-v1",
        "run_id": args.run_id,
        "period": {"start": str(calendar[0].date()), "end": str(calendar[-1].date())},
        "initial_cash": args.initial_cash,
        "benchmark": "SH000300",
        "quality": {
            "bars": "B",
            "index_membership": "B",
            "valuation": "B",
            "fundamentals": "B",
            "market_state": "C",
            "industry": "not-used-current-proxy-is-C",
        },
        "metrics": metrics,
        "benchmark_total_return": benchmark_return,
        "turnover": turnover,
        "rejected_orders": rejected,
        "point_in_time_audits": audits,
        "source_sha256": sha256_file(source_copy),
        "engine_sha256": sha256_file(engine_copy),
        "data_manifests": {
            name: store.read_manifest(name)
            for name in (
                "fundamentals_pit",
                "daily_valuation",
                "daily_market_state",
                "index_membership",
                "industry_membership",
            )
        },
        "limitations": [
            "财务和估值可能包含数据商后来修订，质量 B。",
            "历史 ST 缺失，交易状态质量 C。",
            "使用前复权虚拟价格撮合以保持收益连续，成交股数和费用为近似。",
            "当前行业代理不回填历史，本策略未使用行业约束。",
        ],
    }
    (result_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (result_dir / "report.md").write_text(
        build_report(metrics, benchmark_return, turnover, rejected, audits), encoding="utf-8"
    )
    return result_dir


def parse_args():
    parser = argparse.ArgumentParser(description="运行本地价值质量策略验收")
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument(
        "--qlib-dir",
        type=Path,
        default=Path("D:/code/_open-source/_data/qlib/cn_data"),
    )
    parser.add_argument("--start-date", default="2019-01-01")
    parser.add_argument("--end-date", default="2025-12-31")
    parser.add_argument("--initial-cash", type=float, default=1_000_000.0)
    parser.add_argument("--holdings", type=int, default=20)
    parser.add_argument(
        "--run-id",
        default="2026-07-27__pit-value-quality__local-qlib-eastmoney-v1",
    )
    return parser.parse_args()


if __name__ == "__main__":
    output = run(parse_args())
    print(output)
