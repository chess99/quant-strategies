"""校准按成交量动态选池的 ETF 轮动候选；通过前不计算发布后收益。"""

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
    performance_metrics,
)
from quant_research.data.store import ResearchDataStore  # noqa: E402


CANDIDATE_ID = "dynamic-volume-etf-rotation"
CANDIDATE_DIR = STUDY_DIR / "results" / CANDIDATE_ID
PROTOCOL_PATH = CANDIDATE_DIR / "protocol.json"
SOURCE_PATH = (
    ROOT
    / "joinquant_archive"
    / "sources"
    / "2025年度精选策略"
    / "82.无需先验知识，动态选择的etf轮动策略，更具鲁棒性.py"
)
PUBLIC_START = pd.Timestamp("2006-01-04")
PUBLIC_END = pd.Timestamp("2019-12-13")
INITIAL_CASH = 100_000.0
VOLUME_RANK_DAYS = 30
DYNAMIC_POOL_SIZE = 7
MOMENTUM_DAYS = 13
VOLUME_STATE_DAYS = 7
LOW_VOLUME_STREAK = 6
MINIMUM_MOMENTUM_PERCENT = 0.1
DEFENSIVE_SYMBOL = "SH511880"
RISK_OFF_LEADERS = frozenset({"SH510880", "SH510500"})
PUBLIC_SWITCH_EVENTS = 818
PUBLIC_METRICS = {
    "annualized_return": 0.21708449424602,
    "maximum_drawdown": 0.34508888538093,
    "sharpe": 0.79008123377216,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_protocol() -> dict[str, Any]:
    return json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))


def _consecutive_true(values: pd.Series) -> pd.Series:
    flags = values.fillna(False).to_numpy(dtype=bool)
    output = np.zeros(len(flags), dtype=np.int16)
    streak = 0
    for index, flag in enumerate(flags):
        streak = streak + 1 if flag else 0
        output[index] = streak
    return pd.Series(output, index=values.index)


def build_signal_features(bars: pd.DataFrame) -> pd.DataFrame:
    required = {"trade_date", "symbol", "adjusted_close", "volume"}
    missing = required.difference(bars.columns)
    if missing:
        raise ValueError(f"bars missing signal columns: {sorted(missing)}")
    frame = bars[list(required)].copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.normalize()
    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    frame["adjusted_close"] = pd.to_numeric(frame["adjusted_close"], errors="coerce")
    frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce")
    frame = frame.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    grouped = frame.groupby("symbol", sort=False, group_keys=False)
    frame["volume_mean_30"] = grouped["volume"].transform(
        lambda values: values.rolling(VOLUME_RANK_DAYS, min_periods=VOLUME_RANK_DAYS).mean()
    )
    lagged_close = grouped["adjusted_close"].shift(MOMENTUM_DAYS - 1)
    frame["momentum_percent"] = (frame["adjusted_close"] / lagged_close - 1.0) * 100.0
    frame["close_mean_13"] = grouped["adjusted_close"].transform(
        lambda values: values.rolling(MOMENTUM_DAYS, min_periods=MOMENTUM_DAYS).mean()
    )
    frame["ma_gap_percent"] = (
        frame["adjusted_close"] / frame["close_mean_13"] - 1.0
    ) * 100.0
    frame["volume_mean_7"] = grouped["volume"].transform(
        lambda values: values.rolling(VOLUME_STATE_DAYS, min_periods=VOLUME_STATE_DAYS).mean()
    )
    frame["volume_below_mean"] = frame["volume"].lt(frame["volume_mean_7"])
    frame["low_volume_streak"] = grouped["volume_below_mean"].transform(_consecutive_true)
    return frame.sort_values(["trade_date", "symbol"]).reset_index(drop=True)


def select_target(
    features: pd.DataFrame,
    observation_date,
    *,
    pool_size: int = DYNAMIC_POOL_SIZE,
) -> tuple[str, dict[str, Any]]:
    observation = pd.Timestamp(observation_date).normalize()
    rows = features[features["trade_date"].eq(observation)].copy()
    rows = rows[rows["volume_mean_30"].notna()]
    rows = rows.sort_values(
        ["volume_mean_30", "symbol"], ascending=[False, True]
    ).head(pool_size)
    diagnostics: dict[str, Any] = {
        "observation_date": observation.strftime("%Y-%m-%d"),
        "dynamic_pool": rows["symbol"].tolist(),
        "available_count": int(len(rows)),
    }
    if rows.empty:
        diagnostics.update({"leader": None, "reason": "no_complete_volume_history"})
        return DEFENSIVE_SYMBOL, diagnostics
    ranked = rows.assign(
        _momentum=rows["momentum_percent"].fillna(-100.0),
        _ma_gap=rows["ma_gap_percent"].fillna(-100.0),
    ).sort_values(["_momentum", "symbol"], ascending=[False, True])
    leader = ranked.iloc[0]
    target_market = ranked.iloc[-1]
    low_streak = int(target_market["low_volume_streak"])
    diagnostics.update(
        {
            "leader": str(leader["symbol"]),
            "leader_momentum_percent": float(leader["_momentum"]),
            "leader_ma_gap_percent": float(leader["_ma_gap"]),
            "target_market": str(target_market["symbol"]),
            "low_volume_streak": low_streak,
        }
    )
    # 原函数最多向前查 30 行；若连续 30 日都没有反向状态，会隐式返回 KEEP 而非风险关闭。
    if LOW_VOLUME_STREAK <= low_streak < 30:
        diagnostics["reason"] = "persistent_low_volume"
        return DEFENSIVE_SYMBOL, diagnostics
    if (
        float(leader["_momentum"]) < MINIMUM_MOMENTUM_PERCENT
        or float(leader["_ma_gap"]) < 0.0
    ):
        diagnostics["reason"] = "no_positive_leader"
        return DEFENSIVE_SYMBOL, diagnostics
    if str(leader["symbol"]) in RISK_OFF_LEADERS:
        diagnostics["reason"] = "risk_off_leader"
        return DEFENSIVE_SYMBOL, diagnostics
    diagnostics["reason"] = "risk_on_leader"
    return str(leader["symbol"]), diagnostics


def load_eligible_bars(
    store: ResearchDataStore,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    master = store.read_parquet("etf_master")
    listing = pd.to_datetime(master["listing_date"], errors="coerce")
    delisting = pd.to_datetime(master["delisting_date"], errors="coerce")
    eligible = master[
        master["bar_status"].eq("success")
        & master["quality_grade"].isin(["A", "B"])
        & listing.le(end)
        & (delisting.isna() | delisting.ge(start))
    ].copy()
    symbols = sorted(eligible["symbol"].astype(str).str.upper().unique())
    columns = [
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
    ]
    bars = store.read_symbol_partitions(
        "etf_daily",
        symbols,
        columns=columns,
        filters=[("trade_date", ">=", start), ("trade_date", "<=", end)],
        strict=True,
    )
    bars["trade_date"] = pd.to_datetime(bars["trade_date"]).dt.normalize()
    bars = bars[bars["trade_date"].between(start, end)].copy()
    return bars.sort_values(["trade_date", "symbol"]).reset_index(drop=True), eligible


def build_market_state(raw_bars: pd.DataFrame) -> pd.DataFrame:
    state = raw_bars[["symbol", "trade_date", "open", "high", "low", "close", "volume"]].copy()
    state = state.sort_values(["symbol", "trade_date"])
    state["previous_close"] = state.groupby("symbol")["close"].shift(1)
    state["paused"] = state["volume"].fillna(0).le(0)
    state["is_st"] = False
    open_ratio = state["open"] / state["previous_close"]
    low_ratio = state["low"] / state["previous_close"]
    high_ratio = state["high"] / state["previous_close"]
    state["buy_blocked"] = open_ratio.ge(1.095) & low_ratio.ge(1.095)
    state["sell_blocked"] = open_ratio.le(0.905) & high_ratio.le(0.905)
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


def build_targets(
    features: pd.DataFrame,
    calendar: pd.DatetimeIndex,
) -> tuple[dict[pd.Timestamp, str], pd.DataFrame]:
    targets: dict[pd.Timestamp, str] = {}
    rows = []
    previous_date = None
    previous_target = None
    for trade_date in calendar:
        if previous_date is None:
            previous_date = trade_date
            continue
        target, diagnostics = select_target(features, previous_date)
        targets[pd.Timestamp(trade_date)] = target
        rows.append(
            {
                "trade_date": pd.Timestamp(trade_date),
                "target": target,
                "target_changed": target != previous_target,
                "dynamic_pool": "|".join(diagnostics["dynamic_pool"]),
                **{
                    key: value
                    for key, value in diagnostics.items()
                    if key not in {"dynamic_pool"}
                },
            }
        )
        previous_target = target
        previous_date = trade_date
    return targets, pd.DataFrame(rows)


def count_signal_switches(targets: list[str]) -> int:
    return sum(
        current != previous
        for previous, current in zip(targets, targets[1:])
    )


def run_backtest(
    bars: pd.DataFrame,
    targets: dict[pd.Timestamp, str],
    *,
    commission: float = 0.0003,
    minimum_commission: float = 5.0,
    slippage: float = 0.0,
    maximum_volume_ratio: float = 1.0,
) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    calendar = pd.DatetimeIndex(sorted(bars["trade_date"].unique()))
    target_symbols = sorted(set(targets.values()))
    engine_bars = bars[bars["symbol"].isin(target_symbols)].copy()
    market_state = build_market_state(engine_bars)
    engine_prices = engine_bars[
        ["symbol", "trade_date", "adjusted_open", "adjusted_close", "volume"]
    ].rename(columns={"adjusted_open": "open", "adjusted_close": "close"})
    engine = DailyBacktester(
        engine_prices,
        market_state,
        asset_types={symbol: "etf" for symbol in target_symbols},
        config=BacktestConfig(
            initial_cash=INITIAL_CASH,
            lot_size=100,
            maximum_volume_ratio=maximum_volume_ratio,
            slippage_rate=slippage,
            t_plus_one_asset_types=("stock",),
            minimum_state_quality="B",
        ),
        costs=CostModel(
            buy_commission=commission,
            sell_commission=commission,
            minimum_commission=minimum_commission,
            etf_buy_commission=commission,
            etf_sell_commission=commission,
            etf_minimum_commission=minimum_commission,
        ),
    )
    rebalance_attempts = 0
    for trade_date in calendar:
        target = targets.get(pd.Timestamp(trade_date))
        held = set(engine.positions)
        desired = {target} if target else set()
        if held != desired:
            engine.rebalance_to_weights(
                trade_date,
                {target: 1.0} if target else {},
                execution="open",
            )
            rebalance_attempts += 1
        engine.mark_close(trade_date)
    target_values = [targets[date] for date in calendar if date in targets]
    signal_switches = count_signal_switches(target_values)
    metrics = performance_metrics(engine.equity, engine.trades, trading_days=250)
    metrics.update(
        {
            "switch_event_count": signal_switches,
            "rebalance_attempt_count": rebalance_attempts,
            "trade_count": len(engine.trades),
            "order_count": len(engine.orders),
            "rejected_order_count": len(engine.rejections),
            "commission": commission,
            "minimum_commission": minimum_commission,
            "slippage": slippage,
            "maximum_volume_ratio": maximum_volume_ratio,
        }
    )
    return metrics, {
        "equity": engine.equity,
        "orders": engine.orders,
        "trades": engine.trades,
        "holdings": engine.holdings,
    }


def evaluate_calibration(
    local: dict[str, Any],
    public: dict[str, float] = PUBLIC_METRICS,
    *,
    public_switch_events: int = PUBLIC_SWITCH_EVENTS,
) -> dict[str, Any]:
    gates = load_protocol()["public_calibration"]["gates"]
    gaps = {
        "annualized_return": abs(local["annualized_return"] - public["annualized_return"]),
        "maximum_drawdown": abs(local["maximum_drawdown"] - public["maximum_drawdown"]),
        "sharpe": abs(local["sharpe"] - public["sharpe"]),
        "switch_event_relative": abs(local["switch_event_count"] - public_switch_events)
        / public_switch_events,
    }
    passed = {
        "annualized_return": gaps["annualized_return"]
        <= gates["annualized_return_absolute_gap_max"],
        "maximum_drawdown": gaps["maximum_drawdown"]
        <= gates["maximum_drawdown_absolute_gap_max"],
        "sharpe": gaps["sharpe"] <= gates["sharpe_absolute_gap_max"],
        "switch_event_count": gaps["switch_event_relative"]
        <= gates["switch_event_relative_gap_max"],
    }
    pass_count = sum(passed.values())
    unlocked = (
        pass_count >= gates["minimum_pass_count"]
        and passed["annualized_return"]
        and passed["sharpe"]
    )
    return {
        "unlocked": bool(unlocked),
        "pass_count": int(pass_count),
        "gates_passed": passed,
        "gaps": gaps,
        "local": {key: local[key] for key in (*PUBLIC_METRICS, "switch_event_count")},
        "public": {**public, "switch_event_count": public_switch_events},
        "post_publication_performance_calculated": False,
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


def write_calibration_outputs(
    store: ResearchDataStore,
    eligible: pd.DataFrame,
    metrics: dict[str, Any],
    decision: dict[str, Any],
    targets: pd.DataFrame,
    frames: dict[str, pd.DataFrame],
) -> None:
    CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)
    raw_dir = CANDIDATE_DIR / "raw"
    raw_dir.mkdir(exist_ok=True)
    row = {key: value for key, value in metrics.items() if key != "yearly_returns"}
    row["scenario"] = "causal-daily-source-cost-calibration"
    row["period_start"] = PUBLIC_START.strftime("%Y-%m-%d")
    row["period_end"] = PUBLIC_END.strftime("%Y-%m-%d")
    row["yearly_returns_json"] = json.dumps(metrics["yearly_returns"], sort_keys=True)
    pd.DataFrame([row]).to_csv(
        CANDIDATE_DIR / "version-calibration.csv", index=False, encoding="utf-8-sig"
    )
    comparison = pd.DataFrame(
        [
            {"scenario": "published-public-backtest", **PUBLIC_METRICS, "switch_event_count": PUBLIC_SWITCH_EVENTS},
            row,
        ]
    )
    comparison.to_csv(
        CANDIDATE_DIR / "original-vs-causal.csv", index=False, encoding="utf-8-sig"
    )
    for label, frame in {**frames, "targets": targets}.items():
        frame.to_csv(
            raw_dir / f"version-calibration__{label}.csv", index=False, encoding="utf-8"
        )
    (CANDIDATE_DIR / "version-calibration-decision.json").write_text(
        json.dumps(_json_safe(decision), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "candidate_id": CANDIDATE_ID,
        "run_id": "public-window-causal-daily-calibration-v1",
        "created_at": "2026-08-25",
        "period": {"start": str(PUBLIC_START.date()), "end": str(PUBLIC_END.date())},
        "source_path": SOURCE_PATH.relative_to(ROOT).as_posix(),
        "source_sha256": sha256_file(SOURCE_PATH),
        "engine_path": Path(__file__).resolve().relative_to(ROOT).as_posix(),
        "engine_sha256": sha256_file(Path(__file__).resolve()),
        "protocol_sha256": sha256_file(PROTOCOL_PATH),
        "data_manifests": {
            name: {
                "path": str(store.manifest_path(name)),
                "sha256": sha256_file(store.manifest_path(name)),
            }
            for name in ("etf_daily", "etf_master")
        },
        "eligible_etf_count": int(len(eligible)),
        "post_publication_performance_calculated": False,
        "decision": decision,
        "limitations": load_protocol()["known_limitations"],
    }
    (CANDIDATE_DIR / "version-calibration-manifest.json").write_text(
        json.dumps(_json_safe(manifest), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run_calibration(data_root: Path | None = None) -> dict[str, Any]:
    store = ResearchDataStore(data_root)
    bars, eligible = load_eligible_bars(store, PUBLIC_START, PUBLIC_END)
    features = build_signal_features(bars)
    calendar = pd.DatetimeIndex(sorted(bars["trade_date"].unique()))
    targets, target_frame = build_targets(features, calendar)
    metrics, frames = run_backtest(bars, targets)
    decision = evaluate_calibration(metrics)
    write_calibration_outputs(store, eligible, metrics, decision, target_frame, frames)
    return decision


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    decision = run_calibration(args.data_root)
    print(json.dumps(_json_safe(decision), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
