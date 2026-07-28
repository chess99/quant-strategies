"""运行全市场价值质量本地预检并创建不可变归档。"""

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

from quant_research.backtest import (  # noqa: E402
    BacktestConfig,
    DailyBacktester,
    build_delisting_actions,
    performance_metrics,
)
from quant_research.data.store import ResearchDataStore, sha256_file  # noqa: E402
from quant_research.full_market import (  # noqa: E402
    build_asof_cross_sections,
    build_event_cross_sections,
    build_exact_cross_sections,
    build_fundamental_cross_sections,
    build_interval_cross_sections,
)
from quant_research.portal import LocalDataPortal, QlibDailyBarSource  # noqa: E402


STUDY = "joinquant-value-quality-golden-comparison"
START_DATE = "2019-01-02"
END_DATE = "2023-06-30"
INITIAL_CASH = 10_000_000.0
HOLDINGS = 20
MAX_PER_INDUSTRY = 3
MINIMUM_LISTING_DAYS = 375
TOP_CANDIDATES_TO_ARCHIVE = 100


def stable_symbol_hash(symbols) -> str:
    return hashlib.sha256("\n".join(sorted(symbols)).encode("utf-8")).hexdigest()


def dataset_provenance(store: ResearchDataStore, dataset: str) -> dict:
    manifest = store.read_manifest(dataset)
    path = store.manifest_path(dataset)
    return {
        "dataset": dataset,
        "quality_grade": manifest["quality_grade"],
        "provider": manifest.get("provider"),
        "row_count": manifest.get("row_count"),
        "manifest_sha256": sha256_file(path),
    }


def month_execution_observation_dates(portal, start_date, end_date):
    padded = portal.calendar(pd.Timestamp(start_date) - pd.Timedelta(days=20), end_date)
    run_calendar = padded[padded >= pd.Timestamp(start_date)]
    rows = []
    previous_month = None
    for date in run_calendar:
        month = date.to_period("M")
        if month != previous_month:
            position = padded.get_loc(date)
            rows.append(
                {"execution_date": date, "observation_date": padded[position - 1]}
            )
            previous_month = month
    return run_calendar, pd.DataFrame(rows)


def _rank_within_industry(frame: pd.DataFrame, column: str, ascending: bool) -> pd.Series:
    global_rank = frame[column].rank(pct=True, ascending=ascending)
    industry_size = frame.groupby("industry_code")[column].transform("count")
    industry_rank = frame.groupby("industry_code")[column].rank(
        pct=True, ascending=ascending
    )
    return industry_rank.where(industry_size.ge(5), global_rank)


def score_value_quality(frame: pd.DataFrame) -> pd.DataFrame:
    """使用聚宽可直接取得的共同字段，做行业内价值与质量排序。"""

    data = frame.copy()
    for column in (
        "pe_ttm",
        "pb",
        "ps",
        "roe",
        "roa",
        "gross_margin",
        "net_margin",
        "total_assets",
        "total_liabilities",
        "operating_cash_flow",
    ):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data["debt_to_assets"] = data["total_liabilities"] / data["total_assets"]
    data = data[
        data["pe_ttm"].between(0.01, 100.0)
        & data["pb"].between(0.01, 20.0)
        & data["ps"].between(0.01, 30.0)
        & data["roe"].between(0.0, 100.0)
        & data["roa"].between(0.0, 100.0)
        & data["gross_margin"].between(-100.0, 100.0)
        & data["net_margin"].between(0.0, 100.0)
        & data["total_assets"].gt(0.0)
        & data["debt_to_assets"].between(0.0, 1.5)
        & data["operating_cash_flow"].gt(0.0)
        & data["industry_code"].notna()
    ].copy()
    if data.empty:
        return data
    value_columns = ["pe_ttm", "pb", "ps"]
    quality_high = ["roe", "roa", "gross_margin", "net_margin"]
    for column in value_columns:
        data[f"{column}_score"] = _rank_within_industry(data, column, False)
    for column in quality_high:
        data[f"{column}_score"] = _rank_within_industry(data, column, True)
    data["leverage_score"] = _rank_within_industry(data, "debt_to_assets", False)
    data["value_score"] = data[[f"{column}_score" for column in value_columns]].mean(axis=1)
    data["quality_score"] = data[
        [f"{column}_score" for column in quality_high] + ["leverage_score"]
    ].mean(axis=1)
    data["score"] = 0.5 * data["value_score"] + 0.5 * data["quality_score"]
    return data.sort_values(["score", "symbol"], ascending=[False, True]).reset_index(
        drop=True
    )


def select_with_industry_cap(
    ranked: pd.DataFrame,
    count: int = HOLDINGS,
    maximum_per_industry: int = MAX_PER_INDUSTRY,
) -> pd.DataFrame:
    selected = []
    industry_counts: dict[str, int] = {}
    for index, row in ranked.iterrows():
        industry = str(row["industry_code"])
        if industry_counts.get(industry, 0) >= maximum_per_industry:
            continue
        selected.append(index)
        industry_counts[industry] = industry_counts.get(industry, 0) + 1
        if len(selected) == count:
            break
    return ranked.loc[selected].copy().reset_index(drop=True)


def load_or_build_snapshots(store, observation_dates, execution_dates):
    key_payload = {
        "observation_dates": [str(pd.Timestamp(date).date()) for date in observation_dates],
        "execution_dates": [str(pd.Timestamp(date).date()) for date in execution_dates],
        "manifests": {
            name: sha256_file(store.manifest_path(name))
            for name in (
                "daily_valuation",
                "daily_market_state",
                "fundamentals_pit",
                "industry_membership",
                "st_name_events",
                "delisting_events",
            )
        },
    }
    cache_key = hashlib.sha256(
        json.dumps(key_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    cache_dir = store.snapshot_dir / STUDY / cache_key
    paths = {
        "valuation": cache_dir / "valuation.parquet",
        "state": cache_dir / "state.parquet",
        "fundamentals": cache_dir / "fundamentals.parquet",
        "industry": cache_dir / "industry.parquet",
        "names": cache_dir / "historical-names.parquet",
        "delisting": cache_dir / "delisting-events.parquet",
        "audit": cache_dir / "audit.json",
    }
    if all(path.is_file() for path in paths.values()):
        audit = json.loads(paths["audit"].read_text(encoding="utf-8"))
        if audit.get("key_payload") == key_payload:
            return (
                pd.read_parquet(paths["valuation"]),
                pd.read_parquet(paths["state"]),
                pd.read_parquet(paths["fundamentals"]),
                pd.read_parquet(paths["industry"]),
                pd.read_parquet(paths["names"]),
                pd.read_parquet(paths["delisting"]),
                audit["partition_scans"],
            )
    valuation = build_asof_cross_sections(
        store,
        "daily_valuation",
        observation_dates,
        ["market_cap", "pe_ttm", "pb", "ps", "quality_grade"],
        maximum_age_days=10,
    )
    state = build_exact_cross_sections(
        store,
        "daily_market_state",
        execution_dates,
        ["paused", "is_st", "st_quality", "status_quality", "limit_quality"],
    )
    fundamentals = build_fundamental_cross_sections(
        store,
        "fundamentals_pit",
        observation_dates,
        [
            "roe",
            "roa",
            "gross_margin",
            "net_margin",
            "total_assets",
            "total_liabilities",
            "operating_cash_flow",
            "quality_grade",
        ],
    )
    industry = build_interval_cross_sections(
        store,
        "industry_membership",
        observation_dates,
        ["classification", "industry_code", "industry_name", "quality_grade"],
    )
    industry_frame = industry.frame[
        industry.frame["classification"].eq("sw_l1")
    ].copy()
    names = build_event_cross_sections(
        store,
        "st_name_events",
        execution_dates,
        ["display_name", "st_quality"],
    )
    names_frame = names.frame.rename(
        columns={
            "display_name": "historical_display_name",
            "st_quality": "name_quality",
        }
    )
    delisting = build_event_cross_sections(
        store,
        "delisting_events",
        execution_dates,
        ["is_delisting", "quality_grade"],
    )
    delisting_frame = delisting.frame.rename(
        columns={"quality_grade": "delisting_quality"}
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    for name, result in (
        ("valuation", valuation),
        ("state", state),
        ("fundamentals", fundamentals),
        ("industry", type(industry)(industry_frame, industry.audit)),
        ("names", type(names)(names_frame, names.audit)),
        ("delisting", type(delisting)(delisting_frame, delisting.audit)),
    ):
        result.frame.to_parquet(paths[name], index=False)
    scans = {
        "valuation": valuation.audit,
        "state": state.audit,
        "fundamentals": fundamentals.audit,
        "industry": industry.audit,
        "names": names.audit,
        "delisting": delisting.audit,
    }
    paths["audit"].write_text(
        json.dumps(
            {"schema_version": 1, "key_payload": key_payload, "partition_scans": scans},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return (
        valuation.frame,
        state.frame,
        fundamentals.frame,
        industry_frame,
        names_frame,
        delisting_frame,
        scans,
    )


def build_targets(store: ResearchDataStore, schedule: pd.DataFrame):
    (
        valuation,
        state,
        fundamentals,
        industry,
        historical_names,
        delisting,
        scans,
    ) = load_or_build_snapshots(
        store, schedule["observation_date"], schedule["execution_date"]
    )
    state = state.rename(columns={"observation_date": "execution_date"})
    schedule_map = schedule.set_index("observation_date")["execution_date"]
    valuation["execution_date"] = valuation["observation_date"].map(schedule_map)
    merged = valuation.merge(
        state,
        on=["execution_date", "symbol"],
        how="left",
        suffixes=("_valuation", "_state"),
    )
    merged = merged.merge(
        historical_names[
            ["observation_date", "symbol", "historical_display_name", "name_quality"]
        ].rename(columns={"observation_date": "execution_date"}),
        on=["execution_date", "symbol"],
        how="left",
    )
    merged = merged.merge(
        delisting[
            ["observation_date", "symbol", "is_delisting", "delisting_quality"]
        ].rename(columns={"observation_date": "execution_date"}),
        on=["execution_date", "symbol"],
        how="left",
    )
    merged = merged.merge(
        fundamentals,
        on=["observation_date", "symbol"],
        how="inner",
        suffixes=("", "_fundamental"),
    )
    merged = merged.merge(
        industry[
            [
                "observation_date",
                "symbol",
                "start_date",
                "end_date",
                "industry_code",
                "industry_name",
                "quality_grade",
            ]
        ],
        on=["observation_date", "symbol"],
        how="inner",
        suffixes=("", "_industry"),
    )
    master = store.read_parquet("security_master")
    master = master[master["asset_type"].eq("stock")].copy()
    master["start_date"] = pd.to_datetime(master["start_date"]).dt.normalize()
    master["end_date"] = pd.to_datetime(master["end_date"]).dt.normalize()
    merged = merged.merge(
        master[["symbol", "exchange", "start_date", "end_date"]],
        on="symbol",
        how="left",
        suffixes=("_industry_interval", "_security"),
    )
    target_map = {}
    candidates = []
    coverage = []
    for row in schedule.itertuples(index=False):
        cross = merged[merged["observation_date"].eq(row.observation_date)].copy()
        active = master[
            master["start_date"].le(row.observation_date)
            & master["end_date"].ge(row.observation_date)
        ]
        cutoff = row.observation_date - pd.Timedelta(days=MINIMUM_LISTING_DAYS)
        cross = cross[
            cross["start_date_security"].le(cutoff)
            & cross["end_date_security"].ge(row.observation_date)
            & cross["exchange"].isin(["XSHG", "XSHE"])
            & cross["paused"].eq(False)
            & cross["is_st"].eq(False)
            & cross["st_quality"].isin(["A", "B"])
            & cross["status_quality"].isin(["A", "B"])
            & cross["limit_quality"].isin(["A", "B"])
            & ~cross["historical_display_name"]
            .fillna("")
            .str.contains(r"ST|\*|退", case=False, regex=True)
            & ~cross["is_delisting"].eq(True)
        ]
        ranked = score_value_quality(cross)
        selected = select_with_industry_cap(ranked)
        target_map[row.execution_date] = selected["symbol"].tolist()
        archived = ranked.head(TOP_CANDIDATES_TO_ARCHIVE).copy()
        archived["rank"] = range(1, len(archived) + 1)
        archived["selected"] = archived["symbol"].isin(set(selected["symbol"]))
        archived["execution_date"] = row.execution_date
        archived["candidate_universe_count"] = len(ranked)
        archived["candidate_universe_sha256"] = stable_symbol_hash(ranked["symbol"])
        candidates.append(archived)
        coverage.append(
            {
                "execution_date": row.execution_date,
                "observation_date": row.observation_date,
                "active_full_market_stocks": len(active),
                "merged_point_in_time_rows": len(cross),
                "eligible_candidates": len(ranked),
                "selected_count": len(selected),
                "selected_industries": int(selected["industry_code"].nunique()),
                "selected_sha256": stable_symbol_hash(selected["symbol"]),
            }
        )
    return (
        target_map,
        pd.concat(candidates, ignore_index=True),
        pd.DataFrame(coverage),
        scans,
    )


def build_report(metrics, checks, coverage, rejected_count) -> str:
    return f"""# 全市场价值质量本地预检

## 事实

- 区间：{START_DATE} 至 {END_DATE}；每月首个交易日开盘调仓，观察日为前一交易日。
- 股票池从 6,115 只历史 A 股按观察日生命周期展开；北交所因免费历史涨跌停为 C 级而剔除。
- 财务只使用 `notice_date <= observation_date` 的最新报告；估值最多向前 10 个自然日；
  行业使用申万官方历史一级行业有效区间。
- 先做行业内低 PE/PB/PS 与高 ROE/ROA/利润率、低杠杆综合排名，再设每行业最多
  {MAX_PER_INDUSTRY} 只，等权持有 {HOLDINGS} 只。
- 共 {len(coverage)} 次调仓；最少 {int(coverage['eligible_candidates'].min())} 只合格候选，
  最少选择 {int(coverage['selected_count'].min())} 只。
- 本地累计收益 {metrics['total_return']:.2%}，年化 {metrics['annualized_return']:.2%}，
  最大回撤 {metrics['maximum_drawdown']:.2%}，Sharpe {metrics['sharpe']:.3f}，
  换手 {metrics['turnover']:.2f}，平均现金 {metrics['average_cash_ratio']:.2%}。
- 拒单 {rejected_count} 次；点时和数据质量检查：{checks}。

## 限制

- 东方财富可能把后来修订值回填到旧公告记录，因此财务和估值均为 B，不宣称严格 vintage A。
- 本归档完成本地全量预检，但在聚宽候选、持仓、成交和净值黄金对照通过前，迭代 6 仍未完成。
"""


def run(args) -> Path:
    store = ResearchDataStore(args.data_root)
    portal = LocalDataPortal(store, QlibDailyBarSource(args.qlib_dir))
    calendar, schedule = month_execution_observation_dates(
        portal, args.start_date, args.end_date
    )
    targets, candidates, coverage, scans = build_targets(store, schedule)
    selected_symbols = sorted({symbol for values in targets.values() for symbol in values})
    bars = portal.bars(
        selected_symbols,
        calendar[0],
        calendar[-1],
        fields=("open", "close", "volume"),
        adjustment="pre",
    )
    state_result = build_exact_cross_sections(
        store,
        "daily_market_state",
        calendar,
        [
            "paused",
            "is_st",
            "buy_blocked",
            "sell_blocked",
            "status_quality",
            "st_quality",
            "limit_quality",
        ],
        symbols=selected_symbols,
    )
    state = state_result.frame.rename(columns={"observation_date": "trade_date"})
    delisting_actions = build_delisting_actions(
        store.read_parquet("delisting_events"),
        store.read_parquet("security_master"),
        bars,
    )
    engine = DailyBacktester(
        bars,
        state,
        asset_types={symbol: "stock" for symbol in selected_symbols},
        config=BacktestConfig(
            initial_cash=args.initial_cash,
            maximum_volume_ratio=0.10,
            slippage_rate=0.002,
            allow_unknown_st=False,
            minimum_state_quality="B",
        ),
        corporate_actions=delisting_actions,
    )
    monthly_holdings = []
    for date in calendar:
        if date in targets:
            selected = targets[date]
            engine.rebalance_to_weights(
                date,
                {symbol: 1.0 / len(selected) for symbol in selected},
                execution="open",
            )
            for symbol, position in sorted(engine.positions.items()):
                monthly_holdings.append(
                    {
                        "execution_date": date,
                        "symbol": symbol,
                        "shares": position.shares,
                        "market_value_at_open": position.shares
                        * engine._price_for_equity(date, symbol, "open"),
                    }
                )
        engine.mark_close(date)
    metrics = performance_metrics(engine.equity, engine.trades)
    pit_violations = int(
        pd.to_datetime(candidates["notice_date"])
        .gt(pd.to_datetime(candidates["observation_date"]))
        .sum()
    )
    selected_candidates = candidates[candidates["selected"].astype(bool)]
    filled_state = engine.trades[["trade_date", "symbol"]].merge(
        state[
            [
                "trade_date",
                "symbol",
                "status_quality",
                "st_quality",
                "limit_quality",
            ]
        ],
        on=["trade_date", "symbol"],
        how="left",
    )
    selected_execution_quality_ok = bool(
        selected_candidates["status_quality"].isin(["A", "B"]).all()
        and selected_candidates["st_quality"].isin(["A", "B"]).all()
        and selected_candidates["limit_quality"].isin(["A", "B"]).all()
    )
    filled_trade_quality_ok = bool(
        filled_state["status_quality"].isin(["A", "B"]).all()
        and filled_state["st_quality"].isin(["A", "B"]).all()
        and filled_state["limit_quality"].isin(["A", "B"]).all()
    )
    checks = {
        "all_rebalances_have_20_targets": bool(coverage["selected_count"].eq(HOLDINGS).all()),
        "future_notice_rows_zero": pit_violations == 0,
        "fundamental_partition_failures_zero": not scans["fundamentals"]["failed_symbols"],
        "industry_partition_failures_zero": not scans["industry"]["failed_symbols"],
        "future_industry_intervals_zero": scans["industry"]["future_interval_rows"] == 0,
        "future_name_events_zero": scans["names"]["future_event_rows"] == 0,
        "future_delisting_events_zero": scans["delisting"]["future_event_rows"] == 0,
        "selected_execution_state_quality_at_least_b": selected_execution_quality_ok,
        "filled_trade_state_quality_at_least_b": filled_trade_quality_ok,
        "trades_present": not engine.trades.empty,
        "delisting_actions_audited": len(engine.corporate_actions)
        == len(delisting_actions),
    }
    status = "local_preflight_passed" if all(checks.values()) else "failed"
    result_dir = Path(__file__).resolve().parent / "results" / args.run_id
    if result_dir.exists():
        raise FileExistsError(f"immutable result directory already exists: {result_dir}")
    raw_dir = result_dir / "raw"
    raw_dir.mkdir(parents=True)
    outputs = {
        "equity.csv": engine.equity,
        "orders.csv": engine.orders,
        "trades.csv": engine.trades,
        "holdings-daily.csv": engine.holdings,
        "holdings-monthly.csv": pd.DataFrame(monthly_holdings),
        "candidates-top100.csv": candidates,
        "rebalance-coverage.csv": coverage,
        "cash-ledger.csv": engine.cash_ledger,
        "fees-ledger.csv": engine.fees_ledger,
        "rejections.csv": engine.rejections,
        "corporate-actions.csv": engine.corporate_actions,
    }
    raw_hashes = {}
    for filename, frame in outputs.items():
        path = raw_dir / filename
        frame.to_csv(path, index=False)
        raw_hashes[filename] = sha256_file(path)
    coverage_report = {
        "schema_version": 1,
        "status": status,
        "period": {"start": args.start_date, "end": args.end_date},
        "schedule_rows": len(schedule),
        "selected_unique_symbols": len(selected_symbols),
        "pit_violations": pit_violations,
        "checks": checks,
        "partition_scans": {**scans, "selected_daily_state": state_result.audit},
        "cross_section_summary": {
            "minimum_active_full_market_stocks": int(
                coverage["active_full_market_stocks"].min()
            ),
            "minimum_eligible_candidates": int(coverage["eligible_candidates"].min()),
            "minimum_selected_industries": int(coverage["selected_industries"].min()),
        },
    }
    coverage_path = result_dir / "coverage.json"
    coverage_path.write_text(
        json.dumps(coverage_report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    source_path = result_dir / "source.py"
    engine_path = result_dir / "engine.py"
    jq_path = result_dir / "joinquant_strategy.py"
    shutil.copy2(Path(__file__), source_path)
    shutil.copy2(ROOT / "src" / "quant_research" / "backtest.py", engine_path)
    shutil.copy2(Path(__file__).with_name("joinquant_strategy.py"), jq_path)
    manifest = {
        "schema_version": 1,
        "status": status,
        "platform": "local-qlib-eastmoney-swsresearch",
        "study": STUDY,
        "run_id": args.run_id,
        "period": {"start": args.start_date, "end": args.end_date},
        "initial_cash": args.initial_cash,
        "benchmark": "SH000300",
        "strategy": {
            "frequency": "monthly_first_session_open",
            "observation_lag_sessions": 1,
            "holdings": HOLDINGS,
            "maximum_per_sw_l1": MAX_PER_INDUSTRY,
            "minimum_listing_days": MINIMUM_LISTING_DAYS,
        },
        "data_provenance": [
            dataset_provenance(store, dataset)
            for dataset in (
                "security_master",
                "daily_valuation",
                "daily_market_state",
                "fundamentals_pit",
                "industry_membership",
                "st_name_events",
                "delisting_events",
            )
        ],
        "quality": {
            "bars": "B",
            "valuation": "B",
            "fundamentals": "B",
            "industry": "B",
            "historical_names": "A where available; unavailable names are not backfilled",
            "delisting_events": "B",
            "market_state_row_gate": "B",
        },
        "metrics": metrics,
        "checks": checks,
        "coverage_sha256": sha256_file(coverage_path),
        "source_sha256": sha256_file(source_path),
        "engine_sha256": sha256_file(engine_path),
        "joinquant_strategy_sha256": sha256_file(jq_path),
        "raw_sha256": raw_hashes,
        "joinquant_golden_status": "pending_single_run",
    }
    (result_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (result_dir / "report.md").write_text(
        build_report(metrics, checks, coverage, len(engine.rejections)),
        encoding="utf-8",
    )
    if status != "local_preflight_passed":
        raise RuntimeError(f"local preflight failed; evidence preserved at {result_dir}")
    return result_dir


def parse_args():
    parser = argparse.ArgumentParser(description="运行全市场价值质量本地预检")
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument(
        "--qlib-dir",
        type=Path,
        default=Path("D:/code/_open-source/_data/qlib/cn_data"),
    )
    parser.add_argument("--start-date", default=START_DATE)
    parser.add_argument("--end-date", default=END_DATE)
    parser.add_argument("--initial-cash", type=float, default=INITIAL_CASH)
    parser.add_argument(
        "--run-id",
        default="2026-07-27__monthly-value-quality__local-preflight-v1",
    )
    return parser.parse_args()


if __name__ == "__main__":
    print(run(parse_args()))
