"""运行冻结沪深300成交量加权 RSRS 的首次发布后回放。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


STUDY_DIR = Path(__file__).resolve().parent
ROOT = STUDY_DIR.parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

BASE_PATH = STUDY_DIR / "run_csi300_volume_rsrs.py"
SPEC = importlib.util.spec_from_file_location("live_readiness_csi300_volume_rsrs_base", BASE_PATH)
base = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = base
SPEC.loader.exec_module(base)

from quant_research.backtest import (  # noqa: E402
    BacktestConfig,
    CostModel,
    DailyBacktester,
    performance_metrics,
)
from quant_research.data.store import ResearchDataStore  # noqa: E402
from quant_research.portal import QlibDailyBarSource  # noqa: E402


CANDIDATE_ID = base.CANDIDATE_ID
CANDIDATE_DIR = base.CANDIDATE_DIR
RISK_SYMBOL = "SH510300"
OOS_START = pd.Timestamp("2020-05-15")
OOS_END = pd.Timestamp("2026-07-23")
INITIAL_CASH = 1_000_000.0


@dataclass(frozen=True)
class Scenario:
    name: str
    method: str
    commission: float
    minimum_commission: float
    slippage: float
    maximum_volume_ratio: float


SCENARIOS = (
    Scenario("rsrs-baseline-cost", "rsrs", 0.0003, 5.0, 0.0005, 0.01),
    Scenario("rsrs-double-cost", "rsrs", 0.0006, 5.0, 0.0010, 0.01),
    Scenario("csi300-etf-buy-hold", "buy-hold", 0.0003, 5.0, 0.0005, 0.01),
    Scenario("static-50pct-etf-cash", "half-cash", 0.0003, 5.0, 0.0005, 0.01),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_etf_bars(store: ResearchDataStore) -> pd.DataFrame:
    bars = store.read_symbol_partitions(
        "etf_daily",
        [RISK_SYMBOL],
        columns=[
            "symbol",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "adjusted_open",
            "adjusted_close",
        ],
        strict=True,
    )
    bars["trade_date"] = pd.to_datetime(bars["trade_date"]).dt.normalize()
    return bars[bars["trade_date"].between(OOS_START, OOS_END)].copy()


def build_oos_targets(
    features: pd.DataFrame,
    calendar: pd.DatetimeIndex,
) -> tuple[dict[pd.Timestamp, int], pd.DataFrame]:
    scores = features.set_index("trade_date")["score"]
    all_signal_dates = pd.DatetimeIndex(features["trade_date"])
    prior_dates = all_signal_dates[all_signal_dates < calendar[0]]
    previous_date = prior_dates[-1] if len(prior_dates) else None
    state = 0
    targets = {}
    rows = []
    for trade_date in calendar:
        score = np.nan if previous_date is None else scores.get(previous_date, np.nan)
        previous_state = state
        if np.isfinite(score):
            if score > base.BUY_THRESHOLD and state == 0:
                state = 1
            elif score < base.SELL_THRESHOLD and state == 1:
                state = 0
        targets[pd.Timestamp(trade_date)] = state
        rows.append(
            {
                "trade_date": pd.Timestamp(trade_date),
                "observation_date": previous_date,
                "score": score,
                "target_position": state,
                "signal_transition": state - previous_state,
            }
        )
        previous_date = pd.Timestamp(trade_date)
    return targets, pd.DataFrame(rows)


def build_market_state(raw_bars: pd.DataFrame) -> pd.DataFrame:
    state = raw_bars[["symbol", "trade_date", "open", "high", "low", "close", "volume"]].copy()
    state["previous_close"] = state.groupby("symbol")["close"].shift(1)
    state["paused"] = state["volume"].fillna(0).le(0)
    state["is_st"] = False
    state["buy_blocked"] = (
        state["open"].div(state["previous_close"]).ge(1.095)
        & state["low"].div(state["previous_close"]).ge(1.095)
    )
    state["sell_blocked"] = (
        state["open"].div(state["previous_close"]).le(0.905)
        & state["high"].div(state["previous_close"]).le(0.905)
    )
    state["status_quality"] = "B"
    state["st_quality"] = "B"
    state["limit_quality"] = "B"
    return state[
        [
            "symbol",
            "trade_date",
            "paused",
            "is_st",
            "buy_blocked",
            "sell_blocked",
            "status_quality",
            "st_quality",
            "limit_quality",
        ]
    ]


def run_scenario(
    bars: pd.DataFrame,
    targets: dict[pd.Timestamp, int],
    scenario: Scenario,
) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    engine_bars = bars[
        ["symbol", "trade_date", "adjusted_open", "adjusted_close", "volume"]
    ].rename(columns={"adjusted_open": "open", "adjusted_close": "close"})
    engine = DailyBacktester(
        engine_bars,
        build_market_state(bars),
        asset_types={RISK_SYMBOL: "etf"},
        config=BacktestConfig(
            initial_cash=INITIAL_CASH,
            lot_size=100,
            maximum_volume_ratio=scenario.maximum_volume_ratio,
            slippage_rate=scenario.slippage,
            t_plus_one_asset_types=("stock",),
            minimum_state_quality="B",
        ),
        costs=CostModel(
            buy_commission=scenario.commission,
            sell_commission=scenario.commission,
            minimum_commission=scenario.minimum_commission,
            etf_buy_commission=scenario.commission,
            etf_sell_commission=scenario.commission,
            etf_minimum_commission=scenario.minimum_commission,
        ),
    )
    calendar = pd.DatetimeIndex(sorted(bars["trade_date"].unique()))
    previous_weight = 0.0
    for trade_date in calendar:
        if scenario.method == "rsrs":
            target_weight = float(targets[pd.Timestamp(trade_date)])
        elif scenario.method == "buy-hold":
            target_weight = 1.0
        elif scenario.method == "half-cash":
            target_weight = 0.5
        else:
            raise ValueError(f"unknown method: {scenario.method}")
        if target_weight != previous_weight:
            engine.rebalance_to_weights(
                trade_date,
                {RISK_SYMBOL: target_weight} if target_weight else {},
                execution="open",
            )
        engine.mark_close(trade_date)
        previous_weight = target_weight
    metrics = performance_metrics(engine.equity, engine.trades, trading_days=250)
    sell_count = 0 if engine.trades.empty else int(engine.trades["side"].eq("sell").sum())
    metrics.update(
        {
            "scenario": scenario.name,
            "method": scenario.method,
            "period_start": str(OOS_START.date()),
            "period_end": str(OOS_END.date()),
            "completed_positions": sell_count,
            "trade_count": len(engine.trades),
            "order_count": len(engine.orders),
            "rejected_order_count": len(engine.rejections),
            "commission": scenario.commission,
            "minimum_commission": scenario.minimum_commission,
            "slippage": scenario.slippage,
            "maximum_volume_ratio": scenario.maximum_volume_ratio,
            "parameter_selection_used_oos": False,
        }
    )
    return metrics, {
        "equity": engine.equity,
        "orders": engine.orders,
        "trades": engine.trades,
        "holdings": engine.holdings,
    }


def evaluate_oos(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_name = {row["scenario"]: row for row in results}
    strategy = by_name["rsrs-baseline-cost"]
    double = by_name["rsrs-double-cost"]
    buy_hold = by_name["csi300-etf-buy-hold"]
    half_cash = by_name["static-50pct-etf-cash"]
    gates = base.load_protocol()["promotion_gates_after_oos"]
    passed = {
        "sharpe_min": strategy["sharpe"] >= gates["baseline_cost_sharpe_min"],
        "drawdown_max": strategy["maximum_drawdown"]
        <= gates["baseline_cost_maximum_drawdown_max"],
        "double_cost_positive": double["total_return"]
        > gates["double_cost_total_return_min"],
        "beats_buy_hold_sharpe": strategy["sharpe"] > buy_hold["sharpe"],
        "improves_half_cash": (
            strategy["sharpe"] > half_cash["sharpe"]
            or strategy["maximum_drawdown"] < half_cash["maximum_drawdown"]
        ),
        "completed_positions": strategy["completed_positions"]
        >= gates["minimum_completed_positions"],
    }
    return {
        "passed": bool(all(passed.values())),
        "gates_passed": passed,
        "pass_count": int(sum(passed.values())),
        "gate_count": len(passed),
        "parameter_selection_used_oos": False,
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


def write_outputs(
    store: ResearchDataStore,
    signal_provenance: dict[str, Any],
    results: list[dict[str, Any]],
    decision: dict[str, Any],
    signals: pd.DataFrame,
    frames: dict[str, dict[str, pd.DataFrame]],
) -> None:
    raw_dir = CANDIDATE_DIR / "raw"
    raw_dir.mkdir(exist_ok=True)
    rows = []
    for result in results:
        row = {key: value for key, value in result.items() if key != "yearly_returns"}
        row["yearly_returns_json"] = json.dumps(result["yearly_returns"], sort_keys=True)
        rows.append(row)
        for label, frame in frames[result["scenario"]].items():
            frame.to_csv(
                raw_dir / f"oos__{result['scenario']}__{label}.csv",
                index=False,
                encoding="utf-8",
            )
    pd.DataFrame(rows).to_csv(CANDIDATE_DIR / "oos.csv", index=False, encoding="utf-8-sig")
    signals.to_csv(raw_dir / "oos__signals.csv", index=False, encoding="utf-8")
    comparison = pd.read_csv(CANDIDATE_DIR / "original-vs-causal.csv")
    comparison = pd.concat(
        [comparison, pd.DataFrame(rows).assign(evidence_scope="post-publication replay")],
        ignore_index=True,
        sort=False,
    )
    comparison.to_csv(
        CANDIDATE_DIR / "original-vs-causal.csv", index=False, encoding="utf-8-sig"
    )
    manifest = {
        "schema_version": 1,
        "candidate_id": CANDIDATE_ID,
        "run_id": "untuned-post-publication-oos-v1",
        "created_at": "2026-08-25",
        "period": {"start": str(OOS_START.date()), "end": str(OOS_END.date())},
        "source_sha256": sha256_file(base.SOURCE_PATH),
        "base_engine_sha256": sha256_file(BASE_PATH),
        "oos_engine_sha256": sha256_file(Path(__file__).resolve()),
        "protocol_sha256": sha256_file(base.PROTOCOL_PATH),
        "signal_data_provenance": signal_provenance,
        "etf_data_manifests": {
            name: {
                "path": str(store.manifest_path(name)),
                "sha256": sha256_file(store.manifest_path(name)),
            }
            for name in ("etf_daily", "etf_master")
        },
        "scenarios": [asdict(item) for item in SCENARIOS],
        "parameter_selection_used_oos": False,
        "decision": decision,
        "results": results,
        "limitations": base.load_protocol()["known_limitations"],
    }
    (CANDIDATE_DIR / "oos-run-manifest.json").write_text(
        json.dumps(_json_safe(manifest), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run(data_root: Path | None = None) -> dict[str, Any]:
    calibration = json.loads(
        (CANDIDATE_DIR / "version-calibration-decision.json").read_text(encoding="utf-8")
    )
    if not calibration["unlocked"]:
        raise RuntimeError("public calibration did not unlock the post-publication window")
    source = QlibDailyBarSource()
    signal_bars = source.load(
        [base.SIGNAL_SYMBOL],
        base.WARMUP_START,
        OOS_END,
        ["open", "high", "low", "close", "volume"],
        "pre",
    )
    features = base.build_rsrs_features(signal_bars)
    store = ResearchDataStore(data_root)
    etf_bars = load_etf_bars(store)
    calendar = pd.DatetimeIndex(sorted(etf_bars["trade_date"].unique()))
    targets, signals = build_oos_targets(features, calendar)
    results = []
    frames = {}
    for scenario in SCENARIOS:
        metrics, scenario_frames = run_scenario(etf_bars, targets, scenario)
        results.append(metrics)
        frames[scenario.name] = scenario_frames
    decision = evaluate_oos(results)
    write_outputs(store, source.last_provenance or {}, results, decision, signals, frames)
    return decision


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    decision = run(args.data_root)
    print(json.dumps(_json_safe(decision), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
