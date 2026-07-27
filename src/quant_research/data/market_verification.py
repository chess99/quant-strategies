"""迭代 3 的机器可读验收报告。"""

from __future__ import annotations

from datetime import datetime, timezone

from .store import ResearchDataStore, sha256_file


def build_market_valuation_verification(
    store: ResearchDataStore,
    *,
    minimum_current_valuation_coverage: float = 0.95,
    minimum_known_st_ratio: float = 0.95,
) -> dict:
    master = store.read_parquet("security_master")
    stocks = master[master["asset_type"] == "stock"]
    active_symbols = set(
        stocks.loc[stocks["active_at_source_end"].astype(bool), "symbol"].astype(str)
    )
    valuation = store.read_manifest("daily_valuation")
    price_limit = store.read_manifest("daily_price_limit")
    official = store.read_manifest("daily_official_status")
    names = store.read_manifest("st_name_events")
    risk_events = store.read_manifest("risk_warning_events")
    market_state = store.read_manifest("daily_market_state")
    crosscheck = store.read_manifest("valuation_crosscheck")

    statuses = store.read_parquet("valuation_sync_status")
    successful_valuation = set(
        statuses.loc[statuses["status"] == "success", "symbol"].astype(str)
    )
    current_covered = len(active_symbols & successful_valuation)
    current_coverage = current_covered / len(active_symbols)
    state_coverage = market_state["coverage"]
    checks = {
        "valuation_current_coverage": (
            current_coverage >= minimum_current_valuation_coverage
        ),
        "valuation_second_source": crosscheck.get("status") == "passed",
        "price_limit_has_full_history": price_limit["row_count"] >= 10_000_000,
        "official_status_has_full_history": official["row_count"] >= 10_000_000,
        "market_state_all_symbols": (
            state_coverage["successful_symbols"] == len(stocks)
            and state_coverage["failed_symbols"] == 0
        ),
        "known_st_ratio": (
            state_coverage["known_st_ratio"] >= minimum_known_st_ratio
        ),
        "partitioned_large_datasets": all(
            payload.get("partitioning")
            for payload in (valuation, price_limit, official, market_state)
        ),
    }
    manifest_hashes = {}
    for dataset in (
        "daily_valuation",
        "valuation_crosscheck",
        "daily_price_limit",
        "daily_official_status",
        "st_name_events",
        "risk_warning_events",
        "daily_market_state",
    ):
        path = store.manifest_path(dataset)
        manifest_hashes[dataset] = sha256_file(path)
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if all(checks.values()) else "failed",
        "thresholds": {
            "minimum_current_valuation_coverage": minimum_current_valuation_coverage,
            "minimum_known_st_ratio": minimum_known_st_ratio,
        },
        "universe": {
            "historical_stocks": int(len(stocks)),
            "current_active_stocks": len(active_symbols),
        },
        "valuation": {
            "quality_grade": valuation["quality_grade"],
            "rows": valuation["row_count"],
            "successful_symbols": valuation["coverage"]["successful_symbols"],
            "failed_historical_symbols": valuation["coverage"]["failed_symbols"],
            "current_covered": current_covered,
            "current_coverage_ratio": current_coverage,
            "date_range": valuation["date_range"],
            "crosscheck": {
                "requested_symbols": crosscheck["requested_symbols"],
                "successful_symbols": crosscheck["successful_symbols"],
                "metrics": crosscheck["metrics"],
                "status": crosscheck["status"],
            },
        },
        "market_state": {
            "overall_quality_grade": market_state["quality_grade"],
            "rows": market_state["row_count"],
            "successful_symbols": state_coverage["successful_symbols"],
            "failed_symbols": state_coverage["failed_symbols"],
            "known_st_rows": state_coverage["known_st_rows"],
            "known_st_ratio": state_coverage["known_st_ratio"],
            "unknown_st_rows": (
                market_state["row_count"] - state_coverage["known_st_rows"]
            ),
            "exact_limit_rows": state_coverage["exact_limit_rows"],
            "exact_limit_ratio": state_coverage["exact_limit_ratio"],
            "paused_rows": state_coverage["paused_rows"],
            "date_range": market_state["date_range"],
        },
        "reference_sources": {
            "price_limit_rows": price_limit["row_count"],
            "price_limit_symbols": price_limit["coverage"]["symbols"],
            "official_status_rows": official["row_count"],
            "official_status_end": official["date_range"]["end"],
            "szse_name_event_rows": names["row_count"],
            "szse_name_event_quality": names["quality_grade"],
            "risk_warning_event_rows": risk_events["row_count"],
            "risk_warning_event_quality": risk_events["quality_grade"],
            "risk_warning_announcement_events": risk_events["coverage"][
                "announcement_events"
            ],
        },
        "checks": checks,
        "manifest_sha256": manifest_hashes,
        "limitations": [
            "上交所和北交所 2023-06 后由最后显式状态与发行人公告标题承接，未解析公告 PDF，质量为 B。",
            "估值可能按数据商后来修订的财务值重算，属于 B 级而非严格 PIT A。",
            (
                f"{valuation['coverage']['failed_symbols']} 个无估值的历史代码均逐只保留"
                "失败原因；当前有效股票覆盖率单独验收。"
            ),
        ],
    }
    store.write_json_report("market_valuation_verification", report)
    return report
