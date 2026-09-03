"""运行沪深 300 ETF 10/60 均线的首次未经调参发布后回放。"""

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
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quant_research.backtest import (  # noqa: E402
    BacktestConfig,
    CostModel,
    DailyBacktester,
    performance_metrics,
)
from quant_research.data.store import ResearchDataStore  # noqa: E402


CANDIDATE_ID = "csi300-ma10-60-cash"
CANDIDATE_DIR = STUDY_DIR / "results" / CANDIDATE_ID
SOURCE_PATH = (
    ROOT
    / "joinquant_archive"
    / "sources"
    / "2020年度精选策略"
    / "83 沪深300ETF-1060双均线.py"
)
OOS_START = pd.Timestamp("2018-11-15")
OOS_END = pd.Timestamp("2026-07-24")
INITIAL_CASH = 200_000.0
RISK_SYMBOL = "SH510310"
SHORT_WINDOW = 10
LONG_WINDOW = 60


@dataclass(frozen=True)
class Scenario:
    name: str
    method: str
    commission_rate: float
    minimum_commission: float
    slippage_rate: float
    maximum_volume_ratio: float
    execution_policy: str
    asset_type: str
    fixed_sell_tax: float | None
    cost_label: str


@dataclass(frozen=True)
class FixedTaxCostModel(CostModel):
    fixed_sell_tax: float | None = None

    def stamp_tax_rate(self, asset_type: str, side: str, trade_date) -> float:
        if self.fixed_sell_tax is not None:
            return self.fixed_sell_tax if side == "sell" else 0.0
        return super().stamp_tax_rate(asset_type, side, trade_date)


SCENARIOS = (
    Scenario(
        name="frozen-source-cost",
        method="ma-switch",
        commission_rate=0.0003,
        minimum_commission=5.0,
        slippage_rate=0.0,
        maximum_volume_ratio=1.0,
        execution_policy="source-daily-order",
        asset_type="stock",
        fixed_sell_tax=0.001,
        cost_label="source-declared stock costs including incorrect ETF sell tax",
    ),
    Scenario(
        name="causal-baseline-cost",
        method="ma-switch",
        commission_rate=0.0003,
        minimum_commission=5.0,
        slippage_rate=0.0005,
        maximum_volume_ratio=0.01,
        execution_policy="source-daily-order",
        asset_type="etf",
        fixed_sell_tax=None,
        cost_label="realistic ETF baseline",
    ),
    Scenario(
        name="causal-double-cost",
        method="ma-switch",
        commission_rate=0.0006,
        minimum_commission=5.0,
        slippage_rate=0.0010,
        maximum_volume_ratio=0.01,
        execution_policy="source-daily-order",
        asset_type="etf",
        fixed_sell_tax=None,
        cost_label="double ETF friction",
    ),
    Scenario(
        name="csi300-buy-hold",
        method="risk-buy-hold",
        commission_rate=0.0003,
        minimum_commission=5.0,
        slippage_rate=0.0005,
        maximum_volume_ratio=0.01,
        execution_policy="transition-only",
        asset_type="etf",
        fixed_sell_tax=None,
        cost_label="realistic ETF baseline",
    ),
    Scenario(
        name="static-50pct-cash",
        method="static-half",
        commission_rate=0.0003,
        minimum_commission=5.0,
        slippage_rate=0.0005,
        maximum_volume_ratio=0.01,
        execution_policy="transition-only",
        asset_type="etf",
        fixed_sell_tax=None,
        cost_label="realistic ETF baseline",
    ),
)


PUBLIC_BACKTEST = {
    "scenario": "published-public-backtest",
    "evidence_scope": "public in-sample aggregate",
    "period_start": "2014-06-01",
    "period_end": "2018-11-13",
    "initial_cash": 200_000.0,
    "total_return": 1.19983955,
    "annualized_return": 0.19860036027847,
    "maximum_drawdown": 0.21495593824082,
    "sharpe": 0.89307295642685,
    "sortino": 1.1587412813685,
    "comparable_to_oos": False,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ma_signal(
    close: pd.Series,
    observation_date,
    *,
    short_window: int = SHORT_WINDOW,
    long_window: int = LONG_WINDOW,
) -> int:
    """按冻结源码返回 1=全仓、0=空仓、-1=均线相等或数据不足。"""

    if short_window <= 0 or long_window <= short_window:
        raise ValueError("moving-average windows must satisfy 0 < short < long")
    observation = pd.Timestamp(observation_date).normalize()
    values = (
        pd.to_numeric(close.loc[close.index <= observation], errors="coerce")
        .dropna()
        .tail(long_window)
    )
    if len(values) != long_window:
        return -1
    short_mean = float(values.tail(short_window).mean())
    long_mean = float(values.mean())
    if short_mean > long_mean:
        return 1
    if short_mean < long_mean:
        return 0
    return -1


def load_bars(store: ResearchDataStore) -> pd.DataFrame:
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


def _shares(engine: DailyBacktester) -> int:
    position = engine.positions.get(RISK_SYMBOL)
    return 0 if position is None else int(position.shares)


def _can_buy_one_lot(engine: DailyBacktester, trade_date) -> bool:
    bar = engine._bar(trade_date, RISK_SYMBOL)
    if bar is None or not engine._valid_price(bar.get("open")):
        return False
    price = float(bar["open"]) * (1.0 + engine.config.slippage_rate)
    gross = engine.config.lot_size * price
    commission, tax = engine.costs.fees(
        engine._asset_type(RISK_SYMBOL), "buy", gross, trade_date
    )
    return engine.cash + 1e-9 >= gross + commission + tax


def _apply_ma_signal(
    engine: DailyBacktester,
    trade_date,
    signal: int,
    *,
    execution_policy: str,
) -> str:
    shares_before = _shares(engine)
    if signal == 1:
        if execution_policy == "source-daily-order" and _can_buy_one_lot(
            engine, trade_date
        ):
            engine.order_value(trade_date, RISK_SYMBOL, engine.cash, execution="open")
        elif shares_before == 0:
            engine.rebalance_to_weights(
                trade_date, {RISK_SYMBOL: 1.0}, execution="open"
            )
        return "risk-on" if shares_before == 0 and _shares(engine) > 0 else "hold"
    if signal == 0 and shares_before > 0:
        engine.order_target(trade_date, RISK_SYMBOL, 0, execution="open")
        return "risk-off" if _shares(engine) == 0 else "risk-off-partial"
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
    scenario: Scenario,
) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    close = bars.pivot(
        index="trade_date", columns="symbol", values="adjusted_close"
    )[RISK_SYMBOL].sort_index()
    oos_bars = bars[bars["trade_date"].between(OOS_START, OOS_END)].copy()
    engine_bars = oos_bars[
        ["symbol", "trade_date", "adjusted_open", "adjusted_close", "volume"]
    ].rename(columns={"adjusted_open": "open", "adjusted_close": "close"})
    oos_state = market_state[market_state["trade_date"].between(OOS_START, OOS_END)].copy()
    calendar = pd.DatetimeIndex(sorted(oos_bars["trade_date"].unique()))
    asset_type = scenario.asset_type
    t_plus_one = ("stock", "etf")
    engine = DailyBacktester(
        engine_bars,
        oos_state,
        asset_types={RISK_SYMBOL: asset_type},
        config=BacktestConfig(
            initial_cash=INITIAL_CASH,
            lot_size=100,
            maximum_volume_ratio=scenario.maximum_volume_ratio,
            slippage_rate=scenario.slippage_rate,
            t_plus_one_asset_types=t_plus_one,
            minimum_state_quality="B",
        ),
        costs=FixedTaxCostModel(
            buy_commission=scenario.commission_rate,
            sell_commission=scenario.commission_rate,
            minimum_commission=scenario.minimum_commission,
            etf_buy_commission=scenario.commission_rate,
            etf_sell_commission=scenario.commission_rate,
            etf_minimum_commission=scenario.minimum_commission,
            fixed_sell_tax=scenario.fixed_sell_tax,
        ),
    )
    signal_rows: list[dict[str, Any]] = []
    previous_date = None
    for trade_date in calendar:
        signal = -1
        action = "hold"
        if scenario.method == "ma-switch" and previous_date is not None:
            signal = ma_signal(close, previous_date)
            action = _apply_ma_signal(
                engine,
                trade_date,
                signal,
                execution_policy=scenario.execution_policy,
            )
        elif scenario.method == "risk-buy-hold":
            shares_before = _shares(engine)
            if _can_buy_one_lot(engine, trade_date):
                engine.order_value(trade_date, RISK_SYMBOL, engine.cash, execution="open")
            action = "initial-risk" if shares_before == 0 and _shares(engine) > 0 else "hold"
        elif scenario.method == "static-half" and trade_date == calendar[0]:
            engine.rebalance_to_weights(
                trade_date, {RISK_SYMBOL: 0.5}, execution="open"
            )
            action = "initial-half-risk"
        signal_rows.append(
            {
                "trade_date": pd.Timestamp(trade_date),
                "observation_date": (
                    pd.NaT if previous_date is None else pd.Timestamp(previous_date)
                ),
                "signal": signal,
                "action": action,
                "shares_after_orders": _shares(engine),
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
        "frozen_parameters": {
            "risk_asset": "510310.XSHG",
            "short_window_days": SHORT_WINDOW,
            "long_window_days": LONG_WINDOW,
            "risk_on_weight": 1.0,
            "risk_off_weight": 0.0,
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
            "ETF price-limit state is reconstructed from daily OHLC and previous close at B quality",
            "adjusted ETF prices do not reproduce every cash distribution and share-accounting detail",
            "cash receives zero interest, so risk-off returns are conservative",
            "the public backtest exposes aggregate metrics but not a pre-publication source hash",
        ],
        "results": _json_safe(results),
    }
    (CANDIDATE_DIR / "oos-run-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run(data_root: Path | None = None) -> list[dict[str, Any]]:
    store = ResearchDataStore(data_root)
    bars = load_bars(store)
    if bars["trade_date"].max() < OOS_END:
        raise ValueError(
            f"ETF data ends at {bars['trade_date'].max():%Y-%m-%d}, "
            f"expected {OOS_END:%Y-%m-%d}"
        )
    market_state = build_market_state(bars)
    results = []
    frames_by_scenario = {}
    for scenario in SCENARIOS:
        metrics, frames = run_scenario(bars, market_state, scenario)
        results.append(metrics)
        frames_by_scenario[scenario.name] = frames
    write_outputs(store, results, frames_by_scenario)
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
            "risk_off_transition_count": row["risk_off_transition_count"],
            "risk_on_transition_count": row["risk_on_transition_count"],
        }
        for row in results
    ]
    print(json.dumps(_json_safe(summary), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
