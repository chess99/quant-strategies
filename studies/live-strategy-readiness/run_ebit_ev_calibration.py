"""在公开窗口校准 EBIT/EV 单因子的点时本地重建。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


STUDY_DIR = Path(__file__).resolve().parent
ROOT = STUDY_DIR.parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quant_research.backtest import (  # noqa: E402
    BacktestConfig,
    CostModel,
    DailyBacktester,
    build_delisting_actions,
    performance_metrics,
)
from quant_research.data.store import ResearchDataStore  # noqa: E402
from quant_research.full_market import (  # noqa: E402
    build_asof_cross_sections,
    build_exact_cross_sections,
    build_fundamental_cross_sections,
)
from quant_research.portal import LocalDataPortal, QlibDailyBarSource  # noqa: E402


CANDIDATE_ID = "ebit-ev-value"
CANDIDATE_DIR = STUDY_DIR / "results" / CANDIDATE_ID
SOURCE_PATH = (
    ROOT
    / "joinquant_archive"
    / "sources"
    / "2025年度精选策略"
    / "77.超强单因子策略（EBIT,EV）.py"
)
CALIBRATION_START = pd.Timestamp("2009-01-05")
CALIBRATION_END = pd.Timestamp("2019-12-31")
INITIAL_CASH = 10_000_000.0
HOLDING_COUNT = 50
QLIB_DIR = Path("D:/code/_open-source/_data/qlib/cn_data")

PUBLIC_METRICS = {
    "annualized_return": 0.22545580458148,
    "maximum_drawdown": 0.39627228319793,
    "sharpe": 0.70774727493142,
}
TOLERANCES = {
    "annualized_return": 0.05,
    "maximum_drawdown": 0.07,
    "sharpe": 0.20,
    "minimum_median_holdings": 40,
    "minimum_valid_month_ratio": 0.90,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_symbol_hash(symbols) -> str:
    return hashlib.sha256("\n".join(sorted(symbols)).encode("utf-8")).hexdigest()


def month_execution_observation_dates(calendar_or_portal, start_date, end_date):
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    if hasattr(calendar_or_portal, "calendar"):
        padded = calendar_or_portal.calendar(start - pd.Timedelta(days=20), end)
    else:
        padded = pd.DatetimeIndex(pd.to_datetime(calendar_or_portal)).normalize()
    padded = padded.sort_values().unique()
    run_calendar = padded[(padded >= start) & (padded <= end)]
    rows = []
    previous_month = None
    for date in run_calendar:
        month = date.to_period("M")
        if month == previous_month:
            continue
        position = padded.get_loc(date)
        if position == 0:
            raise ValueError("calendar requires a prior observation session")
        rows.append(
            {
                "execution_date": pd.Timestamp(date),
                "observation_date": pd.Timestamp(padded[position - 1]),
            }
        )
        previous_month = month
    return pd.DatetimeIndex(run_calendar), pd.DataFrame(rows)


def rank_candidates(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    required = ["market_cap", "interest_bearing_debt", "cash", "ebit"]
    for column in required:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna(subset=["symbol", *required])
    data["enterprise_value"] = (
        data["market_cap"] + data["interest_bearing_debt"] - data["cash"]
    )
    data = data[data["ebit"].gt(0) & data["enterprise_value"].gt(0)].copy()
    data["ebit_ev"] = data["ebit"] / data["enterprise_value"]
    data = data[np.isfinite(data["ebit_ev"])].copy()
    return data.sort_values(
        ["ebit_ev", "symbol"], ascending=[False, True], kind="stable"
    ).reset_index(drop=True)


def _snapshot_key(store: ResearchDataStore, schedule: pd.DataFrame) -> tuple[str, dict]:
    payload = {
        "observations": [
            pd.Timestamp(value).strftime("%Y-%m-%d")
            for value in schedule["observation_date"]
        ],
        "manifests": {
            name: sha256_file(store.manifest_path(name))
            for name in ("daily_valuation", "fundamentals_pit", "security_master")
        },
        "fields": ["market_cap", "ebit", "interest_bearing_debt", "cash"],
    }
    key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
    return key, payload


def load_or_build_factor_snapshots(
    store: ResearchDataStore,
    schedule: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    key, payload = _snapshot_key(store, schedule)
    cache = store.snapshot_dir / "live-strategy-readiness-ebit-ev" / key
    factor_path = cache / "factors.parquet"
    audit_path = cache / "audit.json"
    if factor_path.is_file() and audit_path.is_file():
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        if audit.get("key_payload") == payload:
            return pd.read_parquet(factor_path), audit["partition_scans"]
    valuation = build_asof_cross_sections(
        store,
        "daily_valuation",
        schedule["observation_date"],
        ["market_cap", "quality_grade"],
        maximum_age_days=10,
    )
    fundamentals = build_fundamental_cross_sections(
        store,
        "fundamentals_pit",
        schedule["observation_date"],
        ["ebit", "interest_bearing_debt", "cash", "quality_grade"],
    )
    merged = valuation.frame.merge(
        fundamentals.frame,
        on=["observation_date", "symbol"],
        how="inner",
        suffixes=("_valuation", "_fundamental"),
        validate="one_to_one",
    )
    cache.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(factor_path, index=False)
    scans = {"valuation": valuation.audit, "fundamentals": fundamentals.audit}
    audit_path.write_text(
        json.dumps(
            {"schema_version": 1, "key_payload": payload, "partition_scans": scans},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return merged, scans


def build_targets(
    store: ResearchDataStore,
    schedule: pd.DataFrame,
) -> tuple[dict[pd.Timestamp, list[str]], pd.DataFrame, pd.DataFrame, dict]:
    factors, scans = load_or_build_factor_snapshots(store, schedule)
    master = store.read_parquet("security_master")
    master = master[
        master["asset_type"].eq("stock") & master["exchange"].isin(["XSHG", "XSHE"])
    ].copy()
    master["start_date"] = pd.to_datetime(master["start_date"]).dt.normalize()
    master["end_date"] = pd.to_datetime(master["end_date"]).dt.normalize()
    factors = factors.merge(
        master[["symbol", "exchange", "start_date", "end_date"]],
        on="symbol",
        how="inner",
        validate="many_to_one",
    )
    targets = {}
    candidate_rows = []
    coverage_rows = []
    for row in schedule.itertuples(index=False):
        cross = factors[factors["observation_date"].eq(row.observation_date)].copy()
        cross = cross[
            cross["start_date"].le(row.observation_date)
            & cross["end_date"].ge(row.observation_date)
            & cross["quality_grade_valuation"].eq("B")
            & cross["quality_grade_fundamental"].eq("B")
        ]
        ranked = rank_candidates(cross)
        selected = ranked.head(HOLDING_COUNT).copy()
        targets[pd.Timestamp(row.execution_date)] = selected["symbol"].tolist()
        archived = ranked.head(100).copy()
        archived["rank"] = range(1, len(archived) + 1)
        archived["selected"] = archived["rank"].le(HOLDING_COUNT)
        archived["execution_date"] = row.execution_date
        archived["candidate_count"] = len(ranked)
        archived["candidate_sha256"] = stable_symbol_hash(ranked["symbol"])
        candidate_rows.append(archived)
        coverage_rows.append(
            {
                "execution_date": row.execution_date,
                "observation_date": row.observation_date,
                "active_proxy_universe": int(
                    (
                        master["start_date"].le(row.observation_date)
                        & master["end_date"].ge(row.observation_date)
                    ).sum()
                ),
                "factor_merged_rows": len(cross),
                "valid_candidates": len(ranked),
                "selected_count": len(selected),
                "selected_sha256": stable_symbol_hash(selected["symbol"]),
                "future_notice_rows": int(
                    pd.to_datetime(selected.get("notice_date", pd.Series(dtype="datetime64[ns]")))
                    .gt(row.observation_date)
                    .sum()
                ),
            }
        )
    return (
        targets,
        pd.concat(candidate_rows, ignore_index=True),
        pd.DataFrame(coverage_rows),
        scans,
    )


def calibration_decision(metrics: dict[str, Any]) -> dict[str, Any]:
    differences = {
        key: abs(metrics[key] - PUBLIC_METRICS[key])
        for key in ("annualized_return", "maximum_drawdown", "sharpe")
    }
    checks = {
        "annualized_return": differences["annualized_return"] <= TOLERANCES["annualized_return"],
        "maximum_drawdown": differences["maximum_drawdown"] <= TOLERANCES["maximum_drawdown"],
        "sharpe": differences["sharpe"] <= TOLERANCES["sharpe"],
        "median_holdings": metrics["median_holdings"] >= TOLERANCES["minimum_median_holdings"],
        "valid_month_ratio": metrics["valid_month_ratio"] >= TOLERANCES["minimum_valid_month_ratio"],
    }
    return {
        "calibration_passed": bool(all(checks.values())),
        "source_vintage_after": "B" if all(checks.values()) else "C",
        "checks": checks,
        "differences": differences,
        "post_publication_performance_calculated": False,
        "parameter_selection_used": False,
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    return value


def _simulate(
    store: ResearchDataStore,
    portal: LocalDataPortal,
    calendar: pd.DatetimeIndex,
    targets: dict[pd.Timestamp, list[str]],
) -> tuple[DailyBacktester, pd.DataFrame]:
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
    actions = build_delisting_actions(
        store.read_parquet("delisting_events"),
        store.read_parquet("security_master"),
        bars,
    )
    engine = DailyBacktester(
        bars,
        state,
        asset_types={symbol: "stock" for symbol in selected_symbols},
        config=BacktestConfig(
            initial_cash=INITIAL_CASH,
            maximum_volume_ratio=1.0,
            slippage_rate=0.0,
            allow_unknown_st=False,
            minimum_state_quality="B",
        ),
        costs=CostModel(
            buy_commission=0.0003,
            sell_commission=0.0003,
            minimum_commission=5.0,
        ),
        corporate_actions=actions,
    )
    active_target = None
    pending = False
    rebalance_rows = []
    for date in calendar:
        is_rebalance = date in targets
        if is_rebalance:
            active_target = targets[date]
            pending = True
        if pending and active_target:
            before = len(engine.order_records)
            engine.rebalance_to_weights(
                date,
                {symbol: 1.0 / len(active_target) for symbol in active_target},
                execution="open",
            )
            new_orders = engine.orders.iloc[before:]
            incomplete = (
                not new_orders.empty
                and new_orders["unfilled_shares"].gt(0).any()
            )
            wrong_symbols = set(engine.positions) != set(active_target)
            pending = bool(incomplete or wrong_symbols)
            if is_rebalance:
                rebalance_rows.append(
                    {
                        "execution_date": date,
                        "target_count": len(active_target),
                        "actual_holding_count": len(engine.positions),
                        "pending_after_first_attempt": pending,
                        "orders_first_attempt": len(new_orders),
                    }
                )
        engine.mark_close(date)
    return engine, pd.DataFrame(rebalance_rows)


def _write_outputs(
    store: ResearchDataStore,
    metrics: dict[str, Any],
    decision: dict[str, Any],
    engine: DailyBacktester,
    candidates: pd.DataFrame,
    coverage: pd.DataFrame,
    rebalance: pd.DataFrame,
    scans: dict,
) -> None:
    CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)
    raw = CANDIDATE_DIR / "raw"
    raw.mkdir(exist_ok=True)
    pd.DataFrame([{"scenario": "local-public-window-calibration", **metrics}]).to_csv(
        CANDIDATE_DIR / "version-calibration.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(
        [
            {"scenario": "published-joinquant", **PUBLIC_METRICS},
            {"scenario": "local-public-window-calibration", **metrics},
        ]
    ).to_csv(CANDIDATE_DIR / "original-vs-causal.csv", index=False, encoding="utf-8-sig")
    outputs = {
        "version-calibration__equity.csv": engine.equity,
        "version-calibration__orders.csv": engine.orders,
        "version-calibration__trades.csv": engine.trades,
        "version-calibration__holdings.csv": engine.holdings,
        "version-calibration__candidates.csv": candidates,
        "version-calibration__coverage.csv": coverage,
        "version-calibration__rebalances.csv": rebalance,
    }
    for name, frame in outputs.items():
        frame.to_csv(raw / name, index=False, encoding="utf-8")
    (CANDIDATE_DIR / "version-calibration-decision.json").write_text(
        json.dumps(_json_safe(decision), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    data_manifests = {}
    for name in (
        "security_master",
        "daily_valuation",
        "fundamentals_pit",
        "daily_market_state",
        "delisting_events",
    ):
        path = store.manifest_path(name)
        data_manifests[name] = {"path": str(path), "sha256": sha256_file(path)}
    manifest = {
        "schema_version": 1,
        "study_id": "live-strategy-readiness",
        "candidate_id": CANDIDATE_ID,
        "run_id": "public-window-version-calibration-v1",
        "created_at": "2026-08-25",
        "period": {"start": "2009-01-05", "end": "2019-12-31"},
        "source_path": SOURCE_PATH.relative_to(ROOT).as_posix(),
        "source_sha256": sha256_file(SOURCE_PATH),
        "engine_path": Path(__file__).resolve().relative_to(ROOT).as_posix(),
        "engine_sha256": sha256_file(Path(__file__).resolve()),
        "data_manifests": data_manifests,
        "partition_scans": scans,
        "universe_proxy": "all point-in-time active XSHG and XSHE stocks",
        "post_publication_data_used": False,
        "parameter_fitting_used": False,
        "public_metrics": PUBLIC_METRICS,
        "local_metrics": metrics,
        "decision": decision,
    }
    (CANDIDATE_DIR / "version-calibration-manifest.json").write_text(
        json.dumps(_json_safe(manifest), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run(data_root: Path | None = None, qlib_dir: Path = QLIB_DIR):
    store = ResearchDataStore(data_root)
    portal = LocalDataPortal(store, QlibDailyBarSource(qlib_dir))
    calendar, schedule = month_execution_observation_dates(
        portal, CALIBRATION_START, CALIBRATION_END
    )
    targets, candidates, coverage, scans = build_targets(store, schedule)
    engine, rebalance = _simulate(store, portal, calendar, targets)
    metrics = performance_metrics(engine.equity, engine.trades, trading_days=250)
    metrics.update(
        {
            "median_holdings": float(rebalance["actual_holding_count"].median()),
            "valid_month_ratio": float(coverage["selected_count"].eq(HOLDING_COUNT).mean()),
            "rebalance_count": len(rebalance),
            "selected_unique_symbols": len({symbol for values in targets.values() for symbol in values}),
            "future_notice_rows": int(coverage["future_notice_rows"].sum()),
            "rejected_order_count": len(engine.rejections),
        }
    )
    decision = calibration_decision(metrics)
    _write_outputs(
        store, metrics, decision, engine, candidates, coverage, rebalance, scans
    )
    return metrics, decision


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--qlib-dir", type=Path, default=QLIB_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    metrics, decision = run(args.data_root, args.qlib_dir)
    print(json.dumps(_json_safe({"metrics": metrics, "decision": decision}), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
