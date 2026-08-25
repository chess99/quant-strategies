"""运行“股债波动平衡”的首次未经调参发布后回放。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


STUDY_DIR = Path(__file__).resolve().parent
ROOT = STUDY_DIR.parents[1]
SRC = ROOT / "src"
for path in (STUDY_DIR, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_stock_bond_volatility_calibration as calibration  # noqa: E402
from quant_research.backtest import (  # noqa: E402
    BacktestConfig,
    CostModel,
    DailyBacktester,
    performance_metrics,
)
from quant_research.data.store import ResearchDataStore  # noqa: E402


CANDIDATE_ID = calibration.CANDIDATE_ID
CANDIDATE_DIR = calibration.CANDIDATE_DIR
SOURCE_PATH = calibration.SOURCE_PATH
OOS_START = pd.Timestamp("2020-08-17")
OOS_END = pd.Timestamp("2026-07-24")
INITIAL_CASH = 200_000.0
VERSION_DECISION_PATH = CANDIDATE_DIR / "version-calibration-decision.json"


@dataclass(frozen=True)
class Scenario:
    name: str
    method: str
    commission_rate: float
    minimum_commission: float
    slippage_rate: float
    maximum_volume_ratio: float
    cost_label: str


SCENARIOS = (
    Scenario(
        name="frozen-source-cost-proxy",
        method="dynamic-inverse-volatility",
        commission_rate=0.0003,
        minimum_commission=5.0,
        slippage_rate=0.0,
        maximum_volume_ratio=1.0,
        cost_label="platform-default proxy; source did not declare costs",
    ),
    Scenario(
        name="causal-baseline-cost",
        method="dynamic-inverse-volatility",
        commission_rate=0.0003,
        minimum_commission=5.0,
        slippage_rate=0.0005,
        maximum_volume_ratio=0.01,
        cost_label="realistic baseline",
    ),
    Scenario(
        name="causal-double-cost",
        method="dynamic-inverse-volatility",
        commission_rate=0.0006,
        minimum_commission=5.0,
        slippage_rate=0.0010,
        maximum_volume_ratio=0.01,
        cost_label="double friction",
    ),
    Scenario(
        name="static-prior-weekly",
        method="static-prior",
        commission_rate=0.0003,
        minimum_commission=5.0,
        slippage_rate=0.0005,
        maximum_volume_ratio=0.01,
        cost_label="realistic baseline",
    ),
    Scenario(
        name="equal-weight-weekly",
        method="equal-weight",
        commission_rate=0.0003,
        minimum_commission=5.0,
        slippage_rate=0.0005,
        maximum_volume_ratio=0.01,
        cost_label="realistic baseline",
    ),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def available_symbols(close: pd.DataFrame, observation_date) -> list[str]:
    observation = pd.Timestamp(observation_date).normalize()
    history = close.loc[close.index <= observation]
    return [
        symbol
        for symbol in calibration.LOCAL_SYMBOLS
        if symbol in history
        and not history[symbol].dropna().empty
        and history[symbol].dropna().index.max() == observation
    ]


def static_weights(
    close: pd.DataFrame,
    observation_date,
    *,
    method: str,
) -> dict[str, float]:
    available = available_symbols(close, observation_date)
    if not available:
        return {}
    if method == "static-prior":
        raw = calibration.PRIOR_WEIGHTS_LOCAL.loc[available]
        return (raw / raw.sum()).to_dict()
    if method == "equal-weight":
        return {symbol: 1.0 / len(available) for symbol in available}
    raise ValueError(f"unsupported static method: {method}")


def scenario_weights(
    close: pd.DataFrame,
    observation_date,
    method: str,
) -> tuple[dict[str, float], dict[str, Any]]:
    if method == "dynamic-inverse-volatility":
        return calibration.target_weights(close, observation_date)
    weights = static_weights(close, observation_date, method=method)
    return weights, {
        "observation_date": pd.Timestamp(observation_date).strftime("%Y-%m-%d"),
        "volatilities": {},
        "weights": weights,
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


def run_scenario(
    bars: pd.DataFrame,
    market_state: pd.DataFrame,
    scenario: Scenario,
) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    close = bars.pivot(
        index="trade_date", columns="symbol", values="adjusted_close"
    ).sort_index()
    oos_bars = bars[bars["trade_date"].between(OOS_START, OOS_END)].copy()
    engine_bars = oos_bars[
        ["symbol", "trade_date", "adjusted_open", "adjusted_close", "volume"]
    ].rename(columns={"adjusted_open": "open", "adjusted_close": "close"})
    oos_state = market_state[market_state["trade_date"].between(OOS_START, OOS_END)].copy()
    calendar = pd.DatetimeIndex(sorted(oos_bars["trade_date"].unique()))
    prior_dates = close.index[close.index < OOS_START]
    if prior_dates.empty:
        raise ValueError("no pre-OOS observation date is available")
    previous_date = pd.Timestamp(prior_dates.max())
    engine = DailyBacktester(
        engine_bars,
        oos_state,
        asset_types={symbol: "etf" for symbol in calibration.LOCAL_SYMBOLS},
        config=BacktestConfig(
            initial_cash=INITIAL_CASH,
            lot_size=100,
            maximum_volume_ratio=scenario.maximum_volume_ratio,
            slippage_rate=scenario.slippage_rate,
            t_plus_one_asset_types=("etf",),
            minimum_state_quality="B",
        ),
        costs=CostModel(
            buy_commission=scenario.commission_rate,
            sell_commission=scenario.commission_rate,
            minimum_commission=scenario.minimum_commission,
            etf_buy_commission=scenario.commission_rate,
            etf_sell_commission=scenario.commission_rate,
            etf_minimum_commission=scenario.minimum_commission,
        ),
    )
    target_rows = []
    for trade_date in calendar:
        should_observe = not engine.positions or pd.Timestamp(trade_date).weekday() == 4
        if should_observe:
            weights, diagnostics = scenario_weights(
                close, previous_date, scenario.method
            )
            actual = calibration.actual_weights(engine, trade_date)
            drift = calibration.drift_l1(actual, weights)
            rebalance = bool(weights) and (
                engine.cash > calibration.CASH_TRIGGER
                or drift > calibration.DRIFT_THRESHOLD
            )
            target_rows.append(
                {
                    "trade_date": pd.Timestamp(trade_date),
                    "observation_date": pd.Timestamp(previous_date),
                    "method": scenario.method,
                    "rebalance": rebalance,
                    "cash_before": engine.cash,
                    "drift_l1": drift,
                    "available_count": len(weights),
                    "weights_json": json.dumps(weights, sort_keys=True),
                    "volatilities_json": json.dumps(
                        diagnostics["volatilities"], sort_keys=True
                    ),
                }
            )
            if rebalance:
                engine.rebalance_to_weights(trade_date, weights, execution="open")
        engine.mark_close(trade_date)
        previous_date = pd.Timestamp(trade_date)
    equity = engine.equity
    metrics = performance_metrics(equity, engine.trades, trading_days=250)
    returns = pd.to_numeric(equity["daily_return"], errors="coerce").fillna(0.0)
    downside = returns[returns < 0.0]
    sortino = (
        returns.mean() * 250.0 / (downside.std(ddof=1) * math.sqrt(250.0))
        if len(downside) > 1 and downside.std(ddof=1) > 0
        else float("nan")
    )
    targets = pd.DataFrame(target_rows)
    metrics.update(
        {
            "scenario": scenario.name,
            "method": scenario.method,
            "cost_label": scenario.cost_label,
            "period_start": OOS_START.strftime("%Y-%m-%d"),
            "period_end": OOS_END.strftime("%Y-%m-%d"),
            "initial_cash": INITIAL_CASH,
            "sortino": float(sortino),
            "trade_count": len(engine.trades),
            "order_count": len(engine.orders),
            "rejected_order_count": len(engine.rejections),
            "unfilled_shares": (
                int(pd.to_numeric(engine.orders["unfilled_shares"]).sum())
                if not engine.orders.empty
                else 0
            ),
            "total_fees": (
                float(pd.to_numeric(engine.fees_ledger["total_fees"]).sum())
                if not engine.fees_ledger.empty
                else 0.0
            ),
            "commission_rate": scenario.commission_rate,
            "minimum_commission": scenario.minimum_commission,
            "slippage_rate": scenario.slippage_rate,
            "maximum_volume_ratio": scenario.maximum_volume_ratio,
            "rebalance_count": int(targets["rebalance"].sum()),
            "target_event_count": len(targets),
            "average_exposure": 1.0 - metrics["average_cash_ratio"],
            "parameter_selection_used_oos": False,
        }
    )
    frames = {
        "equity": equity,
        "trades": engine.trades,
        "orders": engine.orders,
        "holdings": engine.holdings,
        "targets": targets,
    }
    return metrics, frames


def write_outputs(
    store: ResearchDataStore,
    lof_evidence: list[dict[str, Any]],
    results: list[dict[str, Any]],
    frames_by_scenario: dict[str, dict[str, pd.DataFrame]],
) -> None:
    CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)
    raw_dir = CANDIDATE_DIR / "raw"
    raw_dir.mkdir(exist_ok=True)
    rows = []
    for result in results:
        row = {key: value for key, value in result.items() if key != "yearly_returns"}
        row["yearly_returns_json"] = json.dumps(
            result["yearly_returns"], ensure_ascii=False, sort_keys=True
        )
        rows.append(row)
        for label, frame in frames_by_scenario[result["scenario"]].items():
            frame.to_csv(
                raw_dir / f"{result['scenario']}__{label}.csv",
                index=False,
                encoding="utf-8",
            )
    oos = pd.DataFrame(rows)
    oos.to_csv(CANDIDATE_DIR / "oos.csv", index=False, encoding="utf-8-sig")
    calibration_row = pd.read_csv(CANDIDATE_DIR / "version-calibration.csv")
    comparison = pd.concat(
        [
            pd.DataFrame([calibration.PUBLIC_BACKTEST]),
            calibration_row,
            oos.assign(
                evidence_scope="post-publication replay",
                comparable_to_local=True,
            ),
        ],
        ignore_index=True,
        sort=False,
    )
    comparison.to_csv(
        CANDIDATE_DIR / "original-vs-causal.csv",
        index=False,
        encoding="utf-8-sig",
    )
    data_manifests = {}
    for dataset in ("etf_daily", "etf_master"):
        path = store.manifest_path(dataset)
        data_manifests[dataset] = {"path": str(path), "sha256": sha256_file(path)}
    manifest = {
        "schema_version": 1,
        "study_id": "live-strategy-readiness",
        "candidate_id": CANDIDATE_ID,
        "run_id": "untuned-post-publication-oos-v1",
        "created_at": "2026-08-25",
        "period": {
            "start": OOS_START.strftime("%Y-%m-%d"),
            "end": OOS_END.strftime("%Y-%m-%d"),
        },
        "source_path": SOURCE_PATH.relative_to(ROOT).as_posix(),
        "source_sha256": sha256_file(SOURCE_PATH),
        "engine_path": Path(__file__).resolve().relative_to(ROOT).as_posix(),
        "engine_sha256": sha256_file(Path(__file__).resolve()),
        "version_decision": {
            "path": VERSION_DECISION_PATH.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(VERSION_DECISION_PATH),
            "grade": "B",
        },
        "data_manifests": data_manifests,
        "lof_data": lof_evidence,
        "frozen_parameters": {
            "fund_pool": list(calibration.JQ_SYMBOLS),
            "prior_weights": calibration.PRIOR_WEIGHTS.tolist(),
            "volatility_window_days": calibration.VOLATILITY_WINDOW,
            "drift_l1_threshold": calibration.DRIFT_THRESHOLD,
            "cash_trigger_rmb": calibration.CASH_TRIGGER,
        },
        "parameter_selection_used_oos": False,
        "scenario_count": len(SCENARIOS),
        "scenarios": [asdict(item) for item in SCENARIOS],
        "artifacts": {
            "oos": "oos.csv",
            "comparison": "original-vs-causal.csv",
            "raw_pattern": "raw/{scenario}__{equity,trades,orders,holdings,targets}.csv",
        },
        "limitations": [
            "source vintage is B rather than strict A",
            "six ETF histories and two LOF histories use different B-grade providers",
            "QDII and LOF premium/discount, subscription and NAV divergence are not modeled",
            "ETF price-limit state is reconstructed from daily OHLC and previous close at B quality",
            "the public backtest has no order-level source hash or platform golden ledger",
        ],
        "results": _json_safe(results),
    }
    (CANDIDATE_DIR / "oos-run-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run(data_root: Path | None = None) -> list[dict[str, Any]]:
    store = ResearchDataStore(data_root)
    bars, lof_evidence = calibration.load_bars(store, refresh_lof=False)
    if bars["trade_date"].max() < OOS_END:
        raise ValueError(
            f"fund data ends at {bars['trade_date'].max():%Y-%m-%d}, "
            f"expected {OOS_END:%Y-%m-%d}"
        )
    market_state = calibration.build_market_state(bars)
    results = []
    frames_by_scenario = {}
    for scenario in SCENARIOS:
        metrics, frames = run_scenario(bars, market_state, scenario)
        results.append(metrics)
        frames_by_scenario[scenario.name] = frames
    write_outputs(store, lof_evidence, results, frames_by_scenario)
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    results = run(args.data_root)
    summary = [
        {
            "scenario": row["scenario"],
            "annualized_return": row["annualized_return"],
            "maximum_drawdown": row["maximum_drawdown"],
            "sharpe": row["sharpe"],
            "rebalance_count": row["rebalance_count"],
            "average_exposure": row["average_exposure"],
        }
        for row in results
    ]
    print(json.dumps(_json_safe(summary), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
