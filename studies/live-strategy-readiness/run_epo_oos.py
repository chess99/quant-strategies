"""运行多品种 ETF 动量 + EPO 的首轮未经调参发布后回放。"""

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
    scheduled_dates,
)
from quant_research.data.store import ResearchDataStore  # noqa: E402


CANDIDATE_ID = "multi-asset-etf-momentum-epo"
CANDIDATE_DIR = STUDY_DIR / "results" / CANDIDATE_ID
SOURCE_PATH = (
    ROOT
    / "joinquant_archive"
    / "sources"
    / "聚宽2026年精选"
    / "17多品种ETF动量轮动+EPO优化.py"
)
OOS_START = pd.Timestamp("2024-03-25")
OOS_END = pd.Timestamp("2026-07-24")
INITIAL_CASH = 100_000.0
MOMENTUM_DAYS = 34
STOCK_NUM = 3
EPO_W = 0.2
EPO_LAMBDA = 10.0
PRICE_HISTORY_DAYS = 1200

JQ_SYMBOLS = (
    "518880.XSHG",
    "159985.XSHE",
    "513100.XSHG",
    "510300.XSHG",
    "159915.XSHE",
    "159992.XSHE",
    "515700.XSHG",
    "510150.XSHG",
    "515790.XSHG",
    "515880.XSHG",
    "512720.XSHG",
    "512660.XSHG",
    "159740.XSHE",
)


def to_local_symbol(symbol: str) -> str:
    code, exchange = symbol.upper().split(".")
    return ("SH" if exchange == "XSHG" else "SZ") + code


ETF_SYMBOLS = tuple(to_local_symbol(symbol) for symbol in JQ_SYMBOLS)


@dataclass(frozen=True)
class Scenario:
    name: str
    method: str
    commission_rate: float
    minimum_commission: float
    slippage_rate: float
    maximum_volume_ratio: float
    cost_label: str
    execution_policy: str


SCENARIOS = (
    Scenario(
        name="frozen-original-cost",
        method="epo",
        commission_rate=0.0002,
        minimum_commission=5.0,
        slippage_rate=0.0,
        maximum_volume_ratio=1.0,
        cost_label="published zero slippage",
        execution_policy="source-sequential",
    ),
    Scenario(
        name="causal-baseline-cost",
        method="epo",
        commission_rate=0.0003,
        minimum_commission=5.0,
        slippage_rate=0.0005,
        maximum_volume_ratio=0.01,
        cost_label="realistic baseline",
        execution_policy="sell-first",
    ),
    Scenario(
        name="causal-double-cost",
        method="epo",
        commission_rate=0.0006,
        minimum_commission=5.0,
        slippage_rate=0.0010,
        maximum_volume_ratio=0.01,
        cost_label="double friction",
        execution_policy="sell-first",
    ),
    Scenario(
        name="equal-top3-baseline-cost",
        method="equal-top3",
        commission_rate=0.0003,
        minimum_commission=5.0,
        slippage_rate=0.0005,
        maximum_volume_ratio=0.01,
        cost_label="realistic baseline",
        execution_policy="sell-first",
    ),
    Scenario(
        name="equal-pool-baseline-cost",
        method="equal-pool",
        commission_rate=0.0003,
        minimum_commission=5.0,
        slippage_rate=0.0005,
        maximum_volume_ratio=0.01,
        cost_label="realistic baseline",
        execution_policy="sell-first",
    ),
)

PUBLIC_BACKTEST = {
    "scenario": "published-public-backtest",
    "evidence_scope": "public in-sample aggregate",
    "period_start": "2019-01-01",
    "period_end": "2024-03-21",
    "initial_cash": 100000.0,
    "total_return": 3.03079423,
    "annualized_return": 0.30320783,
    "maximum_drawdown": 0.27016398,
    "sharpe": 1.2812408172336,
    "sortino": 1.7762029936294,
    "turnover": 0.02676566,
    "comparable_to_oos": False,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def momentum_score(close: pd.Series, days: int = MOMENTUM_DAYS) -> float:
    values = pd.to_numeric(close, errors="coerce").dropna().tail(days).to_numpy(dtype=float)
    if len(values) != days or np.any(values <= 0.0):
        return float("nan")
    y = np.log(values)
    x = np.arange(len(y), dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    fitted = slope * x + intercept
    denominator = float(np.sum((y - y.mean()) ** 2))
    if denominator <= 0.0:
        return float("nan")
    r_squared = 1.0 - float(np.sum((y - fitted) ** 2)) / denominator
    return float((math.exp(slope * 250.0) - 1.0) * r_squared)


def epo_weights(returns: pd.DataFrame, w: float = EPO_W) -> pd.Series:
    """复现原帖 anchored/endogenous EPO；lambda 在该分支中实际不参与计算。"""
    if returns.empty or returns.shape[1] == 0:
        raise ValueError("EPO returns must not be empty")
    covariance = returns.cov()
    variances = np.diag(covariance.to_numpy(dtype=float))
    if not np.isfinite(variances).all() or np.any(variances <= 0.0):
        raise ValueError("EPO covariance contains non-positive variance")
    correlation = returns.corr().to_numpy(dtype=float)
    if not np.isfinite(correlation).all():
        raise ValueError("EPO correlation contains non-finite values")
    identity = np.eye(len(variances))
    diagonal_variance = np.diag(variances)
    standard_deviation = np.diag(np.sqrt(variances))
    shrunk_correlation = (1.0 - w) * correlation + w * identity
    shrunk_covariance = standard_deviation @ shrunk_correlation @ standard_deviation
    inverse = np.linalg.solve(shrunk_covariance, identity)
    signal = returns.mean().to_numpy(dtype=float)
    anchor = (1.0 / variances) / np.sum(1.0 / variances)
    numerator = float(np.sqrt(anchor.T @ shrunk_covariance @ anchor))
    denominator = float(
        np.sqrt(signal.T @ inverse @ shrunk_covariance @ inverse @ signal)
    )
    if denominator <= 0.0 or not np.isfinite(denominator):
        raise ValueError("EPO endogenous gamma denominator is invalid")
    gamma = numerator / denominator
    raw = inverse @ (
        (1.0 - w) * gamma * signal + w * diagonal_variance @ anchor
    )
    clipped = np.clip(raw, 0.0, None)
    if clipped.sum() <= 0.0:
        raise ValueError("EPO produced no positive weights")
    return pd.Series(clipped / clipped.sum(), index=returns.columns, dtype=float)


def build_target_weights(
    close: pd.DataFrame,
    observation_date,
    *,
    method: str,
    momentum_days: int = MOMENTUM_DAYS,
    stock_num: int = STOCK_NUM,
    epo_w: float = EPO_W,
    price_history_days: int = PRICE_HISTORY_DAYS,
) -> tuple[dict[str, float], dict[str, Any]]:
    observation = pd.Timestamp(observation_date).normalize()
    history = close.loc[close.index <= observation]
    if history.empty:
        return {}, {"observation_date": observation.strftime("%Y-%m-%d"), "reason": "no_history"}
    available = [
        symbol
        for symbol in close.columns
        if history[symbol].notna().any()
        and pd.notna(history[symbol].dropna().index.max())
        and history[symbol].dropna().index.max() == history.index[-1]
    ]
    scores = {symbol: momentum_score(history[symbol], momentum_days) for symbol in available}
    ranked = sorted(
        ((symbol, score) for symbol, score in scores.items() if np.isfinite(score) and score > 0.0),
        key=lambda item: (-item[1], item[0]),
    )
    selected = [symbol for symbol, _ in ranked[:stock_num]]
    diagnostics: dict[str, Any] = {
        "observation_date": observation.strftime("%Y-%m-%d"),
        "method": method,
        "selected": selected,
        "scores": {symbol: float(score) if np.isfinite(score) else None for symbol, score in scores.items()},
    }
    if method == "equal-pool":
        eligible = [
            symbol
            for symbol in available
            if len(history[symbol].dropna().tail(momentum_days)) == momentum_days
        ]
        weights = {symbol: 1.0 / len(eligible) for symbol in eligible} if eligible else {}
    elif not selected:
        weights = {}
    elif method == "equal-top3":
        weights = {symbol: 1.0 / len(selected) for symbol in selected}
    elif method == "epo":
        price_window = history[selected].tail(price_history_days).ffill()
        returns = price_window.pct_change(fill_method=None).dropna(how="any")
        if len(returns) < 60:
            weights = {}
            diagnostics["reason"] = "insufficient_common_returns"
        else:
            optimized = epo_weights(returns, w=epo_w)
            weights = optimized.to_dict()
            diagnostics["common_return_days"] = len(returns)
    else:
        raise ValueError(f"unsupported method: {method}")
    diagnostics["weights"] = {symbol: float(weight) for symbol, weight in weights.items()}
    return weights, diagnostics


def load_bars(store: ResearchDataStore) -> pd.DataFrame:
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
        ETF_SYMBOLS,
        columns=columns,
        strict=True,
    )
    bars["trade_date"] = pd.to_datetime(bars["trade_date"]).dt.normalize()
    return bars.sort_values(["trade_date", "symbol"]).reset_index(drop=True)


def build_market_state(raw_bars: pd.DataFrame) -> pd.DataFrame:
    state = raw_bars[["symbol", "trade_date", "open", "low", "close", "volume"]].copy()
    state["previous_close"] = state.groupby("symbol")["close"].shift(1)
    state["paused"] = state["volume"].fillna(0).le(0)
    state["is_st"] = False
    # ETF 通常为 10% 涨跌幅；只在开盘且最低/最高价同时锁在边界附近时阻塞。
    up_ratio = state["open"] / state["previous_close"]
    down_ratio = up_ratio
    state["buy_blocked"] = up_ratio.ge(1.095) & (
        state["low"] / state["previous_close"]
    ).ge(1.095)
    state["sell_blocked"] = down_ratio.le(0.905) & (
        state["open"] / state["previous_close"]
    ).le(0.905)
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
    close = bars.pivot(index="trade_date", columns="symbol", values="adjusted_close").sort_index()
    oos_bars = bars[bars["trade_date"].between(OOS_START, OOS_END)].copy()
    engine_bars = oos_bars[
        ["symbol", "trade_date", "adjusted_open", "adjusted_close", "volume"]
    ].rename(columns={"adjusted_open": "open", "adjusted_close": "close"})
    oos_state = market_state[market_state["trade_date"].between(OOS_START, OOS_END)].copy()
    calendar = pd.DatetimeIndex(sorted(oos_bars["trade_date"].unique()))
    target_rows: list[dict[str, Any]] = []

    def target_provider(previous_date, trade_date):
        if previous_date is None:
            return None
        weights, diagnostics = build_target_weights(
            close,
            previous_date,
            method=scenario.method,
            momentum_days=MOMENTUM_DAYS,
            stock_num=STOCK_NUM,
            epo_w=EPO_W,
            price_history_days=PRICE_HISTORY_DAYS,
        )
        target_rows.append(
            {
                "trade_date": pd.Timestamp(trade_date),
                "observation_date": pd.Timestamp(previous_date),
                "method": scenario.method,
                "selected": "|".join(diagnostics.get("selected", [])),
                "weights_json": json.dumps(weights, ensure_ascii=False, sort_keys=True),
                "scores_json": json.dumps(
                    diagnostics.get("scores", {}), ensure_ascii=False, sort_keys=True
                ),
                "common_return_days": diagnostics.get("common_return_days"),
                "reason": diagnostics.get("reason"),
            }
        )
        return weights

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
    schedule = scheduled_dates(calendar, frequency="monthly", when="first")
    previous_date = None
    for trade_date in calendar:
        if trade_date in schedule and previous_date is not None:
            weights = target_provider(previous_date, trade_date)
            if scenario.execution_policy == "source-sequential":
                selected = list(weights)
                total_value = engine.total_value(trade_date, field="open")
                for symbol in list(engine.positions):
                    if symbol not in selected:
                        engine.order_target_value(trade_date, symbol, 0.0, execution="open")
                for symbol, weight in weights.items():
                    engine.order_target_value(
                        trade_date,
                        symbol,
                        total_value * weight,
                        execution="open",
                    )
            elif scenario.execution_policy == "sell-first":
                engine.rebalance_to_weights(trade_date, weights, execution="open")
            else:
                raise ValueError(
                    f"unsupported execution policy: {scenario.execution_policy}"
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
            "parameter_selection_used_oos": False,
        }
    )
    frames = {
        "equity": equity,
        "trades": engine.trades,
        "orders": engine.orders,
        "holdings": engine.holdings,
        "targets": pd.DataFrame(target_rows),
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
    output_rows = []
    for result in results:
        row = {key: value for key, value in result.items() if key != "yearly_returns"}
        row["yearly_returns_json"] = json.dumps(
            result["yearly_returns"], ensure_ascii=False, sort_keys=True
        )
        output_rows.append(row)
        scenario = result["scenario"]
        for label, frame in frames_by_scenario[scenario].items():
            frame.to_csv(
                raw_dir / f"{scenario}__{label}.csv",
                index=False,
                encoding="utf-8",
            )
    oos = pd.DataFrame(output_rows)
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
            "etf_pool": list(JQ_SYMBOLS),
            "stock_num": STOCK_NUM,
            "momentum_days": MOMENTUM_DAYS,
            "epo_lambda": EPO_LAMBDA,
            "epo_w": EPO_W,
            "price_history_days": PRICE_HISTORY_DAYS,
        },
        "parameter_selection_used_oos": False,
        "scenario_count": len(SCENARIOS),
        "scenarios": [asdict(item) for item in SCENARIOS],
        "artifacts": {
            "oos": "oos.csv",
            "original_vs_causal": "original-vs-causal.csv",
            "raw_pattern": "raw/{scenario}__{equity,trades,orders,holdings,targets}.csv",
        },
        "limitations": [
            "source vintage is B rather than strict A",
            "ETF premium/discount and subscription limits are not present in daily bars",
            "ETF price-limit state is reconstructed from daily OHLC and previous close at B quality",
            "public backtest exposes aggregate metrics but not a frozen pre-publication source hash",
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
            f"ETF data ends at {bars['trade_date'].max():%Y-%m-%d}, expected {OOS_END:%Y-%m-%d}"
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
            "trade_count": row["trade_count"],
        }
        for row in results
    ]
    print(json.dumps(_json_safe(summary), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
