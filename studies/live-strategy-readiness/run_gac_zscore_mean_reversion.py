"""校准并首次回放广汽集团 Z-score 均值回归候选。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
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
    performance_metrics,
)
from quant_research.portal import QlibDailyBarSource  # noqa: E402


CANDIDATE_ID = "gac-zscore-mean-reversion"
CANDIDATE_DIR = STUDY_DIR / "results" / CANDIDATE_ID
PROTOCOL_PATH = CANDIDATE_DIR / "protocol.json"
SOURCE_PATH = (
    ROOT
    / "joinquant_archive"
    / "sources"
    / "2020年度精选策略"
    / "12 【均值回归】基于zscore的均值回归策略（胜率100%）.py"
)
SYMBOL = "SH601238"
MA_WINDOW = 20
ZSCORE_WINDOW = 60
BUY_THRESHOLD = -2.0
SELL_THRESHOLD = 1.0
WARMUP_START = pd.Timestamp("2012-01-01")
PUBLIC_START = pd.Timestamp("2013-01-04")
PUBLIC_END = pd.Timestamp("2018-07-06")
OOS_START = pd.Timestamp("2018-07-09")
OOS_END = pd.Timestamp("2026-07-23")
PUBLIC_COMPLETED_POSITIONS = 15
PUBLIC_METRICS = {
    "annualized_return": 0.39130293506464,
    "maximum_drawdown": 0.17046506558779,
    "sharpe": 1.7563278299485,
}


@dataclass(frozen=True)
class Scenario:
    name: str
    method: str
    initial_cash: float
    commission: float
    slippage: float
    maximum_volume_ratio: float


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_protocol() -> dict[str, Any]:
    return json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))


def zscore_series(close: pd.Series) -> pd.Series:
    values = pd.to_numeric(close, errors="coerce")
    residual = values - values.rolling(MA_WINDOW, min_periods=MA_WINDOW).mean()
    mean = residual.rolling(ZSCORE_WINDOW, min_periods=ZSCORE_WINDOW).mean()
    std = residual.rolling(ZSCORE_WINDOW, min_periods=ZSCORE_WINDOW).std(ddof=1)
    return (residual - mean) / std


def hysteresis_positions(scores: pd.Series) -> pd.Series:
    state = 0
    output = []
    for score in pd.to_numeric(scores, errors="coerce"):
        if np.isfinite(score):
            if score <= BUY_THRESHOLD and state == 0:
                state = 1
            elif score >= SELL_THRESHOLD and state == 1:
                state = 0
        output.append(state)
    return pd.Series(output, index=scores.index, dtype=int)


def build_targets(
    bars: pd.DataFrame,
    calendar: pd.DatetimeIndex,
) -> tuple[dict[pd.Timestamp, int], pd.DataFrame]:
    series = bars.sort_values("trade_date").set_index("trade_date")["close"]
    scores = zscore_series(series)
    prior = scores.index[scores.index < calendar[0]]
    previous_date = prior[-1] if len(prior) else None
    state = 0
    targets = {}
    rows = []
    for trade_date in calendar:
        score = np.nan if previous_date is None else scores.get(previous_date, np.nan)
        previous_state = state
        if np.isfinite(score):
            if score <= BUY_THRESHOLD and state == 0:
                state = 1
            elif score >= SELL_THRESHOLD and state == 1:
                state = 0
        targets[pd.Timestamp(trade_date)] = state
        rows.append(
            {
                "trade_date": pd.Timestamp(trade_date),
                "observation_date": previous_date,
                "zscore": score,
                "target_position": state,
                "signal_transition": state - previous_state,
            }
        )
        previous_date = pd.Timestamp(trade_date)
    return targets, pd.DataFrame(rows)


def load_bars(end: pd.Timestamp) -> tuple[pd.DataFrame, dict[str, Any]]:
    source = QlibDailyBarSource()
    pre = source.load(
        [SYMBOL], WARMUP_START, end, ["open", "high", "low", "close", "volume"], "pre"
    )
    provenance = source.last_provenance or {}
    raw = source.load(
        [SYMBOL], WARMUP_START, end, ["open", "high", "low", "close", "volume"], "raw"
    )
    pre["trade_date"] = pd.to_datetime(pre["trade_date"]).dt.normalize()
    raw["trade_date"] = pd.to_datetime(raw["trade_date"]).dt.normalize()
    raw = raw.rename(
        columns={column: f"raw_{column}" for column in ("open", "high", "low", "close", "volume")}
    )
    return pre.merge(raw, on=["symbol", "trade_date"], validate="one_to_one"), provenance


def build_market_state(bars: pd.DataFrame) -> pd.DataFrame:
    state = bars[["symbol", "trade_date", "raw_open", "raw_high", "raw_low", "raw_close", "raw_volume"]].copy()
    state["previous_close"] = state["raw_close"].shift(1)
    state["paused"] = state["raw_volume"].fillna(0).le(0)
    state["is_st"] = False
    state["buy_blocked"] = (
        state["raw_open"].div(state["previous_close"]).ge(1.095)
        & state["raw_low"].div(state["previous_close"]).ge(1.095)
    )
    state["sell_blocked"] = (
        state["raw_open"].div(state["previous_close"]).le(0.905)
        & state["raw_high"].div(state["previous_close"]).le(0.905)
    )
    state["status_quality"] = "B"
    state["st_quality"] = "B"
    state["limit_quality"] = "B"
    return state.rename(columns={"raw_volume": "volume"})[
        [
            "symbol", "trade_date", "paused", "is_st", "buy_blocked", "sell_blocked",
            "status_quality", "st_quality", "limit_quality",
        ]
    ]


def run_scenario(
    bars: pd.DataFrame,
    targets: dict[pd.Timestamp, int],
    scenario: Scenario,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    period = bars[bars["trade_date"].between(start, end)].copy()
    engine = DailyBacktester(
        period[["symbol", "trade_date", "open", "close", "volume"]],
        build_market_state(period),
        asset_types={SYMBOL: "stock"},
        config=BacktestConfig(
            initial_cash=scenario.initial_cash,
            lot_size=100,
            maximum_volume_ratio=scenario.maximum_volume_ratio,
            slippage_rate=scenario.slippage,
            minimum_state_quality="B",
        ),
        costs=CostModel(
            buy_commission=scenario.commission,
            sell_commission=scenario.commission,
            minimum_commission=5.0,
        ),
    )
    calendar = pd.DatetimeIndex(sorted(period["trade_date"].unique()))
    previous_weight = 0.0
    for date in calendar:
        if scenario.method == "signal":
            weight = float(targets[pd.Timestamp(date)])
        elif scenario.method == "buy-hold":
            weight = 1.0
        elif scenario.method == "half-cash":
            weight = 0.5
        else:
            raise ValueError(scenario.method)
        if weight != previous_weight:
            engine.rebalance_to_weights(date, {SYMBOL: weight} if weight else {}, execution="open")
        engine.mark_close(date)
        previous_weight = weight
    metrics = performance_metrics(engine.equity, engine.trades, trading_days=250)
    metrics.update(
        {
            "scenario": scenario.name,
            "method": scenario.method,
            "period_start": str(start.date()),
            "period_end": str(end.date()),
            "completed_positions": 0 if engine.trades.empty else int(engine.trades["side"].eq("sell").sum()),
            "trade_count": len(engine.trades),
            "order_count": len(engine.orders),
            "rejected_order_count": len(engine.rejections),
            "parameter_selection_used_window": False,
        }
    )
    return metrics, {"equity": engine.equity, "orders": engine.orders, "trades": engine.trades, "holdings": engine.holdings}


def evaluate_calibration(local: dict[str, Any]) -> dict[str, Any]:
    gates = load_protocol()["public_calibration"]["gates"]
    gaps = {
        "annualized_return": abs(local["annualized_return"] - PUBLIC_METRICS["annualized_return"]),
        "maximum_drawdown": abs(local["maximum_drawdown"] - PUBLIC_METRICS["maximum_drawdown"]),
        "sharpe": abs(local["sharpe"] - PUBLIC_METRICS["sharpe"]),
        "completed_position_relative": abs(local["completed_positions"] - PUBLIC_COMPLETED_POSITIONS) / PUBLIC_COMPLETED_POSITIONS,
    }
    passed = {
        "annualized_return": gaps["annualized_return"] <= gates["annualized_return_absolute_gap_max"],
        "maximum_drawdown": gaps["maximum_drawdown"] <= gates["maximum_drawdown_absolute_gap_max"],
        "sharpe": gaps["sharpe"] <= gates["sharpe_absolute_gap_max"],
        "completed_positions": gaps["completed_position_relative"] <= gates["completed_position_relative_gap_max"],
    }
    count = sum(passed.values())
    unlocked = count >= gates["minimum_pass_count"] and passed["annualized_return"] and passed["sharpe"]
    return {"unlocked": bool(unlocked), "pass_count": int(count), "gates_passed": passed, "gaps": gaps, "post_publication_performance_calculated": False}


def evaluate_oos(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_name = {row["scenario"]: row for row in results}
    strategy = by_name["zscore-baseline-cost"]
    double = by_name["zscore-double-cost"]
    buy_hold = by_name["gac-buy-hold"]
    half = by_name["static-50pct-gac-cash"]
    gates = load_protocol()["promotion_gates_after_oos"]
    passed = {
        "sharpe_min": strategy["sharpe"] >= gates["baseline_cost_sharpe_min"],
        "drawdown_max": strategy["maximum_drawdown"] <= gates["baseline_cost_maximum_drawdown_max"],
        "double_cost_positive": double["total_return"] > gates["double_cost_total_return_min"],
        "beats_buy_hold_sharpe": strategy["sharpe"] > buy_hold["sharpe"],
        "improves_half_cash": strategy["sharpe"] > half["sharpe"] or strategy["maximum_drawdown"] < half["maximum_drawdown"],
        "completed_positions": strategy["completed_positions"] >= gates["minimum_completed_positions"],
    }
    return {"passed": bool(all(passed.values())), "pass_count": int(sum(passed.values())), "gate_count": len(passed), "gates_passed": passed, "parameter_selection_used_oos": False}


def _safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    return value


def write_phase(
    phase: str,
    provenance: dict[str, Any],
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
            frame.to_csv(raw_dir / f"{phase}__{result['scenario']}__{label}.csv", index=False, encoding="utf-8")
    signals.to_csv(raw_dir / f"{phase}__signals.csv", index=False, encoding="utf-8")
    if phase == "version-calibration":
        pd.DataFrame(rows).to_csv(CANDIDATE_DIR / "version-calibration.csv", index=False, encoding="utf-8-sig")
        comparison = pd.DataFrame([{"scenario": "published-public-backtest", **PUBLIC_METRICS, "completed_positions": PUBLIC_COMPLETED_POSITIONS}, *rows])
        comparison.to_csv(CANDIDATE_DIR / "original-vs-causal.csv", index=False, encoding="utf-8-sig")
        decision_name = "version-calibration-decision.json"
        manifest_name = "version-calibration-manifest.json"
    else:
        pd.DataFrame(rows).to_csv(CANDIDATE_DIR / "oos.csv", index=False, encoding="utf-8-sig")
        comparison = pd.read_csv(CANDIDATE_DIR / "original-vs-causal.csv")
        pd.concat([comparison, pd.DataFrame(rows)], ignore_index=True, sort=False).to_csv(CANDIDATE_DIR / "original-vs-causal.csv", index=False, encoding="utf-8-sig")
        decision_name = "oos-decision.json"
        manifest_name = "oos-run-manifest.json"
    (CANDIDATE_DIR / decision_name).write_text(json.dumps(_safe(decision), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "candidate_id": CANDIDATE_ID,
        "phase": phase,
        "created_at": "2026-08-25",
        "source_sha256": sha256_file(SOURCE_PATH),
        "engine_sha256": sha256_file(Path(__file__).resolve()),
        "protocol_sha256": sha256_file(PROTOCOL_PATH),
        "data_provenance": provenance,
        "parameter_selection_used_window": False,
        "decision": decision,
        "results": results,
    }
    (CANDIDATE_DIR / manifest_name).write_text(json.dumps(_safe(manifest), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(phase: str) -> dict[str, Any]:
    end = PUBLIC_END if phase == "calibration" else OOS_END
    bars, provenance = load_bars(end)
    start = PUBLIC_START if phase == "calibration" else OOS_START
    calendar = pd.DatetimeIndex(sorted(bars.loc[bars["trade_date"].between(start, end), "trade_date"].unique()))
    targets, signals = build_targets(bars, calendar)
    if phase == "calibration":
        scenarios = (Scenario("source-cost-calibration", "signal", 100_000.0, 0.0003, 0.0, 1.0),)
    else:
        calibration = json.loads((CANDIDATE_DIR / "version-calibration-decision.json").read_text(encoding="utf-8"))
        if not calibration["unlocked"]:
            raise RuntimeError("calibration did not unlock OOS")
        scenarios = (
            Scenario("zscore-baseline-cost", "signal", 1_000_000.0, 0.0003, 0.001, 0.01),
            Scenario("zscore-double-cost", "signal", 1_000_000.0, 0.0006, 0.002, 0.01),
            Scenario("gac-buy-hold", "buy-hold", 1_000_000.0, 0.0003, 0.001, 0.01),
            Scenario("static-50pct-gac-cash", "half-cash", 1_000_000.0, 0.0003, 0.001, 0.01),
        )
    results = []
    frames = {}
    for scenario in scenarios:
        metrics, scenario_frames = run_scenario(bars, targets, scenario, start, end)
        results.append(metrics)
        frames[scenario.name] = scenario_frames
    decision = evaluate_calibration(results[0]) if phase == "calibration" else evaluate_oos(results)
    write_phase("version-calibration" if phase == "calibration" else "oos", provenance, results, decision, signals, frames)
    return decision


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("calibration", "oos"), required=True)
    args = parser.parse_args()
    print(json.dumps(_safe(run(args.phase)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
