"""迭代 3 的机器可读验收报告。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .market_sync import read_qlib_symbol_features
from .store import ResearchDataStore, sha256_file


def _agreement(matches: int, compared: int) -> float:
    return matches / compared if compared else 0.0


def _evenly_spaced_symbols(frame: pd.DataFrame, count: int) -> list[str]:
    symbols = frame["symbol"].astype(str).sort_values().drop_duplicates().tolist()
    if len(symbols) <= count:
        return symbols
    positions = np.linspace(0, len(symbols) - 1, num=count, dtype=int)
    return [symbols[position] for position in positions]


def select_market_state_crosscheck_symbols(
    store: ResearchDataStore,
    *,
    sample_per_board: int = 64,
) -> list[str]:
    """按板块和历史停牌事件做确定性抽样，不把当前股票池当历史全集。"""

    if sample_per_board < 1:
        raise ValueError("sample_per_board must be positive")
    master = store.read_parquet("security_master")
    stocks = master[master["asset_type"] == "stock"].copy()
    selected: set[str] = set()
    for _, group in stocks.groupby("board", dropna=False):
        selected.update(_evenly_spaced_symbols(group, sample_per_board))
    try:
        statuses = store.read_parquet("market_state_sync_status")
    except FileNotFoundError:
        statuses = pd.DataFrame()
    if not statuses.empty and "paused_rows" in statuses:
        enriched = stocks[["symbol", "board"]].merge(
            statuses[["symbol", "paused_rows"]], on="symbol", how="left"
        )
        enriched["paused_rows"] = pd.to_numeric(
            enriched["paused_rows"], errors="coerce"
        ).fillna(0)
        for _, group in enriched[enriched["paused_rows"] > 0].groupby(
            "board", dropna=False
        ):
            selected.update(
                group.sort_values(
                    ["paused_rows", "symbol"], ascending=[False, True]
                )["symbol"]
                .head(max(8, sample_per_board // 2))
                .astype(str)
            )
    return sorted(selected)


def build_market_state_crosscheck(
    store: ResearchDataStore,
    *,
    qlib_root: Path | str,
    symbols: Iterable[str] | None = None,
    sample_per_board: int = 64,
    minimum_paused_agreement: float = 0.98,
    minimum_st_agreement: float = 0.99,
    minimum_limit_bound_agreement: float = 0.995,
) -> dict:
    """交叉核验 Baostock 状态、Dolt 限价和 Qlib 行情三个独立事实层。"""

    qlib_root = Path(qlib_root).resolve()
    calendar_path = qlib_root / "calendars" / "day.txt"
    calendar = pd.DatetimeIndex(
        pd.to_datetime(
            calendar_path.read_text(encoding="utf-8").splitlines(),
            errors="raise",
        )
    ).normalize()
    master = store.read_parquet("security_master")
    stocks = master[master["asset_type"] == "stock"].copy()
    requested = (
        list(dict.fromkeys(str(symbol) for symbol in symbols))
        if symbols is not None
        else select_market_state_crosscheck_symbols(
            store, sample_per_board=sample_per_board
        )
    )
    known = set(stocks["symbol"].astype(str))
    unknown = sorted(set(requested).difference(known))
    if unknown:
        raise ValueError(f"crosscheck symbols are outside stock master: {unknown}")
    board_by_symbol = stocks.set_index("symbol")["board"].astype(str).to_dict()

    counts = {
        "paused_compared": 0,
        "paused_matches": 0,
        "st_compared": 0,
        "st_matches": 0,
        "bounds_compared": 0,
        "bounds_matches": 0,
        "one_price_limit_events": 0,
        "buy_blocked_events": 0,
        "sell_blocked_events": 0,
    }
    mismatch_samples: list[dict] = []
    event_samples: list[dict] = []
    checked: list[str] = []
    failures: list[dict] = []
    tolerance = 0.011

    for symbol in requested:
        try:
            features = read_qlib_symbol_features(qlib_root, symbol, calendar)
            factor = pd.to_numeric(features["factor"], errors="coerce").replace(
                0.0, np.nan
            )
            quotes = features[["symbol", "trade_date"]].copy()
            for field in ("open", "high", "low", "close"):
                quotes[f"raw_{field}"] = (
                    pd.to_numeric(features[field], errors="coerce") / factor
                )
            volume = pd.to_numeric(features["volume"], errors="coerce")
            quotes["qlib_paused"] = (
                quotes[["raw_open", "raw_high", "raw_low", "raw_close"]]
                .isna()
                .any(axis=1)
                | volume.fillna(0.0).le(0.0)
            )

            official = store.read_symbol_partitions(
                "daily_official_status",
                [symbol],
                columns=["symbol", "trade_date", "paused", "is_st"],
                strict=False,
            )
            limits = store.read_symbol_partitions(
                "daily_price_limit",
                [symbol],
                columns=[
                    "symbol",
                    "trade_date",
                    "high_limit",
                    "low_limit",
                    "is_st",
                ],
                strict=False,
            )
            if not official.empty:
                status_check = official.merge(
                    quotes[["symbol", "trade_date", "qlib_paused"]],
                    on=["symbol", "trade_date"],
                    how="inner",
                    validate="one_to_one",
                )
                status_matches = status_check["paused"].astype(bool).eq(
                    status_check["qlib_paused"].astype(bool)
                )
                counts["paused_compared"] += len(status_check)
                counts["paused_matches"] += int(status_matches.sum())
                for row in status_check.loc[~status_matches].head(3).itertuples():
                    if len(mismatch_samples) >= 20:
                        break
                    mismatch_samples.append(
                        {
                            "kind": "paused",
                            "symbol": symbol,
                            "trade_date": row.trade_date.strftime("%Y-%m-%d"),
                            "official": bool(row.paused),
                            "qlib": bool(row.qlib_paused),
                        }
                    )
            if not official.empty and not limits.empty:
                st_check = official[["symbol", "trade_date", "is_st"]].merge(
                    limits[["symbol", "trade_date", "is_st"]],
                    on=["symbol", "trade_date"],
                    suffixes=("_official", "_limit"),
                    how="inner",
                    validate="one_to_one",
                )
                st_check = st_check.dropna(
                    subset=["is_st_official", "is_st_limit"]
                )
                st_matches = st_check["is_st_official"].astype(bool).eq(
                    st_check["is_st_limit"].astype(bool)
                )
                counts["st_compared"] += len(st_check)
                counts["st_matches"] += int(st_matches.sum())
            if not limits.empty:
                price_check = limits.merge(
                    quotes,
                    on=["symbol", "trade_date"],
                    how="inner",
                    validate="one_to_one",
                )
                finite = price_check.dropna(
                    subset=["raw_open", "raw_high", "raw_low", "raw_close", "high_limit", "low_limit"]
                ).copy()
                bounds_matches = finite["raw_high"].le(
                    finite["high_limit"] + tolerance
                ) & finite["raw_low"].ge(finite["low_limit"] - tolerance)
                counts["bounds_compared"] += len(finite)
                counts["bounds_matches"] += int(bounds_matches.sum())
                for row in finite.loc[~bounds_matches].head(3).itertuples():
                    if len(mismatch_samples) >= 20:
                        break
                    mismatch_samples.append(
                        {
                            "kind": "price_bounds",
                            "symbol": symbol,
                            "trade_date": row.trade_date.strftime("%Y-%m-%d"),
                            "raw_high": float(row.raw_high),
                            "high_limit": float(row.high_limit),
                            "raw_low": float(row.raw_low),
                            "low_limit": float(row.low_limit),
                        }
                    )
                one_price = finite[
                    ["raw_open", "raw_high", "raw_low", "raw_close"]
                ].max(axis=1).sub(
                    finite[["raw_open", "raw_high", "raw_low", "raw_close"]].min(
                        axis=1
                    )
                ).le(0.001)
                at_high = finite["raw_open"].ge(finite["high_limit"] - 0.001)
                at_low = finite["raw_open"].le(finite["low_limit"] + 0.001)
                one_price_limit = one_price & (at_high | at_low)
                counts["one_price_limit_events"] += int(one_price_limit.sum())
                counts["buy_blocked_events"] += int(at_high.sum())
                counts["sell_blocked_events"] += int(at_low.sum())
                for row in finite.loc[one_price_limit].head(3).itertuples():
                    if len(event_samples) >= 20:
                        break
                    event_samples.append(
                        {
                            "symbol": symbol,
                            "trade_date": row.trade_date.strftime("%Y-%m-%d"),
                            "raw_open": float(row.raw_open),
                            "high_limit": float(row.high_limit),
                            "low_limit": float(row.low_limit),
                            "side": "buy" if row.raw_open >= row.high_limit - 0.001 else "sell",
                        }
                    )
            checked.append(symbol)
        except Exception as exc:  # noqa: BLE001 - audit must preserve per-symbol failure
            failures.append(
                {"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"}
            )

    paused_ratio = _agreement(counts["paused_matches"], counts["paused_compared"])
    st_ratio = _agreement(counts["st_matches"], counts["st_compared"])
    bounds_ratio = _agreement(counts["bounds_matches"], counts["bounds_compared"])
    sampled_boards = pd.Series(
        [board_by_symbol[symbol] for symbol in checked], dtype="object"
    ).value_counts().sort_index().to_dict()
    expected_boards = set(stocks["board"].astype(str).unique())
    checks = {
        "all_requested_symbols_checked": len(checked) == len(requested) and not failures,
        "all_stock_boards_sampled": expected_boards.issubset(sampled_boards),
        "paused_cross_source_rows_present": counts["paused_compared"] > 0,
        "paused_agreement": paused_ratio >= minimum_paused_agreement,
        "st_cross_source_rows_present": counts["st_compared"] > 0,
        "st_agreement": st_ratio >= minimum_st_agreement,
        "price_limit_cross_source_rows_present": counts["bounds_compared"] > 0,
        "price_bounds_agreement": bounds_ratio >= minimum_limit_bound_agreement,
        "one_price_limit_events_observed": counts["one_price_limit_events"] > 0,
        "buy_blocked_events_observed": counts["buy_blocked_events"] > 0,
        "sell_blocked_events_observed": counts["sell_blocked_events"] > 0,
    }
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if all(checks.values()) else "failed",
        "sources": {
            "qlib_daily": {
                "provider": "qlib-community-cn",
                "calendar_path": str(calendar_path),
                "calendar_sha256": sha256_file(calendar_path),
            },
            "official_status": {
                "provider": store.read_manifest("daily_official_status").get(
                    "provider"
                ),
                "manifest_sha256": sha256_file(
                    store.manifest_path("daily_official_status")
                ),
            },
            "price_limit": {
                "provider": store.read_manifest("daily_price_limit").get("provider"),
                "manifest_sha256": sha256_file(
                    store.manifest_path("daily_price_limit")
                ),
            },
        },
        "scope": {
            "selection": (
                "explicit_symbols"
                if symbols is not None
                else f"deterministic_stratified_sample_per_board_{sample_per_board}"
            ),
            "historical_stock_master": int(len(stocks)),
            "symbols_requested": len(requested),
            "symbols_checked": len(checked),
            "boards": sampled_boards,
            "date_range": {
                "start": calendar.min().strftime("%Y-%m-%d"),
                "end": calendar.max().strftime("%Y-%m-%d"),
            },
        },
        "thresholds": {
            "minimum_paused_agreement": minimum_paused_agreement,
            "minimum_st_agreement": minimum_st_agreement,
            "minimum_limit_bound_agreement": minimum_limit_bound_agreement,
        },
        "comparisons": {
            "paused": {
                "compared_rows": counts["paused_compared"],
                "matching_rows": counts["paused_matches"],
                "agreement_ratio": paused_ratio,
            },
            "st": {
                "compared_rows": counts["st_compared"],
                "matching_rows": counts["st_matches"],
                "agreement_ratio": st_ratio,
            },
            "price_bounds": {
                "compared_rows": counts["bounds_compared"],
                "matching_rows": counts["bounds_matches"],
                "agreement_ratio": bounds_ratio,
            },
            "one_price_limit": {"event_rows": counts["one_price_limit_events"]},
            "buy_blocked": {"event_rows": counts["buy_blocked_events"]},
            "sell_blocked": {"event_rows": counts["sell_blocked_events"]},
        },
        "checks": checks,
        "mismatch_samples": mismatch_samples,
        "one_price_event_samples": event_samples,
        "failures": failures,
        "limitations": [
            "交叉核验是按板块与历史停牌事件确定性抽样，不替代三方全量逐行共识数据。",
            "一字板及买卖阻塞由独立 Qlib OHLC 与 Dolt 真实涨跌停价联合验证；免费源没有单独的一字板权威字段。",
        ],
    }
    store.write_json_report("market_state_crosscheck", report)
    return report


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
    state_crosscheck = store.read_manifest("market_state_crosscheck")

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
        "market_state_second_source": state_crosscheck.get("status") == "passed",
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
        "market_state_crosscheck",
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
            "crosscheck": {
                "symbols_checked": state_crosscheck["scope"]["symbols_checked"],
                "boards": state_crosscheck["scope"]["boards"],
                "paused_agreement_ratio": state_crosscheck["comparisons"][
                    "paused"
                ]["agreement_ratio"],
                "st_agreement_ratio": state_crosscheck["comparisons"]["st"][
                    "agreement_ratio"
                ],
                "price_bounds_agreement_ratio": state_crosscheck["comparisons"][
                    "price_bounds"
                ]["agreement_ratio"],
                "one_price_limit_events": state_crosscheck["comparisons"][
                    "one_price_limit"
                ]["event_rows"],
                "buy_blocked_events": state_crosscheck["comparisons"][
                    "buy_blocked"
                ]["event_rows"],
                "sell_blocked_events": state_crosscheck["comparisons"][
                    "sell_blocked"
                ]["event_rows"],
                "status": state_crosscheck["status"],
            },
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
