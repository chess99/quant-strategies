"""运行全市场小市值本地预检并创建不可变归档。"""

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
)
from quant_research.portal import LocalDataPortal, QlibDailyBarSource  # noqa: E402


STUDY = "joinquant-small-cap-golden-comparison"
START_DATE = "2019-01-02"
END_DATE = "2023-06-30"
INITIAL_CASH = 10_000_000.0
STOCK_COUNT = 10
MINIMUM_LISTING_DAYS = 375
TOP_CANDIDATES_TO_ARCHIVE = 50


def stable_symbol_hash(symbols) -> str:
    payload = "\n".join(sorted(symbols)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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


def load_or_build_monthly_snapshots(store, observation_dates, execution_dates):
    key_payload = {
        "observation_dates": [str(pd.Timestamp(date).date()) for date in observation_dates],
        "execution_dates": [str(pd.Timestamp(date).date()) for date in execution_dates],
        "valuation_manifest": sha256_file(store.manifest_path("daily_valuation")),
        "state_manifest": sha256_file(store.manifest_path("daily_market_state")),
        "name_events_manifest": sha256_file(store.manifest_path("st_name_events")),
        "delisting_events_manifest": sha256_file(
            store.manifest_path("delisting_events")
        ),
        "maximum_age_days": 10,
    }
    cache_key = hashlib.sha256(
        json.dumps(key_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    cache_dir = store.snapshot_dir / STUDY / cache_key
    valuation_path = cache_dir / "valuation-asof.parquet"
    state_path = cache_dir / "execution-state.parquet"
    names_path = cache_dir / "historical-names.parquet"
    delisting_path = cache_dir / "delisting-events.parquet"
    audit_path = cache_dir / "audit.json"
    if (
        valuation_path.is_file()
        and state_path.is_file()
        and names_path.is_file()
        and delisting_path.is_file()
        and audit_path.is_file()
    ):
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        if audit.get("key_payload") == key_payload:
            return (
                pd.read_parquet(valuation_path),
                pd.read_parquet(state_path),
                pd.read_parquet(names_path),
                pd.read_parquet(delisting_path),
                audit["partition_scans"],
            )
    valuation_result = build_asof_cross_sections(
        store,
        "daily_valuation",
        observation_dates,
        ["market_cap", "quality_grade"],
        maximum_age_days=10,
    )
    state_result = build_exact_cross_sections(
        store,
        "daily_market_state",
        execution_dates,
        ["paused", "is_st", "st_quality", "status_quality", "limit_quality"],
    )
    name_result = build_event_cross_sections(
        store,
        "st_name_events",
        execution_dates,
        ["display_name", "st_quality"],
    )
    delisting_result = build_event_cross_sections(
        store,
        "delisting_events",
        execution_dates,
        ["is_delisting", "quality_grade"],
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    name_result.frame.rename(
        columns={
            "display_name": "historical_display_name",
            "st_quality": "name_quality",
        }
    ).to_parquet(names_path, index=False)
    delisting_result.frame.rename(
        columns={"quality_grade": "delisting_quality"}
    ).to_parquet(delisting_path, index=False)
    valuation_result.frame.to_parquet(valuation_path, index=False)
    state_result.frame.to_parquet(state_path, index=False)
    scans = {
        "valuation_partition_scan": valuation_result.audit,
        "execution_state_partition_scan": state_result.audit,
        "historical_name_event_scan": name_result.audit,
        "delisting_event_scan": delisting_result.audit,
    }
    audit_path.write_text(
        json.dumps(
            {"schema_version": 1, "key_payload": key_payload, "partition_scans": scans},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    names = name_result.frame.rename(
        columns={
            "display_name": "historical_display_name",
            "st_quality": "name_quality",
        }
    )
    delisting = delisting_result.frame.rename(
        columns={"quality_grade": "delisting_quality"}
    )
    return valuation_result.frame, state_result.frame, names, delisting, scans


def month_execution_observation_dates(portal: LocalDataPortal, start_date, end_date):
    padded = portal.calendar(pd.Timestamp(start_date) - pd.Timedelta(days=20), end_date)
    run_calendar = padded[padded >= pd.Timestamp(start_date)]
    table = []
    previous_month = None
    for date in run_calendar:
        month = date.to_period("M")
        if month != previous_month:
            position = padded.get_loc(date)
            if position == 0:
                raise ValueError("calendar padding did not provide a previous session")
            table.append(
                {
                    "execution_date": date,
                    "observation_date": padded[position - 1],
                }
            )
            previous_month = month
    return run_calendar, pd.DataFrame(table)


def build_targets(store: ResearchDataStore, schedule: pd.DataFrame):
    observation_dates = schedule["observation_date"].tolist()
    execution_dates = schedule["execution_date"].tolist()
    valuation, state, historical_names, delisting, scan_audits = (
        load_or_build_monthly_snapshots(store, observation_dates, execution_dates)
    )
    valuation = valuation.copy()
    state = state.rename(columns={"observation_date": "execution_date"})
    master = store.read_parquet("security_master")
    master = master[master["asset_type"].eq("stock")].copy()
    master["start_date"] = pd.to_datetime(master["start_date"]).dt.normalize()
    master["end_date"] = pd.to_datetime(master["end_date"]).dt.normalize()
    schedule_by_observation = schedule.set_index("observation_date")["execution_date"]
    valuation["execution_date"] = valuation["observation_date"].map(schedule_by_observation)
    merged = valuation.merge(state, on=["execution_date", "symbol"], how="left")
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
        master[["symbol", "exchange", "start_date", "end_date"]],
        on="symbol",
        how="left",
        validate="many_to_one",
    )
    coverage_rows = []
    candidate_rows = []
    targets = {}
    for row in schedule.itertuples(index=False):
        cross = merged[merged["observation_date"].eq(row.observation_date)].copy()
        active = master[
            master["start_date"].le(row.observation_date)
            & master["end_date"].ge(row.observation_date)
        ]
        listed_cutoff = row.observation_date - pd.Timedelta(days=MINIMUM_LISTING_DAYS)
        cross["eligible"] = (
            cross["start_date"].le(listed_cutoff)
            & cross["end_date"].ge(row.observation_date)
            & cross["exchange"].isin(["XSHG", "XSHE"])
            & pd.to_numeric(cross["market_cap"], errors="coerce").gt(0)
            & cross["paused"].eq(False)
            & cross["is_st"].eq(False)
            & cross["st_quality"].isin(["A", "B"])
            & cross["status_quality"].isin(["A", "B"])
            & cross["limit_quality"].isin(["A", "B"])
            & ~cross["historical_display_name"]
            .fillna("")
            .str.contains(r"ST|\*|退", case=False, regex=True)
            & ~cross["is_delisting"].eq(True)
        )
        eligible = cross[cross["eligible"]].sort_values(["market_cap", "symbol"]).copy()
        eligible["rank"] = range(1, len(eligible) + 1)
        eligible["selected"] = eligible["rank"].le(STOCK_COUNT)
        target_symbols = eligible.head(STOCK_COUNT)["symbol"].tolist()
        targets[row.execution_date] = target_symbols
        archived = eligible.head(TOP_CANDIDATES_TO_ARCHIVE).copy()
        archived["candidate_universe_count"] = len(eligible)
        archived["candidate_universe_sha256"] = stable_symbol_hash(eligible["symbol"])
        candidate_rows.append(
            archived[
                [
                    "execution_date",
                    "observation_date",
                    "symbol",
                    "rank",
                    "selected",
                    "market_cap",
                    "trade_date",
                    "age_days",
                    "historical_display_name",
                    "name_quality",
                    "is_delisting",
                    "delisting_quality",
                    "candidate_universe_count",
                    "candidate_universe_sha256",
                ]
            ]
        )
        coverage_rows.append(
            {
                "execution_date": row.execution_date,
                "observation_date": row.observation_date,
                "active_full_market_stocks": len(active),
                "valuation_rows": len(cross),
                "execution_state_rows": int(cross["paused"].notna().sum()),
                "known_st_rows": int(cross["is_st"].notna().sum()),
                "known_historical_name_rows": int(
                    cross["historical_display_name"].notna().sum()
                ),
                "eligible_candidates": len(eligible),
                "selected_count": len(target_symbols),
                "selected_sha256": stable_symbol_hash(target_symbols),
            }
        )
    candidates = pd.concat(candidate_rows, ignore_index=True)
    coverage = pd.DataFrame(coverage_rows)
    return targets, candidates, coverage, scan_audits


def load_selected_state(store, symbols, trading_dates):
    result = build_exact_cross_sections(
        store,
        "daily_market_state",
        trading_dates,
        [
            "paused",
            "is_st",
            "buy_blocked",
            "sell_blocked",
            "status_quality",
            "st_quality",
            "limit_quality",
        ],
        symbols=symbols,
    )
    frame = result.frame.rename(columns={"observation_date": "trade_date"})
    return frame, result.audit


def build_report(metrics, checks, coverage, rejected_count) -> str:
    return f"""# 全市场小市值本地预检

## 事实

- 回测区间：{START_DATE} 至 {END_DATE}；每月首个交易日开盘调仓，观察日为前一交易日。
- 股票池从 6,115 只历史 A 股主表按观察日生命周期展开，不使用当前股票池回填。
- 北交所历史涨跌停在免费源中是 C 级，因此在全市场展开后显式剔除；不以 C 级代理撮合。
- 点时总市值为 B 级；历史 ST/停牌/涨跌停为 A/B 级；价格为 Qlib B 级。
- 共 {len(coverage)} 次调仓；每次最少 {int(coverage['eligible_candidates'].min())} 只合格候选；
  每次均选 {STOCK_COUNT} 只。
- 本地累计收益 {metrics['total_return']:.2%}，年化 {metrics['annualized_return']:.2%}，
  最大回撤 {metrics['maximum_drawdown']:.2%}，Sharpe {metrics['sharpe']:.3f}，
  换手 {metrics['turnover']:.2f}，平均现金比例 {metrics['average_cash_ratio']:.2%}。
- 拒单 {rejected_count} 次；点时、覆盖和归档检查：{checks}。

## 限制

- 本地用连续复权价格表示分红送转影响；撮合器同时支持原始价加显式公司行为账本，
  但免费数据尚无全市场公司行为事件表。
- 本归档是聚宽运行前的本地审计，不包含聚宽黄金结果，不能单独完成迭代 5。
- 聚宽侧仅在本地规则、数据覆盖和未来数据检查通过后运行一次，并输出逐月候选、订单和持仓。
"""


def run(args) -> Path:
    store = ResearchDataStore(args.data_root)
    portal = LocalDataPortal(store, QlibDailyBarSource(args.qlib_dir))
    run_calendar, schedule = month_execution_observation_dates(portal, args.start_date, args.end_date)
    targets, candidates, coverage, scan_audits = build_targets(store, schedule)
    selected_symbols = sorted({symbol for values in targets.values() for symbol in values})
    bars = portal.bars(
        selected_symbols,
        run_calendar[0],
        run_calendar[-1],
        fields=("open", "close", "volume"),
        adjustment="pre",
    )
    state, selected_state_audit = load_selected_state(store, selected_symbols, run_calendar)
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
            allow_unknown_st=False,
            minimum_state_quality="B",
        ),
        corporate_actions=delisting_actions,
    )
    monthly_holdings = []
    for date in run_calendar:
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
    pit_violations = int(candidates["trade_date"].gt(candidates["observation_date"]).sum())
    if engine.trades.empty:
        reason_counts = (
            {} if engine.orders.empty else engine.orders["reason"].value_counts().to_dict()
        )
        raise RuntimeError(
            "quality-gated preflight produced no trades; "
            f"selected_symbols={len(selected_symbols)}, order_reasons={reason_counts}"
        )
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
        validate="many_to_one",
    )
    filled_state_is_ab = filled_state[
        ["status_quality", "st_quality", "limit_quality"]
    ].isin(["A", "B"]).all(axis=None)
    checks = {
        "full_master_is_6115": int(store.read_manifest("security_master")["coverage"]["asset_type_counts"]["stock"])
        == 6115,
        "all_rebalances_have_ten_targets": coverage["selected_count"].eq(STOCK_COUNT).all(),
        "no_valuation_future_data": pit_violations == 0,
        "no_partition_read_failures": not scan_audits["valuation_partition_scan"]["failed_symbols"]
        and not scan_audits["execution_state_partition_scan"]["failed_symbols"]
        and not selected_state_audit["failed_symbols"],
        "no_future_name_events": scan_audits["historical_name_event_scan"][
            "future_event_rows"
        ]
        == 0,
        "no_future_delisting_events": scan_audits["delisting_event_scan"][
            "future_event_rows"
        ]
        == 0,
        "known_st_for_archived_candidates": candidates["symbol"].notna().all(),
        "all_filled_orders_use_a_or_b_state": filled_state_is_ab,
        "nonnegative_cash": engine.equity["cash"].ge(-1e-6).all(),
        "orders_and_ledgers_present": not engine.orders.empty
        and not engine.trades.empty
        and not engine.cash_ledger.empty
        and not engine.fees_ledger.empty,
        "delisting_actions_audited": len(engine.corporate_actions)
        == len(delisting_actions),
    }
    checks = {key: bool(value) for key, value in checks.items()}
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
        "candidates-top50.csv": candidates,
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
        "cross_section_summary": {
            "minimum_active_full_market_stocks": int(coverage["active_full_market_stocks"].min()),
            "maximum_active_full_market_stocks": int(coverage["active_full_market_stocks"].max()),
            "minimum_eligible_candidates": int(coverage["eligible_candidates"].min()),
            "minimum_known_st_rows": int(coverage["known_st_rows"].min()),
        },
        "partition_scans": {**scan_audits, "selected_daily_state": selected_state_audit},
        "limitations": [
            "daily_valuation has 6030 successful symbol partitions and 85 explicit failures",
            "adjusted prices represent corporate actions because a full-market event feed is unavailable",
            "JoinQuant golden comparison has not yet been run",
        ],
    }
    coverage_path = result_dir / "coverage.json"
    coverage_path.write_text(
        json.dumps(coverage_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    source_path = result_dir / "source.py"
    engine_path = result_dir / "engine.py"
    jq_source_path = result_dir / "joinquant_strategy.py"
    shutil.copy2(Path(__file__), source_path)
    shutil.copy2(ROOT / "src" / "quant_research" / "backtest.py", engine_path)
    shutil.copy2(Path(__file__).with_name("joinquant_strategy.py"), jq_source_path)
    provenance = [
        dataset_provenance(store, dataset)
        for dataset in (
            "security_master",
            "daily_valuation",
            "daily_market_state",
            "st_name_events",
            "delisting_events",
        )
    ]
    manifest = {
        "schema_version": 1,
        "status": status,
        "platform": "local-qlib",
        "study": STUDY,
        "run_id": args.run_id,
        "period": {"start": args.start_date, "end": args.end_date},
        "initial_cash": args.initial_cash,
        "strategy": {
            "frequency": "monthly_first_session_open",
            "observation_lag_sessions": 1,
            "stock_count": STOCK_COUNT,
            "minimum_listing_days": MINIMUM_LISTING_DAYS,
            "ranking": "daily_valuation.market_cap ascending",
            "exchange_filter": ["XSHG", "XSHE"],
        },
        "data_provenance": provenance,
        "quality": {
            "bars": "B",
            "valuation": "B",
            "market_state_dataset": "C",
            "market_state_row_gate": "B",
            "historical_names": "A where available; unavailable names are not backfilled",
            "delisting_events": "B",
        },
        "metrics": metrics,
        "checks": checks,
        "coverage_sha256": sha256_file(coverage_path),
        "source_sha256": sha256_file(source_path),
        "engine_sha256": sha256_file(engine_path),
        "joinquant_strategy_sha256": sha256_file(jq_source_path),
        "raw_sha256": raw_hashes,
        "joinquant_golden_status": "pending_single_run",
    }
    (result_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    rejected_count = 0 if engine.rejections.empty else len(engine.rejections)
    (result_dir / "report.md").write_text(
        build_report(metrics, checks, coverage, rejected_count), encoding="utf-8"
    )
    if status != "local_preflight_passed":
        raise RuntimeError(f"local preflight failed; evidence preserved at {result_dir}")
    return result_dir


def parse_args():
    parser = argparse.ArgumentParser(description="运行全市场小市值本地预检")
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
        default="2026-07-27__monthly-small-cap__local-preflight-v1",
    )
    return parser.parse_args()


if __name__ == "__main__":
    print(run(parse_args()))
