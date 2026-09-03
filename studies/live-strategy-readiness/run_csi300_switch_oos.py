"""运行沪深 300 回撤择时 / 国债切换的首次未经调参发布后回放。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
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

from quant_research.backtest import (  # noqa: E402
    BacktestConfig,
    CostModel,
    DailyBacktester,
    performance_metrics,
    scheduled_dates,
)
from quant_research.data.store import ResearchDataStore  # noqa: E402


CANDIDATE_ID = "csi300-drawdown-bond-switch"
CANDIDATE_DIR = STUDY_DIR / "results" / CANDIDATE_ID
SOURCE_PATH = (
    ROOT
    / "joinquant_archive"
    / "sources"
    / "2023年度精选策略"
    / "17.20行代码8年胜率100%躲过了牛年第一场大跌.py"
)
OOS_START = pd.Timestamp("2021-03-08")
OOS_END = pd.Timestamp("2026-07-24")
INITIAL_CASH = 200_000.0
LOOKBACK_DAYS = 32
SIGNAL_SYMBOL = "SH000001"
RISK_SYMBOL = "SH510300"
DEFENSIVE_SYMBOL = "SH511010"
ETF_SYMBOLS = (RISK_SYMBOL, DEFENSIVE_SYMBOL)


@dataclass(frozen=True)
class Scenario:
    name: str
    method: str
    commission_rate: float
    minimum_commission: float
    slippage_rate: float
    maximum_volume_ratio: float
    execution_policy: str
    cost_label: str


SCENARIOS = (
    Scenario(
        name="frozen-source-cost-proxy",
        method="switch",
        commission_rate=0.0003,
        minimum_commission=5.0,
        slippage_rate=0.0,
        maximum_volume_ratio=1.0,
        execution_policy="source-sequential",
        cost_label="platform-default proxy; source did not declare costs",
    ),
    Scenario(
        name="causal-baseline-cost",
        method="switch",
        commission_rate=0.0003,
        minimum_commission=5.0,
        slippage_rate=0.0005,
        maximum_volume_ratio=0.01,
        execution_policy="sell-first",
        cost_label="realistic baseline",
    ),
    Scenario(
        name="causal-double-cost",
        method="switch",
        commission_rate=0.0006,
        minimum_commission=5.0,
        slippage_rate=0.0010,
        maximum_volume_ratio=0.01,
        execution_policy="sell-first",
        cost_label="double friction",
    ),
    Scenario(
        name="csi300-buy-hold",
        method="risk-buy-hold",
        commission_rate=0.0003,
        minimum_commission=5.0,
        slippage_rate=0.0005,
        maximum_volume_ratio=0.01,
        execution_policy="sell-first",
        cost_label="realistic baseline",
    ),
    Scenario(
        name="static-50-50",
        method="static-half",
        commission_rate=0.0003,
        minimum_commission=5.0,
        slippage_rate=0.0005,
        maximum_volume_ratio=0.01,
        execution_policy="sell-first",
        cost_label="realistic baseline",
    ),
)


PUBLIC_BACKTEST = {
    "scenario": "published-public-backtest",
    "evidence_scope": "public in-sample aggregate",
    "period_start": "2013-01-01",
    "period_end": "2021-03-04",
    "initial_cash": 10_000.0,
    "total_return": 4.819173575,
    "annualized_return": 0.24847167458486,
    "maximum_drawdown": 0.13153570811623,
    "sharpe": 1.4699515406993,
    "sortino": 1.8487509982585,
    "turnover": 0.0057351231448319,
    "comparable_to_oos": False,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def switch_signal(close: pd.Series, observation_date) -> int:
    """按冻结源码的 32 日规则返回 0=防御、1=进攻、-1=保持。"""

    observation = pd.Timestamp(observation_date).normalize()
    values = (
        pd.to_numeric(close.loc[close.index <= observation], errors="coerce")
        .dropna()
        .tail(LOOKBACK_DAYS)
        .to_numpy(dtype=float)
    )
    if len(values) != LOOKBACK_DAYS or not np.isfinite(values).all():
        return -1
    if (
        int(values.argmax()) > 22
        and int(values.argmin()) == 0
        and values[-1] < values[-30:].mean()
        and values[-2] < values[:-1].mean()
    ):
        return 0
    if (
        values[2] == values[2:].max()
        and values[-20:].mean() > values[-30:].mean()
        and values[-10:].mean() > values[-20:].mean()
    ):
        return 1
    return -1


def _atomic_csv(frame: pd.DataFrame, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    os.close(handle)
    Path(temporary_name).unlink(missing_ok=True)
    try:
        frame.to_csv(temporary_name, index=False, encoding="utf-8")
        Path(temporary_name).replace(target)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def load_signal_index(
    store: ResearchDataStore,
    *,
    refresh: bool = False,
) -> tuple[pd.Series, dict[str, Any]]:
    target = store.raw_dir / "sina" / "index_daily" / f"{SIGNAL_SYMBOL}.csv"
    if refresh or not target.is_file():
        import akshare as ak

        downloaded = ak.stock_zh_index_daily(symbol="sh000001")
        frame = downloaded.rename(columns={"date": "trade_date"}).copy()
        required = {"trade_date", "open", "high", "low", "close", "volume"}
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(f"Sina index response is missing columns: {sorted(missing)}")
        frame = frame[["trade_date", "open", "high", "low", "close", "volume"]]
        frame.insert(0, "symbol", SIGNAL_SYMBOL)
        frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.normalize()
        frame = frame.sort_values("trade_date").drop_duplicates("trade_date")
        _atomic_csv(frame, target)
    frame = pd.read_csv(target, parse_dates=["trade_date"])
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.normalize()
    frame = frame.sort_values("trade_date").drop_duplicates("trade_date")
    if frame["trade_date"].max() < OOS_END:
        raise ValueError(
            f"signal index data ends at {frame['trade_date'].max():%Y-%m-%d}, "
            f"expected at least {OOS_END:%Y-%m-%d}; rerun with --refresh-index"
        )
    close = frame.set_index("trade_date")["close"].astype(float)
    evidence = {
        "provider": "Sina via akshare.stock_zh_index_daily",
        "request_symbol": "sh000001",
        "path": str(target),
        "sha256": sha256_file(target),
        "first_date": frame["trade_date"].min().strftime("%Y-%m-%d"),
        "last_date": frame["trade_date"].max().strftime("%Y-%m-%d"),
        "row_count": len(frame),
    }
    return close, evidence


def load_etf_bars(store: ResearchDataStore) -> pd.DataFrame:
    bars = store.read_symbol_partitions(
        "etf_daily",
        ETF_SYMBOLS,
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
    return bars.sort_values(["trade_date", "symbol"]).reset_index(drop=True)


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


def _shares(engine: DailyBacktester, symbol: str) -> int:
    position = engine.positions.get(symbol)
    return 0 if position is None else int(position.shares)


def _switch_target(
    engine: DailyBacktester,
    trade_date,
    signal: int,
    *,
    execution_policy: str,
) -> str:
    risk_shares = _shares(engine, RISK_SYMBOL)
    if signal == 0 and risk_shares > 0:
        if execution_policy == "source-sequential":
            engine.order_target_value(trade_date, RISK_SYMBOL, 0.0, execution="open")
            engine.order_target_value(
                trade_date, DEFENSIVE_SYMBOL, engine.cash, execution="open"
            )
        else:
            engine.rebalance_to_weights(
                trade_date, {DEFENSIVE_SYMBOL: 1.0}, execution="open"
            )
        return "risk-off"
    if signal == 1 and risk_shares == 0:
        if execution_policy == "source-sequential":
            engine.order_target_value(trade_date, DEFENSIVE_SYMBOL, 0.0, execution="open")
            engine.order_target_value(trade_date, RISK_SYMBOL, engine.cash, execution="open")
        else:
            engine.rebalance_to_weights(
                trade_date, {RISK_SYMBOL: 1.0}, execution="open"
            )
        return "risk-on"
    return "hold"


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
    signal_close: pd.Series,
    scenario: Scenario,
) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    oos_bars = bars[bars["trade_date"].between(OOS_START, OOS_END)].copy()
    engine_bars = oos_bars[
        ["symbol", "trade_date", "adjusted_open", "adjusted_close", "volume"]
    ].rename(columns={"adjusted_open": "open", "adjusted_close": "close"})
    oos_state = market_state[market_state["trade_date"].between(OOS_START, OOS_END)].copy()
    calendar = pd.DatetimeIndex(sorted(oos_bars["trade_date"].unique()))
    monthly = scheduled_dates(calendar, frequency="monthly", when="first")
    engine = DailyBacktester(
        engine_bars,
        oos_state,
        asset_types={symbol: "etf" for symbol in ETF_SYMBOLS},
        config=BacktestConfig(
            initial_cash=INITIAL_CASH,
            lot_size=100,
            maximum_volume_ratio=scenario.maximum_volume_ratio,
            slippage_rate=scenario.slippage_rate,
            t_plus_one_asset_types=("stock",),
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
    signal_rows: list[dict[str, Any]] = []
    previous_date = None
    for trade_date in calendar:
        signal = -1
        action = "hold"
        if scenario.method == "switch" and previous_date is not None:
            signal = switch_signal(signal_close, previous_date)
            action = _switch_target(
                engine,
                trade_date,
                signal,
                execution_policy=scenario.execution_policy,
            )
        elif scenario.method == "risk-buy-hold" and trade_date == calendar[0]:
            engine.rebalance_to_weights(
                trade_date, {RISK_SYMBOL: 1.0}, execution="open"
            )
            action = "initial-risk"
        elif scenario.method == "static-half" and trade_date in monthly:
            engine.rebalance_to_weights(
                trade_date,
                {RISK_SYMBOL: 0.5, DEFENSIVE_SYMBOL: 0.5},
                execution="open",
            )
            action = "static-rebalance"
        signal_rows.append(
            {
                "trade_date": pd.Timestamp(trade_date),
                "observation_date": (
                    pd.NaT if previous_date is None else pd.Timestamp(previous_date)
                ),
                "signal": signal,
                "action": action,
                "risk_shares_after_orders": _shares(engine, RISK_SYMBOL),
                "defensive_shares_after_orders": _shares(engine, DEFENSIVE_SYMBOL),
            }
        )
        engine.mark_close(trade_date)
        previous_date = trade_date
    equity = engine.equity
    metrics = performance_metrics(equity, engine.trades, trading_days=250)
    returns = pd.to_numeric(equity["daily_return"], errors="coerce").fillna(0.0)
    downside = returns[returns < 0.0]
    sortino = (
        returns.mean() * 250.0 / (downside.std(ddof=1) * math.sqrt(250.0))
        if len(downside) > 1 and downside.std(ddof=1) > 0
        else float("nan")
    )
    signals = pd.DataFrame(signal_rows)
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
            "execution_policy": scenario.execution_policy,
            "risk_off_transition_count": int(signals["action"].eq("risk-off").sum()),
            "risk_on_transition_count": int(signals["action"].eq("risk-on").sum()),
            "parameter_selection_used_oos": False,
        }
    )
    frames = {
        "equity": equity,
        "trades": engine.trades,
        "orders": engine.orders,
        "holdings": engine.holdings,
        "signals": signals,
    }
    return metrics, frames


def write_outputs(
    store: ResearchDataStore,
    index_evidence: dict[str, Any],
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
    comparison = pd.concat(
        [
            pd.DataFrame([PUBLIC_BACKTEST]),
            oos.assign(
                evidence_scope="post-publication replay",
                comparable_to_oos=True,
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
        "data_manifests": data_manifests,
        "signal_index": index_evidence,
        "frozen_parameters": {
            "signal_symbol": "000001.XSHG",
            "risk_asset": "510300.XSHG",
            "defensive_asset": "511010.XSHG",
            "signal_lookback_days": LOOKBACK_DAYS,
        },
        "parameter_selection_used_oos": False,
        "scenario_count": len(SCENARIOS),
        "scenarios": [asdict(item) for item in SCENARIOS],
        "artifacts": {
            "oos": "oos.csv",
            "original_vs_causal": "original-vs-causal.csv",
            "raw_pattern": "raw/{scenario}__{equity,trades,orders,holdings,signals}.csv",
        },
        "limitations": [
            "source vintage is B rather than strict A",
            "the source did not declare costs; its published-cost replay is only a proxy",
            "ETF price-limit state is reconstructed from daily OHLC and previous close at B quality",
            "adjusted ETF prices do not reproduce every cash distribution and share-accounting detail",
            "the public backtest exposes aggregate metrics but not a pre-publication source hash",
        ],
        "results": _json_safe(results),
    }
    (CANDIDATE_DIR / "oos-run-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run(
    data_root: Path | None = None,
    *,
    refresh_index: bool = False,
) -> list[dict[str, Any]]:
    store = ResearchDataStore(data_root)
    bars = load_etf_bars(store)
    if bars["trade_date"].max() < OOS_END:
        raise ValueError(
            f"ETF data ends at {bars['trade_date'].max():%Y-%m-%d}, "
            f"expected {OOS_END:%Y-%m-%d}"
        )
    signal_close, index_evidence = load_signal_index(store, refresh=refresh_index)
    market_state = build_market_state(bars)
    results = []
    frames_by_scenario = {}
    for scenario in SCENARIOS:
        metrics, frames = run_scenario(bars, market_state, signal_close, scenario)
        results.append(metrics)
        frames_by_scenario[scenario.name] = frames
    write_outputs(store, index_evidence, results, frames_by_scenario)
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--refresh-index", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    results = run(args.data_root, refresh_index=args.refresh_index)
    summary = [
        {
            "scenario": row["scenario"],
            "annualized_return": row["annualized_return"],
            "maximum_drawdown": row["maximum_drawdown"],
            "sharpe": row["sharpe"],
            "risk_off_transition_count": row["risk_off_transition_count"],
            "risk_on_transition_count": row["risk_on_transition_count"],
        }
        for row in results
    ]
    print(json.dumps(_json_safe(summary), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
