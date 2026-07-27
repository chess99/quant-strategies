"""解析聚宽结构化日志并与本地黄金结果比较。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .jq_compat import to_local_symbol


def parse_joinquant_small_cap_log(
    text: str,
    *,
    selected_count: int = 10,
) -> dict[str, pd.DataFrame]:
    candidates = []
    orders = []
    holdings = []
    for raw_line in text.splitlines():
        marker_position = raw_line.find("QR_")
        if marker_position < 0:
            continue
        parts = raw_line[marker_position:].strip().split("|")
        marker = parts[0]
        if marker == "QR_CANDIDATES" and len(parts) >= 6:
            execution_date, observation_date = pd.to_datetime(parts[1:3])
            codes = [code for code in parts[5].split(",") if code]
            for rank, code in enumerate(codes, start=1):
                candidates.append(
                    {
                        "execution_date": execution_date,
                        "observation_date": observation_date,
                        "universe_count": int(parts[3]),
                        "reported_candidate_count": int(parts[4]),
                        "symbol": to_local_symbol(code),
                        "rank": rank,
                        "selected": rank <= selected_count,
                    }
                )
        elif marker == "QR_ORDER" and len(parts) >= 5:
            record = {
                "execution_date": pd.Timestamp(parts[1]),
                "side": parts[2],
                "symbol": to_local_symbol(parts[3]),
                "status": parts[4],
                "requested_shares": None,
                "filled_shares": None,
            }
            if parts[4] != "none" and len(parts) >= 7:
                record.update(
                    {
                        "requested_shares": int(float(parts[4])),
                        "filled_shares": int(float(parts[5])),
                        "status": parts[6],
                    }
                )
            orders.append(record)
        elif marker == "QR_HOLDINGS" and len(parts) >= 5:
            codes = [code for code in parts[3].split(",") if code]
            for code in codes:
                holdings.append(
                    {
                        "execution_date": pd.Timestamp(parts[1]),
                        "reported_holding_count": int(parts[2]),
                        "symbol": to_local_symbol(code),
                        "total_value": float(parts[4]),
                    }
                )
    return {
        "candidates": pd.DataFrame(candidates),
        "orders": pd.DataFrame(orders),
        "holdings": pd.DataFrame(holdings),
    }


def load_joinquant_stats(path: Path | str) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if "stats" in payload and isinstance(payload["stats"], dict):
        payload = payload["stats"]
    aliases = {
        "total_return": ("total_return", "algorithm_return"),
        "annualized_return": ("annualized_return", "annual_algo_return"),
        "maximum_drawdown": ("maximum_drawdown", "max_drawdown"),
        "sharpe": ("sharpe",),
    }
    result = {}
    for target, names in aliases.items():
        for name in names:
            if name in payload and payload[name] is not None:
                result[target] = float(payload[name])
                break
        if target not in result:
            raise ValueError(f"JoinQuant stats is missing {target}: aliases={names}")
    return result


def _sets_by_date(frame: pd.DataFrame, date_column: str, symbol_column="symbol") -> dict:
    if frame.empty:
        return {}
    result = {}
    for date, group in frame.groupby(date_column):
        result[pd.Timestamp(date).normalize()] = set(group[symbol_column].astype(str))
    return result


def _overlap_rows(local_sets: dict, golden_sets: dict, label: str):
    rows = []
    for date in sorted(set(local_sets).union(golden_sets)):
        local = local_sets.get(date, set())
        golden = golden_sets.get(date, set())
        intersection = local.intersection(golden)
        denominator = max(len(local), len(golden), 1)
        rows.append(
            {
                "comparison": label,
                "execution_date": date,
                "local_count": len(local),
                "joinquant_count": len(golden),
                "intersection_count": len(intersection),
                "overlap_ratio": len(intersection) / denominator,
                "local_only": ",".join(sorted(local - golden)),
                "joinquant_only": ",".join(sorted(golden - local)),
            }
        )
    return rows


def compare_small_cap_results(
    local_result_dir: Path | str,
    parsed_log: dict[str, pd.DataFrame],
    joinquant_metrics: dict,
) -> tuple[dict, pd.DataFrame]:
    return _compare_portfolio_results(
        local_result_dir,
        parsed_log,
        joinquant_metrics,
        candidate_filename="candidates-top50.csv",
    )


def compare_value_quality_results(
    local_result_dir: Path | str,
    parsed_log: dict[str, pd.DataFrame],
    joinquant_metrics: dict,
) -> tuple[dict, pd.DataFrame]:
    return _compare_portfolio_results(
        local_result_dir,
        parsed_log,
        joinquant_metrics,
        candidate_filename="candidates-top100.csv",
    )


def _compare_portfolio_results(
    local_result_dir: Path | str,
    parsed_log: dict[str, pd.DataFrame],
    joinquant_metrics: dict,
    *,
    candidate_filename: str,
) -> tuple[dict, pd.DataFrame]:
    local_dir = Path(local_result_dir)
    local_manifest = json.loads((local_dir / "manifest.json").read_text(encoding="utf-8"))
    local_candidates = pd.read_csv(
        local_dir / "raw" / candidate_filename, parse_dates=["execution_date"]
    )
    selected = local_candidates[local_candidates["selected"].astype(str).str.lower().eq("true")]
    local_holdings = pd.read_csv(
        local_dir / "raw" / "holdings-monthly.csv", parse_dates=["execution_date"]
    )
    local_orders = pd.read_csv(
        local_dir / "raw" / "orders.csv", parse_dates=["trade_date"]
    )
    jq_candidates = parsed_log["candidates"]
    jq_holdings = parsed_log["holdings"]
    jq_orders = parsed_log["orders"]
    overlap_rows = []
    overlap_rows.extend(
        _overlap_rows(
            _sets_by_date(selected, "execution_date"),
            _sets_by_date(jq_candidates[jq_candidates["selected"]], "execution_date"),
            "selected_candidates",
        )
    )
    overlap_rows.extend(
        _overlap_rows(
            _sets_by_date(local_holdings, "execution_date"),
            _sets_by_date(jq_holdings, "execution_date"),
            "holdings",
        )
    )
    local_order_events = local_orders.rename(columns={"trade_date": "execution_date"})
    overlap_rows.extend(
        _overlap_rows(
            _sets_by_date(local_order_events, "execution_date"),
            _sets_by_date(jq_orders, "execution_date"),
            "ordered_symbols",
        )
    )
    overlaps = pd.DataFrame(overlap_rows)
    means = (
        overlaps.groupby("comparison")["overlap_ratio"].mean().to_dict()
        if not overlaps.empty
        else {}
    )
    local_metrics = local_manifest["metrics"]
    annualized_difference = local_metrics["annualized_return"] - joinquant_metrics[
        "annualized_return"
    ]
    drawdown_difference = local_metrics["maximum_drawdown"] - joinquant_metrics[
        "maximum_drawdown"
    ]
    expected_dates = int(
        pd.read_csv(local_dir / "raw" / "rebalance-coverage.csv").shape[0]
    )
    checks = {
        "joinquant_candidate_dates_complete": int(jq_candidates["execution_date"].nunique())
        == expected_dates,
        "joinquant_holding_dates_complete": int(jq_holdings["execution_date"].nunique())
        == expected_dates,
        "candidate_overlap_at_least_80_percent": means.get("selected_candidates", 0.0)
        >= 0.80,
        "holding_overlap_at_least_80_percent": means.get("holdings", 0.0) >= 0.80,
        "annualized_difference_at_most_3pp": abs(annualized_difference) <= 0.03,
        "drawdown_difference_at_most_3pp": abs(drawdown_difference) <= 0.03,
    }
    result = {
        "status": "passed" if all(checks.values()) else "failed",
        "expected_rebalance_dates": expected_dates,
        "joinquant_candidate_dates": int(jq_candidates["execution_date"].nunique()),
        "joinquant_holding_dates": int(jq_holdings["execution_date"].nunique()),
        "mean_overlap": means,
        "local_metrics": local_metrics,
        "joinquant_metrics": joinquant_metrics,
        "differences": {
            "annualized_return": annualized_difference,
            "maximum_drawdown": drawdown_difference,
        },
        "checks": checks,
    }
    return result, overlaps
